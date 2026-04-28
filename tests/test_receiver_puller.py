"""Receiver puller: HTTP stream → atomic rename, sha256 + size computed on the fly.
Uses the same http.server pattern test_downloader uses."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sathop.receiver.main import _pull_http as pull


def _serve_static(payload: bytes) -> tuple[HTTPServer, int]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            if self.path != "/f":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


async def test_pull_writes_file_and_reports_sha_and_size(tmp_path):
    # Payload deliberately larger than one chunk (256KB) to exercise streaming.
    payload = b"x" * (700 * 1024)
    srv, port = _serve_static(payload)
    try:
        dest = tmp_path / "out" / "sub" / "granule.bin"
        sha, size = await pull(f"http://127.0.0.1:{port}/f", dest)
        assert sha == hashlib.sha256(payload).hexdigest()
        assert size == len(payload)
        assert dest.read_bytes() == payload
        # .part file should be gone after atomic replace
        assert not dest.with_suffix(dest.suffix + ".part").exists()
    finally:
        srv.shutdown()


async def test_pull_creates_parent_dirs(tmp_path):
    srv, port = _serve_static(b"hello")
    try:
        dest = tmp_path / "deep" / "nested" / "path" / "f.bin"
        assert not dest.parent.exists()
        sha, size = await pull(f"http://127.0.0.1:{port}/f", dest)
        assert dest.read_bytes() == b"hello"
        assert size == 5
        assert sha == hashlib.sha256(b"hello").hexdigest()
    finally:
        srv.shutdown()


async def test_pull_404_raises(tmp_path):
    srv, port = _serve_static(b"only-served-at-/f")
    try:
        with pytest.raises(Exception):
            await pull(f"http://127.0.0.1:{port}/nope", tmp_path / "x.bin")
    finally:
        srv.shutdown()


async def test_pull_cleans_up_part_on_mid_stream_failure(tmp_path):
    """If the server hangs up mid-stream, the partial `.part` file must be
    removed — otherwise it lingers on disk after permanent download failures
    (e.g. orchestrator stops offering the object before retry overwrites it)."""

    class HangUp(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            # Lie about size so the client expects more bytes than we send,
            # then drop the connection partway through.
            self.send_response(200)
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.write(b"x" * 4096)
            self.wfile.flush()
            # Forcibly close — client will hit a transport error mid-stream.
            self.connection.close()

    srv = HTTPServer(("127.0.0.1", 0), HangUp)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    dest = tmp_path / "out.bin"
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with pytest.raises(Exception):
            await pull(f"http://127.0.0.1:{port}/f", dest)
    finally:
        srv.shutdown()
    assert not dest.exists(), "dest should not exist on failure"
    assert not part.exists(), ".part should be cleaned up on mid-stream failure"
