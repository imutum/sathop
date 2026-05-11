"""Operator-triggered restart, delivered via heartbeat reply.

POST /api/{workers,receivers}/{id}/restart sets a one-shot flag the next
heartbeat consumes — the response carries `restart_requested=True` exactly
once, the orchestrator clears the flag, and a follow-up heartbeat reads
False. Two containers sharing the same ID would race for the signal; the
first one to heartbeat wins, which is the same "first to ack wins" pattern
we already use for lease reclamation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Receiver, Worker
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
    )
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


# ─── worker ────────────────────────────────────────────────────────────────


async def _seed_worker() -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="0.3.9", capacity=4))
        await s.commit()


def _worker_heartbeat() -> dict:
    return {"worker_id": "w1", "version": "0.3.9"}


def test_worker_restart_endpoint_404_for_unknown(client):
    r = client.post("/api/workers/ghost/restart")
    assert r.status_code == 404


async def test_worker_restart_signal_round_trip(client):
    """Set flag → heartbeat returns True once → orchestrator clears → next
    heartbeat returns False. The whole point is one-shot delivery: a second
    heartbeat (post-restart, from the freshly-spawned container) must NOT see
    the flag again, otherwise we'd loop the worker forever."""
    await _seed_worker()

    # No restart pending yet.
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.status_code == 200
    assert r.json()["restart_requested"] is False

    # Operator clicks restart.
    r = client.post("/api/workers/w1/restart")
    assert r.status_code == 200

    # First heartbeat after the click consumes it.
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["restart_requested"] is True

    # And it's gone from the row.
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w.restart_requested_at is None

    # Subsequent heartbeats see False — no looping.
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["restart_requested"] is False


async def test_worker_restart_idempotent(client):
    """Re-clicking before the heartbeat consumes it just refreshes the ts —
    still one delivery. Prevents 'I clicked twice; will it restart twice?'"""
    await _seed_worker()
    client.post("/api/workers/w1/restart")
    client.post("/api/workers/w1/restart")  # second click
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["restart_requested"] is True
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["restart_requested"] is False


# ─── receiver ──────────────────────────────────────────────────────────────


async def _seed_receiver() -> None:
    async with orch_db._session_maker() as s:
        s.add(Receiver(receiver_id="r1", version="0.3.9", platform="linux"))
        await s.commit()


def _receiver_heartbeat() -> dict:
    return {"receiver_id": "r1", "version": "0.3.9"}


def test_receiver_restart_endpoint_404_for_unknown(client):
    r = client.post("/api/receivers/ghost/restart")
    assert r.status_code == 404


async def test_receiver_restart_signal_round_trip(client):
    await _seed_receiver()

    r = client.post("/api/receivers/heartbeat", json=_receiver_heartbeat())
    assert r.json()["restart_requested"] is False

    client.post("/api/receivers/r1/restart")

    r = client.post("/api/receivers/heartbeat", json=_receiver_heartbeat())
    assert r.json()["restart_requested"] is True

    async with orch_db._session_maker() as s:
        rcv = await s.get(Receiver, "r1")
        assert rcv.restart_requested_at is None

    r = client.post("/api/receivers/heartbeat", json=_receiver_heartbeat())
    assert r.json()["restart_requested"] is False
