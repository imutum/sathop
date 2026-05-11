"""Receiver._fetch_one_inner: verify + ack flow covering happy, sha-mismatch,
and pull-error paths. Plus config.load() env-var handling."""

from __future__ import annotations

import asyncio
import hashlib
import ssl
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from sathop.receiver.config import Settings, load
from sathop.receiver.runtime import Receiver
from sathop.receiver.runtime import is_cert_error as _is_cert_error
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
        await r._fetch_one_inner(it)

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
        await r._fetch_one_inner(it)

        # Corrupt file was unlinked
        assert not (tmp_path / "archive" / "b1" / "g1" / "corrupt.bin").exists()
        assert len(acks) == 1
        assert acks[0].success is False
        assert acks[0].error and "mismatch" in acks[0].error
    finally:
        srv.shutdown()


async def test_concurrent_pulls_same_dest_do_not_race(tmp_path):
    """Two tasks pulling the SAME object_key concurrently must both finish
    cleanly — no `tmp not found` rename error. This used to corrupt: with a
    fixed `<dest>.part`, the first rename would atomically move it to dest
    while the second was still writing, and the second's rename would then
    ENOENT on src. Per-pull random `.part-<token>` makes the writes
    independent; the rename is last-writer-wins, which is fine."""
    payload = b"shared-dest-bytes"
    srv, port = _serve(payload)
    try:
        r, acks = _make_receiver(tmp_path)
        url = f"http://127.0.0.1:{port}/"
        item = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/shared.bin",
            presigned_url=url,
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        # Two object_ids, identical key — simulates the race shape (orch
        # offering twice, multi-receiver shared volume, etc).
        item2 = item.model_copy(update={"object_id": 2})
        await asyncio.gather(r._fetch_one_inner(item), r._fetch_one_inner(item2))

        # Both acks should be success — neither task's rename should have
        # tripped over the other's tmp.
        assert len(acks) == 2
        assert all(a.success for a in acks), [a.error for a in acks]
        # Final dest exists; no leftover .part-* files.
        dest = tmp_path / "archive" / "b1" / "g1" / "shared.bin"
        assert dest.read_bytes() == payload
        leftovers = list(dest.parent.glob("*.part*"))
        assert leftovers == [], leftovers
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
    await r._fetch_one_inner(it)

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
    # 16 since 0.3.11 — pipeline (producer + N workers) makes high N cheap
    # so we ship a default that saturates a typical home/office link.
    assert s.concurrent_pulls == 16
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
    with pytest.raises(RuntimeError, match="missing orchestrator URL"):
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


# ─── TLS trust ────────────────────────────────────────────────────────────


def test_config_load_defaults_tls_trust_orch_true(monkeypatch, tmp_path):
    """Self-signed worker certs are the default deployment shape; receivers
    must trust the orchestrator-managed CA bundle out of the box."""
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "r")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://x")
    monkeypatch.setenv("SATHOP_TOKEN", "t")
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("SATHOP_TLS_TRUST_ORCH", raising=False)
    s = load()
    assert s.tls_verify is True
    assert s.tls_trust_orch is True


