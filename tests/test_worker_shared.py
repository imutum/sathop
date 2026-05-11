"""Worker shared-file sync: orch meta check, conditional download, sha256
verification, sidecar caching, per-name locking."""

from __future__ import annotations

import hashlib
import json
import threading
import time

import httpx
import pytest

from sathop.worker import shared as worker_shared


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _meta_body(name: str, data: bytes) -> dict:
    return {"name": name, "sha256": _sha(data), "size": len(data)}


def _route(urls: dict[str, tuple[int, bytes] | bytes | dict]):
    """MockTransport handler keyed on the trailing path; values may be raw
    bytes (200), JSON-able dicts (200), or (status, bytes) tuples."""

    def handler(req: httpx.Request) -> httpx.Response:
        key = req.url.path
        v = urls[key]
        if isinstance(v, tuple):
            status, body = v
            return httpx.Response(status, content=body)
        if isinstance(v, dict):
            return httpx.Response(200, json=v)
        return httpx.Response(200, content=v)

    return handler


def _patch_client(monkeypatch, handler, capture: list | None = None):
    """Replace `make_sync_orch_client` so all `_sync_one` / `prune_orphans`
    HTTP calls hit our MockTransport. When `capture` is given, every request
    is appended as (path, Authorization-header) for assertion."""

    def fake(orch_url: str, token: str, timeout: float = 30.0) -> httpx.Client:
        def wrapped(req: httpx.Request) -> httpx.Response:
            if capture is not None:
                capture.append((req.url.path, req.headers.get("Authorization")))
            return handler(req)

        return httpx.Client(
            base_url=orch_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            transport=httpx.MockTransport(wrapped),
        )

    monkeypatch.setattr(worker_shared, "make_sync_orch_client", fake)


# ─── happy path ────────────────────────────────────────────────────────────


def test_sync_downloads_when_missing(tmp_path, monkeypatch):
    data = b"mask-bytes-v1"
    _patch_client(
        monkeypatch,
        _route(
            {
                "/api/shared/mask.tif": _meta_body("mask.tif", data),
                "/api/shared/mask.tif/download": data,
            }
        ),
    )
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert (tmp_path / "mask.tif").read_bytes() == data
    assert (tmp_path / ".sha256" / "mask.tif").read_text() == _sha(data)


def test_sync_skips_download_when_sha_matches(tmp_path, monkeypatch):
    """If local sidecar matches orch sha, the download endpoint is never hit."""
    data = b"same"
    sha = _sha(data)

    (tmp_path / "mask.tif").write_bytes(data)
    sidecar_dir = tmp_path / ".sha256"
    sidecar_dir.mkdir()
    (sidecar_dir / "mask.tif").write_text(sha)

    calls: list[tuple[str, str | None]] = []
    _patch_client(
        monkeypatch,
        _route({"/api/shared/mask.tif": _meta_body("mask.tif", data)}),
        capture=calls,
    )
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert [path for path, _ in calls] == ["/api/shared/mask.tif"]


def test_sync_redownloads_when_sha_drifts(tmp_path, monkeypatch):
    v1 = b"old"
    v2 = b"new-version-bytes"

    (tmp_path / "mask.tif").write_bytes(v1)
    (tmp_path / ".sha256").mkdir()
    (tmp_path / ".sha256" / "mask.tif").write_text(_sha(v1))

    _patch_client(
        monkeypatch,
        _route(
            {
                "/api/shared/mask.tif": _meta_body("mask.tif", v2),
                "/api/shared/mask.tif/download": v2,
            }
        ),
    )
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert (tmp_path / "mask.tif").read_bytes() == v2
    assert (tmp_path / ".sha256" / "mask.tif").read_text() == _sha(v2)


def test_sync_without_sidecar_triggers_refetch(tmp_path, monkeypatch):
    """File exists but sidecar missing → treat as drifted, re-download."""
    data = b"payload"
    (tmp_path / "mask.tif").write_bytes(data)  # no sidecar

    _patch_client(
        monkeypatch,
        _route(
            {
                "/api/shared/mask.tif": _meta_body("mask.tif", data),
                "/api/shared/mask.tif/download": data,
            }
        ),
    )
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert (tmp_path / ".sha256" / "mask.tif").read_text() == _sha(data)


