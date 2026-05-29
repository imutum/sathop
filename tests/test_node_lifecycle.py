"""Worker remove + pause, receiver enable + forget endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Batch, Granule, Receiver, Worker
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
        max_inflight_per_worker=0,
    )
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _add_worker(worker_id: str = "w1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=4))
        await s.commit()


async def _add_receiver(receiver_id: str = "r1", enabled: bool = True) -> None:
    async with orch_db._session_maker() as s:
        s.add(Receiver(receiver_id=receiver_id, version="t", platform="linux", enabled=enabled))
        await s.commit()


async def _seed_granule(
    worker_id: str,
    state: str = GranuleState.DOWNLOADING.value,
    granule_id: str | None = None,
) -> None:
    async with orch_db._session_maker() as s:
        if await s.get(Batch, "b") is None:
            s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=granule_id or f"g-{state}",
                batch_id="b",
                state=state,
                inputs=[],
                leased_by=worker_id,
            )
        )
        await s.commit()


# ─── worker remove ─────────────────────────────────────────────────────────


async def test_worker_remove_marks_removed_at(client):
    await _add_worker()
    r = client.delete("/api/workers/w1")
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w is not None
        assert w.removed_at is not None


async def test_worker_remove_idempotent(client):
    await _add_worker()
    assert client.delete("/api/workers/w1").status_code == 200
    assert client.delete("/api/workers/w1").status_code == 200


async def test_worker_remove_heartbeat_returns_removed(client):
    await _add_worker()
    client.delete("/api/workers/w1")
    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.status_code == 200
    assert r.json()["removed"] is True


async def test_worker_remove_blocks_re_register(client):
    await _add_worker()
    client.delete("/api/workers/w1")
    r = client.post(
        "/api/workers/register",
        json={"worker_id": "w1", "version": "0.1.0", "capacity": 4},
    )
    assert r.status_code == 410


async def test_worker_remove_blocks_lease(client):
    await _add_worker()
    client.delete("/api/workers/w1")
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 4})
    assert r.status_code == 403


async def test_worker_remove_404_when_unknown(client):
    r = client.delete("/api/workers/ghost")
    assert r.status_code == 404


async def test_worker_remove_force_revokes_leases(client):
    await _add_worker()
    await _seed_granule("w1", state=GranuleState.DOWNLOADING.value, granule_id="b:dl")
    r = client.delete("/api/workers/w1?force=true")
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "b:dl")
        assert g.state == GranuleState.PENDING.value


# ─── worker purge (physical delete of a history node) ──────────────────────


async def test_worker_purge_requires_removed_first(client):
    await _add_worker()
    r = client.delete("/api/workers/w1?purge=true")
    assert r.status_code == 409
    async with orch_db._session_maker() as s:
        assert await s.get(Worker, "w1") is not None


async def test_worker_purge_deletes_row(client):
    await _add_worker()
    client.delete("/api/workers/w1")
    r = client.delete("/api/workers/w1?purge=true")
    assert r.status_code == 200
    assert r.json()["purged"] is True
    async with orch_db._session_maker() as s:
        assert await s.get(Worker, "w1") is None


async def test_worker_purge_leaves_leased_by_dangling(client):
    # Purge only drops the worker row; the granule's leased_by string stays as a
    # now-orphaned reference (rendered as a deleted node client-side).
    await _add_worker()
    await _seed_granule("w1", state=GranuleState.DELETED.value, granule_id="b:done")
    client.delete("/api/workers/w1")
    assert client.delete("/api/workers/w1?purge=true").status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "b:done")
        assert g is not None
        assert g.leased_by == "w1"


async def test_worker_purge_404_when_unknown(client):
    r = client.delete("/api/workers/ghost?purge=true")
    assert r.status_code == 404


# ─── worker paused blocks lease ──────────────────────────────────────────


async def test_worker_paused_lease_returns_403(client):
    await _add_worker()
    client.put("/api/workers/w1/pause", json={"operator_paused": True})
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 4})
    assert r.status_code == 403


# ─── worker self-paused state surfaces in /api/workers ─────────────────────


async def test_worker_paused_round_trip_via_heartbeat(client):
    await _add_worker()
    r0 = client.get("/api/workers")
    assert r0.status_code == 200
    [row0] = r0.json()
    assert not row0["paused"]

    r = client.post(
        "/api/workers/heartbeat",
        json={"worker_id": "w1", "disk_used_gb": 90.0, "disk_total_gb": 100.0, "paused": True},
    )
    assert r.status_code == 200

    r1 = client.get("/api/workers")
    [row1] = r1.json()
    assert row1["paused"] is True

    client.post("/api/workers/heartbeat", json={"worker_id": "w1", "paused": False})
    [row2] = client.get("/api/workers").json()
    assert row2["paused"] is False


# ─── worker operator-set pause via heartbeat reply ────────────────────────


async def test_worker_pause_endpoint_propagates_via_heartbeat(client):
    await _add_worker()
    r = client.put("/api/workers/w1/pause", json={"operator_paused": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "operator_paused": True}

    [row] = client.get("/api/workers").json()
    assert row["operator_paused"] is True

    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.status_code == 200
    assert r.json()["operator_paused"] is True

    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.json()["operator_paused"] is True

    assert client.put("/api/workers/w1/pause", json={"operator_paused": False}).status_code == 200
    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.json()["operator_paused"] is False


async def test_worker_pause_404_when_unknown(client):
    r = client.put("/api/workers/ghost/pause", json={"operator_paused": True})
    assert r.status_code == 404


# ─── force-revoke worker leases ────────────────────────────────────────────


async def test_worker_revoke_all_resets_leases_to_pending(client):
    await _add_worker()
    await _seed_granule("w1", state=GranuleState.DOWNLOADING.value, granule_id="b:dl")
    await _seed_granule("w1", state=GranuleState.PROCESSED.value, granule_id="b:proc")
    r = client.post("/api/workers/w1/revoke-all")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "revoked": 2}

    async with orch_db._session_maker() as s:
        for gid in ("b:dl", "b:proc"):
            g = await s.get(Granule, gid)
            assert g is not None
            assert g.state == GranuleState.PENDING.value
            assert g.leased_by is None
            assert g.lease_expires_at is None
            assert g.retry_count == 1


async def test_worker_revoke_all_skips_terminal_granules(client):
    await _add_worker()
    await _seed_granule("w1", state=GranuleState.UPLOADED.value, granule_id="b:done")
    await _seed_granule("w1", state=GranuleState.DOWNLOADING.value, granule_id="b:dl")
    r = client.post("/api/workers/w1/revoke-all")
    assert r.json()["revoked"] == 1
    async with orch_db._session_maker() as s:
        done = await s.get(Granule, "b:done")
        assert done.state == GranuleState.UPLOADED.value


async def test_worker_revoke_all_404_when_unknown(client):
    assert client.post("/api/workers/ghost/revoke-all").status_code == 404


# ─── one-shot remote GC ────────────────────────────────────────────────────


async def test_worker_gc_endpoint_one_shot_via_heartbeat(client):
    await _add_worker()
    r = client.post("/api/workers/w1/gc")
    assert r.status_code == 200

    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["gc_requested"] is True
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["gc_requested"] is False


async def test_worker_gc_404_when_unknown(client):
    assert client.post("/api/workers/ghost/gc").status_code == 404


# ─── receiver enable/disable + forget ───────────────────────────────────────


async def test_receiver_disable_blocks_pull(client):
    await _add_receiver(enabled=False)
    r = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10})
    assert r.status_code == 403


async def test_receiver_enable_round_trip_and_forget(client):
    await _add_receiver()
    assert client.delete("/api/receivers/r1").status_code == 409
    assert client.put("/api/receivers/r1/enabled", json={"enabled": False}).status_code == 200
    r = client.delete("/api/receivers/r1")
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        assert (await s.get(Receiver, "r1")) is None


# ─── update-all ────────────────────────────────────────────────────────────


async def test_update_all_sends_to_active_workers(client):
    await _add_worker("w1")
    await _add_worker("w2")
    # pause w2 — should be skipped
    client.put("/api/workers/w2/pause", json={"operator_paused": True})
    r = client.post("/api/workers/update-all")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # w1 gets the signal
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["update_requested"] is True
    # w2 does not
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w2"}).json()
    assert body["update_requested"] is False


# ─── remove-all ────────────────────────────────────────────────────────────


async def test_remove_all_marks_all_workers(client):
    await _add_worker("w1")
    await _add_worker("w2")
    r = client.post("/api/workers/remove-all")
    assert r.status_code == 200
    assert r.json()["count"] == 2

    # both get removed signal
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["removed"] is True
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w2"}).json()
    assert body["removed"] is True

    # re-register blocked
    r = client.post("/api/workers/register", json={"worker_id": "w1", "version": "t", "capacity": 4})
    assert r.status_code == 410


async def test_remove_all_skips_already_removed(client):
    await _add_worker("w1")
    client.delete("/api/workers/w1")
    r = client.post("/api/workers/remove-all")
    assert r.json()["count"] == 0
