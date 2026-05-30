"""Orchestrator self-restart / upgrade flow: graceful-shutdown signalling.

Covers the fix for "click 重启 → process hangs in graceful shutdown": the
long-lived /api/stream connection must observe a shutdown signal and close
promptly. Also covers the version-upgrade endpoint that writes `.pending-version`
for the entrypoint to consume (one self-contained bundle per version — backend +
matching frontend — so they can't drift)."""

from __future__ import annotations

import asyncio

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
