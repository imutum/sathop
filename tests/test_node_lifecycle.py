"""Worker / receiver enable + forget endpoints — runtime kill-switch and
permanent removal, with safety guards so an operator can't drop a busy node."""

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


async def _add_worker(worker_id: str = "w1", enabled: bool = True) -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=4, enabled=enabled))
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
                inputs_json="[]",
                leased_by=worker_id,
            )
        )
        await s.commit()


async def _worker_enabled(worker_id: str) -> bool:
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, worker_id)
        assert w is not None
        return w.enabled


# ─── worker enable/disable ──────────────────────────────────────────────────


async def test_worker_disable_then_enable_round_trip(client):
    await _add_worker()
    r = client.put("/api/workers/w1/enabled", json={"enabled": False})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "enabled": False}
    assert (await _worker_enabled("w1")) is False

    r = client.put("/api/workers/w1/enabled", json={"enabled": True})
    assert r.status_code == 200
    assert (await _worker_enabled("w1")) is True


async def test_worker_disabled_lease_returns_403(client):
    await _add_worker(enabled=False)
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 4})
    assert r.status_code == 403


async def test_worker_enable_404_when_unknown(client):
    r = client.put("/api/workers/ghost/enabled", json={"enabled": False})
    assert r.status_code == 404


# ─── worker self-paused state surfaces in /api/workers ─────────────────────


async def test_worker_paused_round_trip_via_heartbeat(client):
    """A heartbeat with paused=True should land on the workers row and ride the
    list endpoint, so the dashboard can flag a self-paused-but-online worker."""
    await _add_worker()
    # Default after registration: paused must be falsy (the row may have NULL
    # right after the additive ALTER TABLE — both forms must read as not-paused).
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

    # And it clears again on the next heartbeat once disk drops below resume
    # threshold (the worker stops sending paused=True).
    client.post("/api/workers/heartbeat", json={"worker_id": "w1", "paused": False})
    [row2] = client.get("/api/workers").json()
    assert row2["paused"] is False


# ─── worker forget (delete) ─────────────────────────────────────────────────


async def test_worker_forget_refuses_when_enabled(client):
    await _add_worker()
    r = client.delete("/api/workers/w1")
    assert r.status_code == 409
    assert "disable it first" in r.json()["detail"]
    # row stays
    assert (await _worker_enabled("w1")) is True


async def test_worker_forget_refuses_with_inflight(client):
    await _add_worker(enabled=False)
    await _seed_granule("w1", state=GranuleState.PROCESSING.value, granule_id="b:still-here")
    r = client.delete("/api/workers/w1")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "wait for drain" in detail
    # Operator needs to know which granules — the IDs surface in the error.
    assert "b:still-here" in detail


async def test_worker_forget_succeeds_when_disabled_and_idle(client):
    await _add_worker(enabled=False)
    r = client.delete("/api/workers/w1")
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        assert (await s.get(Worker, "w1")) is None


async def test_worker_forget_404_when_unknown(client):
    r = client.delete("/api/workers/ghost")
    assert r.status_code == 404


# ─── receiver enable/disable + forget ───────────────────────────────────────


async def test_receiver_disable_blocks_pull(client):
    await _add_receiver(enabled=False)
    r = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10})
    assert r.status_code == 403


async def test_receiver_enable_round_trip_and_forget(client):
    await _add_receiver()
    # delete refused while enabled
    assert client.delete("/api/receivers/r1").status_code == 409
    # disable
    assert client.put("/api/receivers/r1/enabled", json={"enabled": False}).status_code == 200
    # delete now allowed
    r = client.delete("/api/receivers/r1")
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        assert (await s.get(Receiver, "r1")) is None


# ─── operator-set pause via heartbeat reply ────────────────────────────────


async def test_worker_pause_endpoint_propagates_via_heartbeat(client):
    """PUT /pause sets the persistent flag; the next heartbeat reply
    forwards it, and /api/workers exposes it for the UI."""
    await _add_worker()
    r = client.put("/api/workers/w1/pause", json={"paused": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "pause_requested": True}

    # /api/workers reflects the flag so the frontend renders the pause Badge
    [row] = client.get("/api/workers").json()
    assert row["pause_requested"] is True

    # Worker-side observes pause_requested=True on the next heartbeat reply.
    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.status_code == 200
    body = r.json()
    assert body["pause_requested"] is True
    # Persistent: pause_requested stays True across heartbeats until cleared.
    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.json()["pause_requested"] is True

    # Resume → flag flips, heartbeat reply mirrors it.
    assert client.put("/api/workers/w1/pause", json={"paused": False}).status_code == 200
    r = client.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.json()["pause_requested"] is False


async def test_worker_pause_404_when_unknown(client):
    r = client.put("/api/workers/ghost/pause", json={"paused": True})
    assert r.status_code == 404


# ─── force-revoke worker leases ────────────────────────────────────────────


async def test_worker_revoke_all_resets_leases_to_pending(client):
    """Sets up a worker holding two granules (one DOWNLOADING, one PROCESSED)
    and confirms revoke-all flips both back to PENDING with retry_count +1."""
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
    """A granule that already moved to UPLOADED (worker handed off to receiver)
    must NOT be reverted — that would re-process work already shipped."""
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

    # First heartbeat after the click sees the flag.
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["gc_requested"] is True
    # Second heartbeat: flag was consumed (one-shot), no longer set.
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["gc_requested"] is False


async def test_worker_gc_404_when_unknown(client):
    assert client.post("/api/workers/ghost/gc").status_code == 404
