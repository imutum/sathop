"""Heartbeat-driven version flap detection.

Two containers sharing the same worker_id (or receiver_id) cause subtle
production bugs — concurrent .part writes, mixed TLS trust modes, register
overwriting each other. The orchestrator can't actively kick one out (no
process-instance fencing yet) but it can SURFACE the symptom: a stable
node ID whose `version` field flips between heartbeats almost certainly
means an orphan container is alive and competing.

Quiet path: same version every heartbeat → no log noise.
Noisy path: version changes between heartbeats → warn-level event so the
operator sees it in the events feed and the per-node UI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store
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


def _events_matching(needle: str) -> list[str]:
    rows = event_store.query(limit=10000)
    # query returns newest-first; reverse to get chronological order
    rows.reverse()
    return [e["message"] for e in rows if needle in (e["message"] or "")]


# ─── worker ────────────────────────────────────────────────────────────────


async def _seed_worker(version: str = "0.3.7") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version=version, capacity=4))
        await s.commit()


def _worker_heartbeat(version: str) -> dict:
    return {"worker_id": "w1", "version": version}


async def test_worker_heartbeat_updates_version_silently_when_unchanged(client):
    await _seed_worker("0.3.7")
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat("0.3.7"))
    assert r.status_code == 200
    assert _events_matching("version changed") == []


async def test_worker_heartbeat_logs_warn_on_version_flap(client):
    """A second container heartbeating with a different version under the same
    worker_id is the orphan signal we want to make visible."""
    await _seed_worker("0.3.7")
    client.post("/api/workers/heartbeat", json=_worker_heartbeat("0.3.3"))
    flaps = _events_matching("version changed")
    assert len(flaps) == 1
    assert "'0.3.7' → '0.3.3'" in flaps[0]
    # And the DB now reflects the latest reporter (next reporter will also flag
    # if it differs — flapping is the actionable signal).
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w.version == "0.3.3"


async def test_worker_heartbeat_empty_version_is_ignored(client):
    """Pre-0.3.8 worker clients don't send `version`; treat empty as 'no info'
    rather than as a flap to a blank version. Otherwise rolling redeploys
    from old → new clients would fire a false-positive on every heartbeat."""
    await _seed_worker("0.3.7")
    r = client.post("/api/workers/heartbeat", json=_worker_heartbeat(""))
    assert r.status_code == 200
    assert _events_matching("version changed") == []
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w.version == "0.3.7"  # untouched


# ─── receiver ──────────────────────────────────────────────────────────────


async def _seed_receiver(version: str = "0.3.7") -> None:
    async with orch_db._session_maker() as s:
        s.add(Receiver(receiver_id="r1", version=version, platform="linux"))
        await s.commit()


def _receiver_heartbeat(version: str) -> dict:
    return {"receiver_id": "r1", "version": version}


async def test_receiver_heartbeat_logs_warn_on_version_flap(client):
    await _seed_receiver("0.3.7")
    client.post("/api/receivers/heartbeat", json=_receiver_heartbeat("0.3.3"))
    flaps = _events_matching("version changed")
    assert len(flaps) == 1
    assert "'0.3.7' → '0.3.3'" in flaps[0]


async def test_receiver_heartbeat_empty_version_is_ignored(client):
    await _seed_receiver("0.3.7")
    r = client.post("/api/receivers/heartbeat", json=_receiver_heartbeat(""))
    assert r.status_code == 200
    assert _events_matching("version changed") == []
