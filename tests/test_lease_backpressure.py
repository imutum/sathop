"""Per-worker max-inflight cap on /api/workers/lease.

Covers:
  • cap=0 (default) leaves behavior unchanged
  • cap=N refuses lease when worker already holds N pre-upload granules
  • cap=N refuses when worker holds N post-upload objects (not yet deleted)
  • cap=N mixes pre + post state correctly
  • terminal (deleted/failed) granules don't count against the cap
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Batch, Granule, GranuleObject, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
        max_inflight_per_worker=0,  # baseline; per-test overrides bump this
    )
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_worker(worker_id: str = "w1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=10, public_url=None))
        await s.commit()


async def _seed_granule(
    gid: str,
    batch_id: str,
    state: str,
    leased_by: str | None = None,
) -> None:
    async with orch_db._session_maker() as s:
        if await s.get(Batch, batch_id) is None:
            s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=gid,
                batch_id=batch_id,
                state=state,
                inputs=[],
                leased_by=leased_by,
                lease_expires_at=utcnow() if leased_by else None,
            )
        )
        await s.commit()


async def _seed_object(granule_id: str, worker_id: str, deleted: bool = False) -> None:
    async with orch_db._session_maker() as s:
        s.add(
            GranuleObject(
                granule_id=granule_id,
                worker_id=worker_id,
                object_key=f"{granule_id}/out.nc",
                presigned_url="http://x/y",
                sha256="0" * 64,
                size=1,
                deleted_at=utcnow() if deleted else None,
            )
        )
        await s.commit()


# ─── cap=0: unchanged behavior ──────────────────────────────────────────────


async def test_cap_zero_leases_all_up_to_capacity(client):
    await _seed_worker()
    for i in range(5):
        await _seed_granule(f"g{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 5


# ─── cap=N enforcement ─────────────────────────────────────────────────────


async def test_cap_blocks_when_pre_upload_holdings_at_cap(client, patch_settings):
    patch_settings(max_inflight_per_worker=2)
    await _seed_worker()
    # Worker already holds 2 pre-upload granules
    for i in range(2):
        await _seed_granule(f"held-{i}", "b", GranuleState.DOWNLOADING.value, leased_by="w1")
    # 3 pending waiting — cap says zero new leases
    for i in range(3):
        await _seed_granule(f"want-{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_cap_allows_partial_lease_when_under_cap(client, patch_settings):
    patch_settings(max_inflight_per_worker=3)
    await _seed_worker()
    await _seed_granule("held-0", "b", GranuleState.PROCESSING.value, leased_by="w1")
    # 5 pending; cap 3 minus 1 held = 2 new leases
    for i in range(5):
        await _seed_granule(f"want-{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert len(r.json()["items"]) == 2


async def test_cap_counts_post_upload_objects_still_on_worker(client, patch_settings):
    """UPLOADED clears leased_by, but objects still live on the worker until
    receiver acks + delete-confirms. Those count against the cap."""
    patch_settings(max_inflight_per_worker=2)
    await _seed_worker()
    # Granule is UPLOADED (no leased_by), but object still on worker
    await _seed_granule("up1", "b", GranuleState.UPLOADED.value)
    await _seed_object("up1", "w1")
    await _seed_granule("up2", "b", GranuleState.ACKED.value)
    await _seed_object("up2", "w1")
    # 3 pending
    for i in range(3):
        await _seed_granule(f"want-{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert r.json()["items"] == []


async def test_cap_ignores_already_deleted_objects(client, patch_settings):
    patch_settings(max_inflight_per_worker=2)
    await _seed_worker()
    # Object exists but is marked deleted → no storage held
    await _seed_granule("old", "b", GranuleState.DELETED.value)
    await _seed_object("old", "w1", deleted=True)
    for i in range(3):
        await _seed_granule(f"want-{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert len(r.json()["items"]) == 2


async def test_cap_mixes_pre_and_post(client, patch_settings):
    """1 pre-upload leased + 1 post-upload object = 2 held; cap=2 blocks."""
    patch_settings(max_inflight_per_worker=2)
    await _seed_worker()
    await _seed_granule("dl", "b", GranuleState.DOWNLOADING.value, leased_by="w1")
    await _seed_granule("up", "b", GranuleState.UPLOADED.value)
    await _seed_object("up", "w1")
    await _seed_granule("want", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 10})
    assert r.json()["items"] == []


async def test_cap_does_not_affect_other_workers(client, patch_settings):
    """w1 at cap; w2 has no holdings and should lease freely."""
    patch_settings(max_inflight_per_worker=2)
    await _seed_worker("w1")
    await _seed_worker("w2")
    for i in range(2):
        await _seed_granule(f"w1-held-{i}", "b", GranuleState.DOWNLOADING.value, leased_by="w1")
    for i in range(3):
        await _seed_granule(f"want-{i}", "b", GranuleState.PENDING.value)

    r = client.post("/api/workers/lease", json={"worker_id": "w2", "capacity": 10})
    assert len(r.json()["items"]) == 2  # w2 cap is fresh
