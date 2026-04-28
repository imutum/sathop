"""Worker state-transition endpoint + lease-sweeper coverage of the new
in-flight states (downloaded/processing/processed)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.background import sweep_expired_leases
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "max_inflight_per_worker", 0)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed(
    granule_id: str = "g1",
    state: str = GranuleState.DOWNLOADING.value,
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


def _post(client, gid: str, state: str, worker_id: str = "w1"):
    return client.post(
        "/api/workers/state",
        json={"granule_id": gid, "worker_id": worker_id, "state": state},
    )


# ─── happy path ────────────────────────────────────────────────────────────


async def test_full_forward_chain(client):
    await _seed()
    for nxt in (
        GranuleState.DOWNLOADED.value,
        GranuleState.PROCESSING.value,
        GranuleState.PROCESSED.value,
    ):
        r = _post(client, "g1", nxt)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == nxt
        assert await _state("g1") == nxt


# ─── ownership + transition guards ─────────────────────────────────────────


async def test_rejects_when_worker_does_not_hold_lease(client):
    await _seed(leased_by="w-other")
    r = _post(client, "g1", GranuleState.DOWNLOADED.value, worker_id="w1")
    assert r.status_code == 409
    assert await _state("g1") == GranuleState.DOWNLOADING.value


async def test_rejects_skipping_intermediate(client):
    """From DOWNLOADING you cannot jump straight to PROCESSING."""
    await _seed()
    r = _post(client, "g1", GranuleState.PROCESSING.value)
    assert r.status_code == 409
    assert await _state("g1") == GranuleState.DOWNLOADING.value


async def test_rejects_backwards_transition(client):
    await _seed(state=GranuleState.PROCESSING.value)
    r = _post(client, "g1", GranuleState.DOWNLOADED.value)
    assert r.status_code == 409


async def test_rejects_unknown_granule(client):
    await _seed()
    r = _post(client, "ghost", GranuleState.DOWNLOADED.value)
    assert r.status_code == 404


async def test_rejects_non_reportable_state(client):
    """downloading / uploaded / pending are owned by lease/upload/etc., not
    by the worker state endpoint."""
    await _seed()
    for forbidden in (
        GranuleState.DOWNLOADING.value,
        GranuleState.UPLOADED.value,
        GranuleState.PENDING.value,
        GranuleState.FAILED.value,
    ):
        r = _post(client, "g1", forbidden)
        assert r.status_code == 422, f"{forbidden} should be rejected"


# ─── lease-sweeper coverage of the new in-flight states ────────────────────


@pytest.mark.parametrize(
    "state",
    [
        GranuleState.DOWNLOADING.value,
        GranuleState.DOWNLOADED.value,
        GranuleState.PROCESSING.value,
        GranuleState.PROCESSED.value,
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
