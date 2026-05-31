"""Batch-level pause/resume: a paused batch's PENDING granules are not leased
(in-flight drains, no state change); resume makes them claimable again. Pause is
a batch attribute, orthogonal to the granule state machine — the batch-level
counterpart to the atomic, per-granule cancel."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.admin_readmodels import admin_overview
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="", max_inflight_per_worker=0)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed(batch_id: str, gids: list[str], state=GranuleState.PENDING.value) -> None:
    async with orch_db._session_maker() as s:
        if await s.get(Batch, batch_id) is None:
            s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:/x"))
        for g in gids:
            s.add(Granule(granule_id=g, batch_id=batch_id, state=state, inputs=[]))
        await s.commit()


async def _register_worker(wid: str = "w1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=wid, version="", capacity=10, public_url=None))
        await s.commit()


def _lease(client, n: int, wid: str = "w1") -> list[dict]:
    r = client.post("/api/workers/lease", json={"worker_id": wid, "capacity": n})
    assert r.status_code == 200
    return r.json()["items"]


async def test_pause_blocks_lease_then_resume_unblocks(client):
    await _register_worker()
    await _seed("b1", ["g1", "g2"])

    assert client.post("/api/batches/b1/pause").json() == {"ok": True, "status": "paused"}
    assert _lease(client, 5) == []  # paused → nothing claimable

    assert client.post("/api/batches/b1/resume").json() == {"ok": True, "status": "running"}
    leased = _lease(client, 5)
    assert {it["granule_id"] for it in leased} == {"g1", "g2"}


async def test_pause_is_per_batch(client):
    await _register_worker()
    await _seed("b1", ["g1"])
    await _seed("b2", ["g2"])
    client.post("/api/batches/b1/pause")

    leased = _lease(client, 5)
    assert {it["granule_id"] for it in leased} == {"g2"}  # only the un-paused batch


async def test_pause_does_not_touch_in_flight_granules(client):
    # A granule already leased (QUEUED) keeps draining; pause only gates PENDING.
    await _seed("b1", ["g1"], state=GranuleState.QUEUED.value)
    client.post("/api/batches/b1/pause")
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.QUEUED.value  # unchanged by pause


async def test_pause_resume_idempotent_and_404(client):
    await _seed("b1", ["g1"])
    assert client.post("/api/batches/b1/pause").json()["status"] == "paused"
    assert client.post("/api/batches/b1/pause").json()["status"] == "paused"  # idempotent
    assert client.post("/api/batches/b1/resume").json()["status"] == "running"
    assert client.post("/api/batches/b1/resume").json()["status"] == "running"
    assert client.post("/api/batches/nope/pause").status_code == 404


async def test_paused_status_surfaces_in_summary(client):
    await _seed("b1", ["g1"])
    client.post("/api/batches/b1/pause")
    r = client.get("/api/batches/b1")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"


async def test_retry_failed_on_paused_batch_stays_gated(client):
    # Retrying failed granules re-pends them, but a paused batch still won't lease.
    await _register_worker()
    await _seed("b1", ["g1"], state=GranuleState.FAILED.value)
    client.post("/api/batches/b1/pause")
    assert client.post("/api/batches/b1/retry-failed").json()["reset"] == 1
    assert _lease(client, 5) == []  # re-pended but held by the pause
    client.post("/api/batches/b1/resume")
    assert {it["granule_id"] for it in _lease(client, 5)} == {"g1"}


async def test_paused_batch_pending_not_flagged_stuck(client):
    # A paused batch's held PENDING granule is intentionally idle, not "stuck" —
    # it must not trip overview/metrics/reconcile alerts (regression for the
    # stuck-detection exclusion).
    old = utcnow() - timedelta(hours=999)
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="local:/x"))
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b1",
                state=GranuleState.PENDING.value,
                inputs=[],
                updated_at=old,
            )
        )
        await s.commit()

    now = utcnow()
    async with orch_db._session_maker() as s:
        running = await admin_overview(s, now=now)
        assert running["stuck_by_state"].get("pending", 0) == 1  # stuck while running

    client.post("/api/batches/b1/pause")
    async with orch_db._session_maker() as s:
        paused = await admin_overview(s, now=now)
        assert paused["stuck_by_state"].get("pending", 0) == 0  # not stuck once paused
