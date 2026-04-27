"""Receiver._fetch_one: verify + ack flow covering happy, sha-mismatch, and
pull-error paths. Plus config.load() env-var handling."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from sathop.receiver.main import Receiver, Settings, load
from sathop.shared.protocol import AckReport, PullItem


def _serve(payload: bytes):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def _make_receiver(tmp_path: Path) -> tuple[Receiver, list[AckReport]]:
    """Build a Receiver with a stub OrchestratorClient that just captures acks."""
    settings = Settings(
        receiver_id="r1",
        orchestrator_url="http://orch.test",
        token="t",
        storage_dir=tmp_path / "archive",
        poll_interval=1,
        concurrent_pulls=2,
        platform="linux",
    )
    r = Receiver(settings)
    captured: list[AckReport] = []

    class StubClient:
        async def ack(self, req: AckReport) -> None:
            captured.append(req)

        async def aclose(self) -> None:
            pass

    r.client = StubClient()  # type: ignore[assignment]
    return r, captured


async def test_fetch_one_happy_path(tmp_path):
    payload = b"hello-world"
    srv, port = _serve(payload)
    try:
        r, acks = _make_receiver(tmp_path)
        it = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/out.bin",
            presigned_url=f"http://127.0.0.1:{port}/",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), it)

        assert (tmp_path / "archive" / "b1" / "g1" / "out.bin").read_bytes() == payload
        assert len(acks) == 1
        assert acks[0].success is True
        assert acks[0].object_id == 1
        assert acks[0].error is None
    finally:
        srv.shutdown()


async def test_fetch_one_sha_mismatch_deletes_and_acks_false(tmp_path):
    payload = b"actual-bytes"
    srv, port = _serve(payload)
    try:
        r, acks = _make_receiver(tmp_path)
        it = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=2,
            object_key="b1/g1/corrupt.bin",
            presigned_url=f"http://127.0.0.1:{port}/",
            sha256="0" * 64,  # wrong
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), it)

        # Corrupt file was unlinked
        assert not (tmp_path / "archive" / "b1" / "g1" / "corrupt.bin").exists()
        assert len(acks) == 1
        assert acks[0].success is False
        assert acks[0].error and "mismatch" in acks[0].error
    finally:
        srv.shutdown()


async def test_fetch_one_pull_error_acks_false_with_exception_text(tmp_path):
    r, acks = _make_receiver(tmp_path)
    it = PullItem(
        granule_id="g1",
        batch_id="b1",
        object_id=3,
        object_key="b1/g1/x.bin",
        presigned_url="http://127.0.0.1:1/",  # port 1: reserved, connect will fail
        sha256="abc",
        size=5,
    )
    await r._fetch_one(asyncio.Semaphore(1), it)

    assert len(acks) == 1
    assert acks[0].success is False
    assert acks[0].sha256 == ""
    assert acks[0].error


# ─── config.load() ────────────────────────────────────────────────────────


def test_config_load_reads_required_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "recv-home")
    monkeypatch.setenv("SATHOP_ORCH_URL", "https://orch.example.com/")
    monkeypatch.setenv("SATHOP_TOKEN", "t0k3n")
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path / "arch"))
    monkeypatch.delenv("SATHOP_POLL_INTERVAL", raising=False)
    monkeypatch.delenv("SATHOP_CONCURRENT_PULLS", raising=False)

    s = load()

    assert s.receiver_id == "recv-home"
    # trailing slash is stripped
    assert s.orchestrator_url == "https://orch.example.com"
    assert s.token == "t0k3n"
    assert s.storage_dir == tmp_path / "arch"
    # defaults
    assert s.poll_interval == 10
    assert s.concurrent_pulls == 4
    assert s.platform == ("windows" if sys.platform == "win32" else "linux")


def test_config_load_respects_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "r")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://x")
    monkeypatch.setenv("SATHOP_TOKEN", "t")
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("SATHOP_POLL_INTERVAL", "60")
    monkeypatch.setenv("SATHOP_CONCURRENT_PULLS", "8")

    s = load()
    assert s.poll_interval == 60
    assert s.concurrent_pulls == 8


def test_config_load_raises_on_missing_required(monkeypatch):
    for k in ("SATHOP_RECEIVER_ID", "SATHOP_URL", "SATHOP_ORCH_URL", "SATHOP_TOKEN", "SATHOP_STORAGE_DIR"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        load()


def test_config_load_reads_sathop_url(monkeypatch, tmp_path):
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "r")
    monkeypatch.setenv("SATHOP_URL", "sathops://newtok@orch.example.com:443")
    monkeypatch.delenv("SATHOP_ORCH_URL", raising=False)
    monkeypatch.delenv("SATHOP_TOKEN", raising=False)
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path))

    s = load()
    assert s.orchestrator_url == "https://orch.example.com:443"
    assert s.token == "newtok"


def test_config_load_sathop_url_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "r")
    monkeypatch.setenv("SATHOP_URL", "sathop://winner@new:8000")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://loser:9000")
    monkeypatch.setenv("SATHOP_TOKEN", "loser-tok")
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path))

    s = load()
    assert s.orchestrator_url == "http://new:8000"
    assert s.token == "winner"