# ─── failure modes ─────────────────────────────────────────────────────────


def test_sync_raises_on_sha_mismatch_and_leaves_no_partial(tmp_path, monkeypatch):
    data = b"real-bytes"
    bogus = {"name": "mask.tif", "sha256": _sha(b"something-else"), "size": len(data)}
    _patch_client(
        monkeypatch,
        _route(
            {
                "/api/shared/mask.tif": bogus,
                "/api/shared/mask.tif/download": data,
            }
        ),
    )
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert not (tmp_path / "mask.tif").exists()
    assert not list(tmp_path.glob(".mask.tif.*.part"))


def test_sync_raises_on_meta_404(tmp_path, monkeypatch):
    _patch_client(monkeypatch, _route({"/api/shared/gone.tif": (404, b"")}))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        worker_shared.sync(["gone.tif"], tmp_path, "http://orch", "tok")


def test_sync_empty_list_noop(tmp_path, monkeypatch):
    """No names → no HTTP calls, no dirs created."""
    called = [False]

    def handler(req: httpx.Request) -> httpx.Response:
        called[0] = True
        return httpx.Response(200, json={})

    _patch_client(monkeypatch, handler)
    worker_shared.sync([], tmp_path / "nope", "http://orch", "tok")
    assert called[0] is False
    assert not (tmp_path / "nope").exists()


def test_sync_sends_bearer_token(tmp_path, monkeypatch):
    data = b"x"
    seen: list[tuple[str, str | None]] = []
    _patch_client(
        monkeypatch,
        _route(
            {
                "/api/shared/a": _meta_body("a", data),
                "/api/shared/a/download": data,
            }
        ),
        capture=seen,
    )
    worker_shared.sync(["a"], tmp_path, "http://orch", "secret-tok")

    assert all(auth == "Bearer secret-tok" for _, auth in seen)


# ─── per-name lock ──────────────────────────────────────────────────────────


def test_lock_for_returns_same_lock_per_name():
    assert worker_shared._name_locks.get("x") is worker_shared._name_locks.get("x")
    assert worker_shared._name_locks.get("x") is not worker_shared._name_locks.get("y")


def test_concurrent_sync_of_same_name_serialized(tmp_path, monkeypatch):
    """Two threads calling sync() for the same name hit the orchestrator serially,
    not in parallel — guarded by the per-name lock."""
    data = b"content"

    in_flight = [0]
    peak = [0]
    barrier = threading.Event()

    def handler(req: httpx.Request) -> httpx.Response:
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        if not barrier.is_set():
            barrier.set()
            time.sleep(0.05)
        try:
            if req.url.path.endswith("/download"):
                return httpx.Response(200, content=data)
            return httpx.Response(200, json=_meta_body("a.bin", data))
        finally:
            in_flight[0] -= 1

    _patch_client(monkeypatch, handler)

    def runner():
        worker_shared.sync(["a.bin"], tmp_path, "http://orch", "tok")

    threads = [threading.Thread(target=runner) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert peak[0] == 1
    assert (tmp_path / "a.bin").read_bytes() == data


def test_concurrent_sync_of_different_names_proceed_in_parallel(tmp_path, monkeypatch):
    """Different names don't block each other — locks are per-name."""
    data_a = b"A"
    data_b = b"B"

    in_flight = [0]
    peak = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.03)
        try:
            path = req.url.path
            if path == "/api/shared/a.bin":
                return httpx.Response(200, json=_meta_body("a.bin", data_a))
            if path == "/api/shared/b.bin":
                return httpx.Response(200, json=_meta_body("b.bin", data_b))
            if path == "/api/shared/a.bin/download":
                return httpx.Response(200, content=data_a)
            if path == "/api/shared/b.bin/download":
                return httpx.Response(200, content=data_b)
            raise AssertionError(path)
        finally:
            in_flight[0] -= 1

    _patch_client(monkeypatch, handler)

    def runner(name):
        worker_shared.sync([name], tmp_path, "http://orch", "tok")

    threads = [
        threading.Thread(target=runner, args=("a.bin",)),
        threading.Thread(target=runner, args=("b.bin",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert peak[0] >= 2
    assert (tmp_path / "a.bin").exists()
    assert (tmp_path / "b.bin").exists()
