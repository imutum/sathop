"""HttpDownloader auth translation tests (Credential → httpx header)."""

from __future__ import annotations

import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sathop.shared.protocol import Credential
from sathop.worker.downloader import HttpDownloader


def _start(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int]:
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _serve_requiring(expected_auth: str, payload: bytes) -> tuple[HTTPServer, int]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != expected_auth:
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return _start(H)


def _serve_payload(payload: bytes, *, send_content_length: bool = True) -> tuple[HTTPServer, int]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            self.send_response(200)
            if send_content_length:
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return _start(H)


async def test_bearer_token_attaches_header(tmp_path):
    srv, port = _serve_requiring("Bearer nasa-edl-xyz", b"bearer-ok")
    try:
        dl = HttpDownloader()
        dest = tmp_path / "f.bin"
        n = await dl.fetch(
            f"http://127.0.0.1:{port}/f",
            dest,
            auth=Credential(name="edl", scheme="bearer", token="nasa-edl-xyz"),
        )
        assert n == 9
        assert dest.read_bytes() == b"bearer-ok"
    finally:
        srv.shutdown()


async def test_bearer_wrong_token_401s(tmp_path):
    srv, port = _serve_requiring("Bearer correct", b"x")
    try:
        dl = HttpDownloader()
        with pytest.raises(Exception):
            await dl.fetch(
                f"http://127.0.0.1:{port}/f",
                tmp_path / "f.bin",
                auth=Credential(name="x", scheme="bearer", token="wrong"),
            )
    finally:
        srv.shutdown()


async def test_basic_auth(tmp_path):
    expected = "Basic " + base64.b64encode(b"alice:s3cr3t").decode()
    srv, port = _serve_requiring(expected, b"basic-ok")
    try:
        dl = HttpDownloader()
        dest = tmp_path / "f.bin"
        await dl.fetch(
            f"http://127.0.0.1:{port}/f",
            dest,
            auth=Credential(name="x", scheme="basic", username="alice", password="s3cr3t"),
        )
        assert dest.read_bytes() == b"basic-ok"
    finally:
        srv.shutdown()


async def test_progress_cb_invoked(tmp_path):
    """Cb sees monotonically growing `downloaded`, hits exact total at end, and
    `total` matches Content-Length on every call."""
    payload = b"x" * 1_500_000  # 1.5 MB → at least 6 × 256KB chunks
    srv, port = _serve_payload(payload)
    calls: list[tuple[int, int | None]] = []

    async def cb(downloaded: int, total: int | None) -> None:
        calls.append((downloaded, total))

    try:
        n = await HttpDownloader().fetch(f"http://127.0.0.1:{port}/f", tmp_path / "f", progress_cb=cb)
    finally:
        srv.shutdown()

    assert n == len(payload)
    assert len(calls) >= 2
    assert all(t == len(payload) for _, t in calls)
    downloaded_seq = [d for d, _ in calls]
    assert downloaded_seq == sorted(downloaded_seq)
    assert downloaded_seq[-1] == len(payload)


async def test_progress_cb_no_content_length(tmp_path):
    """Server omits Content-Length → cb still fires with total=None each call."""
    payload = b"y" * 300_000
    srv, port = _serve_payload(payload, send_content_length=False)
    calls: list[tuple[int, int | None]] = []

    async def cb(downloaded: int, total: int | None) -> None:
        calls.append((downloaded, total))

    try:
        await HttpDownloader().fetch(f"http://127.0.0.1:{port}/f", tmp_path / "f", progress_cb=cb)
    finally:
        srv.shutdown()

    assert len(calls) >= 1
    assert calls[-1][0] == len(payload)


async def test_no_auth_passes_nothing(tmp_path):
    """Server that permits unauthenticated GETs should see no Authorization header."""
    seen_auth: list[str | None] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            seen_auth.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        await HttpDownloader().fetch(f"http://127.0.0.1:{port}/f", tmp_path / "f", auth=None)
    finally:
        srv.shutdown()
    assert seen_auth == [None]
