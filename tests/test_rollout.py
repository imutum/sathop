"""L2 staged fleet rollout: the leader advances one rollout canary→batch→fleet,
gated purely by version-confirmed liveness (a wave completes when its frozen
cohort all report version==target; a wave that times out HALTs — never an
auto-rollback). Drives the leader by calling advance_rollout() directly and
simulates a worker confirming by setting Worker.version=target.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop import __version__
from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api import admin
from sathop.orchestrator.background import advance_rollout
from sathop.orchestrator.db import Rollout, Worker, utcnow
from sathop.orchestrator.main import app

TARGET = __version__  # equal to orch version → passes the orch-before-worker guard


@pytest.fixture
async def client(tmp_path, patch_settings, monkeypatch):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()

    async def _ok(version: str) -> None:  # the release is "downloadable" — no network
        return None

    monkeypatch.setattr(admin, "head_release_asset", _ok)
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_workers(n: int, version: str = "0.0.1") -> None:
    async with orch_db._session_maker() as s:
        for i in range(n):
            s.add(Worker(worker_id=f"w{i:02d}", version=version, capacity=4))
        await s.commit()


async def _confirm(worker_ids: list[str]) -> None:
    """Simulate the workers rebooting onto TARGET (the only signal the gate reads)."""
    async with orch_db._session_maker() as s:
        for wid in worker_ids:
            (await s.get(Worker, wid)).version = TARGET
        await s.commit()


async def _expire_wave_deadline() -> None:
    async with orch_db._session_maker() as s:
        r = await s.scalar(select(Rollout).order_by(Rollout.id.desc()))
        r.wave_deadline_at = utcnow() - timedelta(seconds=1)
        await s.commit()


def _status(client: TestClient) -> dict:
    return client.get("/api/admin/rollout").json()


# ─── start guards ────────────────────────────────────────────────────────────


async def test_start_creates_pending_rollout(client):
    await _seed_workers(2)
    body = client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1}).json()
    assert body["active"] and body["phase"] == "pending"
    assert body["target_version"] == TARGET


async def test_start_refuses_version_newer_than_orchestrator(client):
    await _seed_workers(1)
    r = client.post("/api/admin/rollout", json={"target_version": "999.0.0"})
    assert r.status_code == 409  # orch-before-worker


async def test_start_rejects_garbage_version(client):
    r = client.post("/api/admin/rollout", json={"target_version": "nope"})
    assert r.status_code == 422


async def test_start_refuses_a_second_active_rollout(client):
    await _seed_workers(2)
    assert client.post("/api/admin/rollout", json={"target_version": TARGET}).status_code == 200
    assert client.post("/api/admin/rollout", json={"target_version": TARGET}).status_code == 409


async def test_start_resolves_a_channel(client, monkeypatch):
    await _seed_workers(1)

    async def fake(channel="stable"):
        return {"tag": f"v{TARGET}", "html_url": "https://example"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fake)
    body = client.post("/api/admin/rollout", json={"channel": "edge"}).json()
    assert body["channel"] == "edge"
    assert body["target_version"] == TARGET


# ─── leader wave advancement ───────────────────────────────────────────────────


async def test_full_rollout_canary_batch_fleet(client):
    await _seed_workers(6)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1, "batch_pct": 0.5})

    # pending → canary: exactly one worker stamped.
    await advance_rollout()
    st = _status(client)
    assert st["wave"] == "canary" and st["members"]["pending"] == 1
    canary = st["pending_ids"]
    assert len(canary) == 1
    async with orch_db._session_maker() as s:
        assert (await s.get(Worker, canary[0])).update_to_version == TARGET  # the update one-shot fired

    # canary confirms → batch wave (ceil(5 * 0.5) = 3).
    await _confirm(canary)
    await advance_rollout()
    st = _status(client)
    assert st["wave"] == "batch" and st["members"]["pending"] == 3

    # batch confirms → fleet wave (remaining 2).
    await _confirm(st["pending_ids"])
    await advance_rollout()
    st = _status(client)
    assert st["wave"] == "fleet" and st["members"]["pending"] == 2

    # fleet confirms → done.
    await _confirm(st["pending_ids"])
    await advance_rollout()
    st = _status(client)
    assert st["phase"] == "done" and not st["active"]


async def test_silence_does_not_advance(client):
    """A wave never advances on silence — only version-confirmed liveness moves it."""
    await _seed_workers(3)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1})
    await advance_rollout()  # → canary
    await advance_rollout()  # nobody confirmed, deadline not passed → no change
    st = _status(client)
    assert st["phase"] == "running" and st["wave"] == "canary" and st["members"]["pending"] == 1


async def test_halt_on_timeout(client):
    """A crash-looping / silent worker stays on the old version → the wave times
    out and HALTs (hard fact #2), it never falsely advances."""
    await _seed_workers(2)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1})
    await advance_rollout()  # → canary, one stamped
    laggard = _status(client)["pending_ids"][0]
    await _expire_wave_deadline()
    await advance_rollout()  # deadline passed, unconfirmed → halt
    st = _status(client)
    assert st["phase"] == "halted" and laggard in st["halt_reason"]


async def test_resume_after_halt(client):
    await _seed_workers(2)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1})
    await advance_rollout()
    canary = _status(client)["pending_ids"]
    await _expire_wave_deadline()
    await advance_rollout()
    assert _status(client)["phase"] == "halted"

    # operator fixes the laggard, then resumes → running again, leader proceeds.
    await _confirm(canary)
    assert client.post("/api/admin/rollout/resume").json()["phase"] == "running"
    await advance_rollout()  # canary now confirmed → next wave proceeds (batch, the 1 remaining)
    st = _status(client)
    assert st["phase"] == "running" and st["wave"] == "batch"


async def test_abort_stops_the_rollout(client):
    await _seed_workers(2)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 1})
    await advance_rollout()
    assert client.post("/api/admin/rollout/abort").json()["phase"] == "aborted"
    # no active rollout → the leader is a no-op
    assert await advance_rollout() is False
    assert _status(client)["active"] is False


async def test_paused_member_is_excused_not_blocking(client):
    """An operator-paused member is dropped from the wave denominator so it can't
    block the wave forever."""
    await _seed_workers(2)
    client.post("/api/admin/rollout", json={"target_version": TARGET, "canary_count": 2})
    await advance_rollout()  # canary = both workers
    assert _status(client)["members"]["pending"] == 2
    # confirm one, pause the other → wave should complete (excused), not stall.
    st = _status(client)
    await _confirm([st["pending_ids"][0]])
    async with orch_db._session_maker() as s:
        (await s.get(Worker, st["pending_ids"][1])).operator_paused = True
        await s.commit()
    await advance_rollout()
    assert _status(client)["phase"] == "done"
