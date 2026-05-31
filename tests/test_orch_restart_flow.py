"""Orchestrator self-restart / upgrade flow: graceful-shutdown signalling.

Covers the fix for "click 重启 → process hangs in graceful shutdown": the
long-lived /api/stream connection must observe a shutdown signal and close
promptly. Also covers the version-upgrade endpoint that writes `.pending-version`
for the entrypoint to consume (one self-contained bundle per version — backend +
matching frontend — so they can't drift)."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


# ─── shutdown signal ─────────────────────────────────────────────────────────


def test_request_shutdown_flag():
    from sathop.orchestrator import pubsub

    pubsub.reset_shutdown()
    assert pubsub.is_shutting_down() is False
    pubsub.request_shutdown()
    assert pubsub.is_shutting_down() is True
    pubsub.reset_shutdown()
    assert pubsub.is_shutting_down() is False


async def test_sse_stream_closes_when_shutdown_requested():
    """A stream that checks in after the flag is set exits at the loop top."""
    from sathop.orchestrator import pubsub
    from sathop.orchestrator.api.stream import stream

    pubsub.reset_shutdown()
    try:
        resp = await stream()
        it = resp.body_iterator
        assert b"ready" in await it.__anext__()

        pubsub.request_shutdown()
        assert b"shutdown" in await it.__anext__()
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()
    finally:
        pubsub.reset_shutdown()


async def test_sse_parked_stream_wakes_on_shutdown():
    """A stream already parked in q.get() is woken by the nudge and closes,
    rather than hanging until the heartbeat timeout."""
    from sathop.orchestrator import pubsub
    from sathop.orchestrator.api.stream import stream

    pubsub.reset_shutdown()
    try:
        resp = await stream()
        it = resp.body_iterator
        assert b"ready" in await it.__anext__()

        nxt = asyncio.ensure_future(it.__anext__())
        await asyncio.sleep(0.05)  # let it park in q.get()
        assert not nxt.done()

        pubsub.request_shutdown()
        frame = await asyncio.wait_for(nxt, timeout=2)
        assert b"shutdown" in frame
    finally:
        pubsub.reset_shutdown()


# ─── health exposes web_sha ──────────────────────────────────────────────────


def test_health_includes_web_sha(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "web_sha" in body  # str (dist deployed) or None


# ─── version upgrade endpoint ────────────────────────────────────────────────


def test_upgrade_rejects_bad_version(client):
    """A non-version string is refused (422) before anything is written."""
    r = client.post("/api/admin/upgrade", json={"version": "not-a-version"})
    assert r.status_code == 422


def test_upgrade_writes_pending_and_triggers_shutdown(tmp_path, monkeypatch, client):
    """A valid, downloadable version writes .pending-version and asks for restart.

    HEAD is mocked OK, the repo-root is redirected to a tmp dir, and the SIGTERM
    scheduling is stubbed so the test process survives."""
    from sathop.orchestrator import pubsub
    from sathop.orchestrator.api import admin

    monkeypatch.setattr("sathop.shared.release.repo_root", lambda: tmp_path)

    real_client = httpx.AsyncClient  # capture before patching to avoid recursion

    def ok_client(*_a, **_k):
        return real_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(200)),
            follow_redirects=True,
        )

    monkeypatch.setattr(admin.httpx, "AsyncClient", ok_client)

    triggered = {"v": False}
    monkeypatch.setattr(admin, "_trigger_shutdown", lambda: triggered.__setitem__("v", True))
    pubsub.reset_shutdown()

    r = client.post("/api/admin/upgrade", json={"version": "v9.9.9"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "9.9.9"}
    assert (tmp_path / ".pending-version").read_text() == "9.9.9"
    assert triggered["v"] is True


# ─── shutdown signal target: which PID restarts the CONTAINER ────────────────
# Multi-process uvicorn: a worker SIGTERMing itself only gets respawned by the
# master — the container never restarts and .pending-version is never consumed.
# The signal must hit the master (the worker's parent); single-process keeps self.


def test_shutdown_target_single_process_signals_self(monkeypatch, patch_settings):
    from sathop.orchestrator.api import admin

    patch_settings(orch_workers=1)
    monkeypatch.setattr(admin, "is_postgres", lambda: True)
    assert admin._shutdown_target_pid() == os.getpid()


def test_shutdown_target_multiprocess_signals_master(monkeypatch, patch_settings):
    from sathop.orchestrator.api import admin

    patch_settings(orch_workers=4)
    monkeypatch.setattr(admin, "is_postgres", lambda: True)
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    assert admin._shutdown_target_pid() == 4242


def test_shutdown_target_multiprocess_on_sqlite_signals_self(monkeypatch, patch_settings):
    # workers>1 but SQLite → run() forces a single process → self is correct.
    from sathop.orchestrator.api import admin

    patch_settings(orch_workers=4)
    monkeypatch.setattr(admin, "is_postgres", lambda: False)
    assert admin._shutdown_target_pid() == os.getpid()


def test_shutdown_target_orphaned_master_falls_back_to_self(monkeypatch, patch_settings):
    # Parent already reaped → reparented to PID 1 (tini); must NOT SIGTERM it
    # (that stops the container), fall back to self.
    from sathop.orchestrator.api import admin

    patch_settings(orch_workers=4)
    monkeypatch.setattr(admin, "is_postgres", lambda: True)
    monkeypatch.setattr(os, "getppid", lambda: 1)
    assert admin._shutdown_target_pid() == os.getpid()


# ─── .pending-version stamp lands where the entrypoint reads it ──────────────
# Under the A/B-slots editable layout repo_root() is the slot dir; the stamp must
# climb to the slots parent (REPO_DIR) or the upgrade silently no-ops. These do
# NOT monkeypatch the resolver away — they reproduce the slot layout.


def test_stamp_dir_climbs_out_of_slot(monkeypatch, tmp_path):
    from sathop.shared import release

    monkeypatch.delenv("SATHOP_REPO_DIR", raising=False)
    slot = tmp_path / "slots" / "1.0.2"
    slot.mkdir(parents=True)
    monkeypatch.setattr(release, "repo_root", lambda: slot)
    assert release.stamp_dir() == tmp_path
    p = release.write_pending_version("1.0.2")
    assert p == tmp_path / ".pending-version"  # REPO_DIR, not the slot
    assert p.read_text() == "1.0.2"


def test_stamp_dir_env_override_wins(monkeypatch, tmp_path):
    from sathop.shared import release

    monkeypatch.setenv("SATHOP_REPO_DIR", str(tmp_path))
    monkeypatch.setattr(release, "repo_root", lambda: tmp_path / "slots" / "x")
    assert release.stamp_dir() == tmp_path


def test_stamp_dir_dev_checkout_uses_repo_root(monkeypatch, tmp_path):
    from sathop.shared import release

    monkeypatch.delenv("SATHOP_REPO_DIR", raising=False)
    monkeypatch.setattr(release, "repo_root", lambda: tmp_path)  # not under slots/
    assert release.stamp_dir() == tmp_path


def test_upgrade_502_when_asset_missing(tmp_path, monkeypatch, client):
    """A version whose release asset 404s fails fast (no pending write, no
    restart) — better than crash-looping the container post-restart."""
    from sathop.orchestrator.api import admin

    monkeypatch.setattr("sathop.shared.release.repo_root", lambda: tmp_path)

    real_client = httpx.AsyncClient  # capture before patching to avoid recursion

    def missing_client(*_a, **_k):
        return real_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(404)),
            follow_redirects=True,
        )

    monkeypatch.setattr(admin.httpx, "AsyncClient", missing_client)
    triggered = {"v": False}
    monkeypatch.setattr(admin, "_trigger_shutdown", lambda: triggered.__setitem__("v", True))

    r = client.post("/api/admin/upgrade", json={"version": "0.0.1"})
    assert r.status_code == 502
    assert not (tmp_path / ".pending-version").exists()
    assert triggered["v"] is False
