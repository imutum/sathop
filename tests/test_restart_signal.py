"""Operator-triggered update (worker) / restart (receiver), delivered via heartbeat reply.

Worker: POST /api/workers/{id}/update → heartbeat returns update_requested=True once.
Receiver: POST /api/receivers/{id}/restart → heartbeat returns restart_requested=True once."""

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


def test_worker_update_endpoint_404_for_unknown(client):
    r = client.post("/api/workers/ghost/update")
    assert r.status_code == 404


async def test_worker_update_signal_round_trip(client):
    await _seed_worker()

    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.status_code == 200
    assert r.json()["update_requested"] is False

    r = client.post("/api/workers/w1/update")
    assert r.status_code == 200

    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["update_requested"] is True

    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w.update_requested_at is None

    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["update_requested"] is False


async def test_worker_update_idempotent(client):
    await _seed_worker()
    client.post("/api/workers/w1/update")
    client.post("/api/workers/w1/update")
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["update_requested"] is True
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat())
    assert r.json()["update_requested"] is False


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