def test_config_load_tls_trust_orch_off_when_explicitly_false(monkeypatch, tmp_path):
    monkeypatch.setenv("SATHOP_RECEIVER_ID", "r")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://x")
    monkeypatch.setenv("SATHOP_TOKEN", "t")
    monkeypatch.setenv("SATHOP_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("SATHOP_TLS_TRUST_ORCH", "false")
    assert load().tls_trust_orch is False


def test_is_cert_error_walks_cause_chain():
    """`raise ... from e` sets __cause__ (explicit chaining)."""
    try:
        try:
            raise ssl.SSLError("certificate verify failed")
        except ssl.SSLError as e:
            raise RuntimeError("connect failed") from e
    except RuntimeError as e:
        assert _is_cert_error(e) is True

    assert _is_cert_error(RuntimeError("network down")) is False


def test_is_cert_error_walks_context_chain():
    """Bare `raise X` inside an `except:` block sets __context__ implicitly —
    this is exactly how httpx wraps the underlying httpcore/ssl error, and a
    walker that only follows __cause__ misses it (regression: v0.3.3 shipped
    with a __cause__-only walk that left receivers permanently stuck on cert
    errors despite the lazy-refresh path being wired in)."""
    try:
        try:
            raise ssl.SSLError("certificate verify failed")
        except ssl.SSLError:
            raise RuntimeError("wrapped — no `from` clause")
    except RuntimeError as e:
        assert _is_cert_error(e) is True


def test_is_cert_error_handles_real_httpx_self_signed_chain():
    """Reproduce the exact exception shape httpx raises on a self-signed cert
    so a future refactor that breaks the chain walk fails this test loudly."""
    import httpx

    # 127.0.0.1:1 refuses fast on most platforms; flip a real httpx call to a
    # self-signed endpoint instead would require a server, so we manually
    # rebuild the chain shape httpx actually emits (verified by inspection).
    try:
        try:
            try:
                raise ssl.SSLCertVerificationError(
                    1,
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate",
                )
            except ssl.SSLCertVerificationError:
                raise httpx.ConnectError(
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate"
                )
        except httpx.ConnectError:
            raise httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate"
            )
    except httpx.ConnectError as e:
        assert isinstance(e, ssl.SSLError) is False, "sanity: top-level is not SSLError"
        assert _is_cert_error(e) is True


async def test_pull_retries_once_after_refreshing_trust_on_cert_error(tmp_path, monkeypatch):
    """First pull attempt raises a cert error; receiver refreshes its trust
    bundle and retries; second attempt succeeds. Covers the case where a worker
    registered after our startup snapshot."""
    payload = b"after-refresh"
    srv, port = _serve(payload)
    try:
        r, acks = _make_receiver(tmp_path)
        # Make sure the retry path can run.
        r.s = replace(r.s, tls_trust_orch=True, tls_verify=True)

        refreshes = 0

        async def fake_refresh() -> None:
            nonlocal refreshes
            refreshes += 1

        # Wrap _pull_single so the FIRST call simulates an SSL cert error and
        # subsequent calls fall through to the real implementation. (Sub-MB
        # payload skips segmented dispatch, so single is the only path here.)
        from sathop.receiver import puller as recv_mod

        real_pull = recv_mod.pull_single
        calls = 0

        async def flaky_pull(client, url, dest):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Emit the same __context__-wrapped shape httpx produces on a
                # real cert verify failure — bare ssl.SSLError used to pass
                # because the chain was trivial. v0.3.4 walks __context__ too.
                try:
                    raise ssl.SSLError("certificate verify failed: self-signed certificate")
                except ssl.SSLError:
                    raise RuntimeError("ConnectError wrap")
            return await real_pull(client, url, dest)

        monkeypatch.setattr(recv_mod, "pull_single", flaky_pull)
        monkeypatch.setattr(r, "_refresh_trust", fake_refresh)

        it = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=42,
            object_key="b1/g1/out.bin",
            presigned_url=f"http://127.0.0.1:{port}/",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one_inner(it)

        assert refreshes == 1, "trust must be refreshed before the retry"
        assert calls == 2, "second pull should fire after the refresh"
        assert len(acks) == 1
        assert acks[0].success is True
    finally:
        srv.shutdown()


async def test_pull_does_not_refresh_when_trust_orch_disabled(tmp_path, monkeypatch):
    """Operator who set tls_trust_orch=false has their own trust setup; we
    must not silently bypass it by refetching the orch bundle."""
    r, acks = _make_receiver(tmp_path)
    r.s = replace(r.s, tls_trust_orch=False, tls_verify=True)

    refreshes = 0

    async def fake_refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    from sathop.receiver import puller as recv_mod

    async def always_cert_error(client, url, dest):
        try:
            raise ssl.SSLError("certificate verify failed")
        except ssl.SSLError:
            raise RuntimeError("ConnectError wrap")

    monkeypatch.setattr(recv_mod, "pull_single", always_cert_error)
    monkeypatch.setattr(r, "_refresh_trust", fake_refresh)

    it = PullItem(
        granule_id="g1",
        batch_id="b1",
        object_id=99,
        object_key="b1/g1/x.bin",
        presigned_url="http://127.0.0.1:1/",
        sha256="0" * 64,
        size=1,
    )
    await r._fetch_one_inner(it)
    assert refreshes == 0
    assert len(acks) == 1
    assert acks[0].success is False
