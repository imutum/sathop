"""Worker /events endpoint + lease-sweeper coverage of the in-flight states
(queued/downloading/downloaded/processing/processed/uploading)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.worker_leases import renew_worker_leases
from sathop.orchestrator.background import sweep_expired_leases
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.state_machine import GranuleState


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


async def _seed(
    granule_id: str = "g1",
    state: str = GranuleState.QUEUED.value,
    leased_by: str | None = "w1",
    expires_in: timedelta = timedelta(minutes=30),
) -> None:
    async with orch_db._session_maker() as s:
        if await s.get(Worker, "w1") is None:
            s.add(Worker(worker_id="w1", version="t", capacity=10))
        if await s.get(Batch, "b") is None:
            s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=granule_id,
                batch_id="b",
                state=state,
                inputs_json="[]",
                leased_by=leased_by,
                lease_expires_at=(utcnow() + expires_in) if leased_by else None,
            )
        )
        await s.commit()


async def _state(granule_id: str) -> str:
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, granule_id)
        assert g is not None
        return g.state


def _emit(client, kind: str, gid: str = "g1", worker_id: str = "w1", **extra):
    return client.post(
        "/api/workers/events",
        json={"kind": kind, "granule_id": gid, "worker_id": worker_id, **extra},
    )


# ─── happy path ────────────────────────────────────────────────────────────


_FORWARD_CHAIN = [
    ("download_started", GranuleState.DOWNLOADING.value),
    ("download_finished", GranuleState.DOWNLOADED.value),
    ("process_started", GranuleState.PROCESSING.value),
    ("process_finished", GranuleState.PROCESSED.value),
    ("upload_started", GranuleState.UPLOADING.value),
]


async def test_full_forward_chain(client):
    await _seed()
    for kind, expected in _FORWARD_CHAIN:
        r = _emit(client, kind)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == expected
        assert await _state("g1") == expected


# ─── ownership + transition guards ─────────────────────────────────────────


async def test_rejects_when_worker_does_not_hold_lease(client):
    await _seed(leased_by="w-other")
    r = _emit(client, "download_started", worker_id="w1")
    assert r.status_code == 409
    assert await _state("g1") == GranuleState.QUEUED.value


async def test_rejects_skipping_intermediate(client):
    """From QUEUED you cannot jump straight to DOWNLOADED — DownloadStarted is
    required to mark the start of byte transfer."""
    await _seed()
    r = _emit(client, "download_finished")
    assert r.status_code == 409
    assert await _state("g1") == GranuleState.QUEUED.value


async def test_rejects_backwards_transition(client):
    await _seed(state=GranuleState.PROCESSING.value)
    r = _emit(client, "download_finished")
    assert r.status_code == 409


async def test_rejects_unknown_granule(client):
    await _seed()
    r = _emit(client, "download_started", gid="ghost")
    assert r.status_code == 404


async def test_rejects_unknown_event_kind(client):
    await _seed()
    r = client.post(
        "/api/workers/events",
        json={"kind": "made_up_event", "granule_id": "g1", "worker_id": "w1"},
    )
    # Pydantic rejects unknown discriminator value with 422.
    assert r.status_code == 422


# ─── lease-sweeper coverage of the new in-flight states ────────────────────


@pytest.mark.parametrize(
    "state",
    [
        GranuleState.QUEUED.value,
        GranuleState.DOWNLOADING.value,
        GranuleState.DOWNLOADED.value,
        GranuleState.PROCESSING.value,
        GranuleState.PROCESSED.value,
        GranuleState.UPLOADING.value,
    ],
)
async def test_sweeper_reclaims_expired_lease_in_any_in_flight_state(client, state):
    await _seed(state=state, expires_in=timedelta(minutes=-1))
    n = await sweep_expired_leases()
    assert n == 1
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g is not None
        assert g.state == GranuleState.PENDING.value
        assert g.leased_by is None
        assert g.lease_expires_at is None


async def test_sweeper_ignores_uploaded(client):
    """UPLOADED has already cleared leased_by — nothing to reclaim."""
    await _seed(state=GranuleState.UPLOADED.value, leased_by=None)
    assert await sweep_expired_leases() == 0


async def test_sweeper_ignores_unexpired(client):
    await _seed(state=GranuleState.PROCESSING.value, expires_in=timedelta(minutes=5))
    assert await sweep_expired_leases() == 0


async def test_heartbeat_renews_only_leases_near_expiry(client):
    await _seed(granule_id="fresh", state=GranuleState.PROCESSING.value, expires_in=timedelta(minutes=25))
    await _seed(granule_id="stale", state=GranuleState.PROCESSING.value, expires_in=timedelta(minutes=10))
    now = utcnow()
    async with orch_db._session_maker() as s:
        fresh = await s.get(Granule, "fresh")
        stale = await s.get(Granule, "stale")
        assert fresh is not None and fresh.lease_expires_at is not None
        assert stale is not None and stale.lease_expires_at is not None
        fresh_before = fresh.lease_expires_at
        stale_before = stale.lease_expires_at
        await renew_worker_leases(s, "w1", now)
        await s.commit()

    async with orch_db._session_maker() as s:
        fresh = await s.get(Granule, "fresh")
        stale = await s.get(Granule, "stale")
        assert fresh is not None and fresh.lease_expires_at == fresh_before
        assert stale is not None and stale.lease_expires_at is not None
        assert stale.lease_expires_at > stale_before
