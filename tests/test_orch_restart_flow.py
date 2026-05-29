"""Orchestrator self-restart flow: graceful-shutdown signalling + version-gated
frontend sync.

These cover the fix for "click 更新并重启 → process hangs in graceful shutdown":
the long-lived /api/stream connection must observe a shutdown signal and close
promptly, and the dist must re-sync to the running version on boot."""

from __future__ import annotations

import asyncio
import hashlib
import io
import tarfile

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


# ─── frontend sync ───────────────────────────────────────────────────────────


def _dist_targz(html: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("dist/index.html")
        info.size = len(html)
        tf.addfile(info, io.BytesIO(html))
    return buf.getvalue()


async def test_ensure_frontend_version_gated_no_network(tmp_path, monkeypatch):
    """Matching .version short-circuits before any HTTP — restarts at the same
    version cost nothing."""
    from sathop.orchestrator import frontend_sync as fs

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ui")
    (dist / ".version").write_text("0.6.10")
    monkeypatch.setattr(fs, "_DIST_DIR", dist)

    # No httpx patch: if it tried the network the MockTransport-less client would
    # fail. It must not get that far.
    res = await fs.ensure_frontend("0.6.10")
    assert res["action"] == "already_up_to_date"


async def test_ensure_frontend_downloads_on_version_mismatch(tmp_path, monkeypatch):
    from sathop.orchestrator import frontend_sync as fs

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("old")
    (dist / ".version").write_text("0.6.9")
    monkeypatch.setattr(fs, "_DIST_DIR", dist)

    payload = _dist_targz(b"<html>v0.6.10</html>")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    real_client = httpx.AsyncClient

    def factory(*_a, **_k):
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(fs.httpx, "AsyncClient", factory)

    res = await fs.ensure_frontend("0.6.10")
    assert res["action"] == "downloaded"
    assert (dist / "index.html").read_text() == "<html>v0.6.10</html>"
    assert (dist / ".version").read_text() == "0.6.10"
    assert (dist / ".sha256").read_text() == hashlib.sha256(payload).hexdigest()

    # Same bytes again (force bypasses the version gate) → sha matches, no swap.
    res2 = await fs.ensure_frontend("0.6.10", force=True)
    assert res2["action"] == "already_up_to_date"
