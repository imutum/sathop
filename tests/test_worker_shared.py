"""Worker shared-file sync: orch meta check, conditional download, sha256
verification, sidecar caching, per-name locking."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time

import pytest

from sathop.worker import shared as worker_shared


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class _Resp:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._buf = io.BytesIO(data)
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _meta(name: str, data: bytes) -> bytes:
    return json.dumps({"name": name, "sha256": _sha(data), "size": len(data)}).encode()


def _route(urls: dict[str, bytes | tuple[bytes, int]]):
    """urlopen stub dispatching on req.full_url."""

    def fake(req, timeout=30):
        v = urls[req.full_url]
        data, status = v if isinstance(v, tuple) else (v, 200)
        return _Resp(data, status)

    return fake


# ─── happy path ────────────────────────────────────────────────────────────


def test_sync_downloads_when_missing(tmp_path, monkeypatch):
    data = b"mask-bytes-v1"
    monkeypatch.setattr(
        worker_shared.urllib.request,
        "urlopen",
        _route(
            {
                "http://orch/api/shared/mask.tif": _meta("mask.tif", data),
                "http://orch/api/shared/mask.tif/download": data,
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

    calls: list[str] = []

    def fake(req, timeout=30):
        calls.append(req.full_url)
        return _Resp(_meta("mask.tif", data))

    monkeypatch.setattr(worker_shared.urllib.request, "urlopen", fake)
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert calls == ["http://orch/api/shared/mask.tif"]


def test_sync_redownloads_when_sha_drifts(tmp_path, monkeypatch):
    v1 = b"old"
    v2 = b"new-version-bytes"

    (tmp_path / "mask.tif").write_bytes(v1)
    (tmp_path / ".sha256").mkdir()
    (tmp_path / ".sha256" / "mask.tif").write_text(_sha(v1))

    monkeypatch.setattr(
        worker_shared.urllib.request,
        "urlopen",
        _route(
            {
                "http://orch/api/shared/mask.tif": _meta("mask.tif", v2),
                "http://orch/api/shared/mask.tif/download": v2,
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

    monkeypatch.setattr(
        worker_shared.urllib.request,
        "urlopen",
        _route(
            {
                "http://orch/api/shared/mask.tif": _meta("mask.tif", data),
                "http://orch/api/shared/mask.tif/download": data,
            }
        ),
    )
    worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert (tmp_path / ".sha256" / "mask.tif").read_text() == _sha(data)


# ─── failure modes ─────────────────────────────────────────────────────────


def test_sync_raises_on_sha_mismatch_and_leaves_no_partial(tmp_path, monkeypatch):
    data = b"real-bytes"
    bogus_meta = json.dumps(
        {"name": "mask.tif", "sha256": _sha(b"something-else"), "size": len(data)}
    ).encode()
    monkeypatch.setattr(
        worker_shared.urllib.request,
        "urlopen",
        _route(
            {
                "http://orch/api/shared/mask.tif": bogus_meta,
                "http://orch/api/shared/mask.tif/download": data,
            }
        ),
    )
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        worker_shared.sync(["mask.tif"], tmp_path, "http://orch", "tok")

    assert not (tmp_path / "mask.tif").exists()
    assert not list(tmp_path.glob(".mask.tif.*.part"))


def test_sync_raises_on_meta_404(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worker_shared.urllib.request,
        "urlopen",
        _route({"http://orch/api/shared/gone.tif": (b"", 404)}),
    )
    with pytest.raises(RuntimeError, match="HTTP 404"):
        worker_shared.sync(["gone.tif"], tmp_path, "http://orch", "tok")


def test_sync_empty_list_noop(tmp_path, monkeypatch):
    """No names → no HTTP calls, no dirs created."""
    called = [False]

    def fake(req, timeout=30):
        called[0] = True
        return _Resp(b"{}")

    monkeypatch.setattr(worker_shared.urllib.request, "urlopen", fake)
    worker_shared.sync([], tmp_path / "nope", "http://orch", "tok")
    assert called[0] is False
    assert not (tmp_path / "nope").exists()


def test_sync_sends_bearer_token(tmp_path, monkeypatch):
    data = b"x"
    seen: list[tuple[str, str | None]] = []

    def fake(req, timeout=30):
        seen.append((req.full_url, req.headers.get("Authorization")))
        if req.full_url.endswith("/download"):
            return _Resp(data)
        return _Resp(_meta("a", data))

    monkeypatch.setattr(worker_shared.urllib.request, "urlopen", fake)
    worker_shared.sync(["a"], tmp_path, "http://orch", "secret-tok")

    assert all(auth == "Bearer secret-tok" for _, auth in seen)


# ─── per-name lock ──────────────────────────────────────────────────────────


def test_lock_for_returns_same_lock_per_name():
    assert worker_shared._lock_for("x") is worker_shared._lock_for("x")
    assert worker_shared._lock_for("x") is not worker_shared._lock_for("y")


def test_concurrent_sync_of_same_name_serialized(tmp_path, monkeypatch):
    """Two threads calling sync() for the same name hit the orchestrator serially,
    not in parallel — guarded by the per-name lock."""
    data = b"content"

    in_flight = [0]
    peak = [0]
    barrier = threading.Event()

    def fake(req, timeout=30):
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        # First entrant sleeps so the second overlaps if locking is broken.
        if not barrier.is_set():
            barrier.set()
            time.sleep(0.05)
        try:
            if req.full_url.endswith("/download"):
                return _Resp(data)
            return _Resp(_meta("a.bin", data))
        finally:
            in_flight[0] -= 1

    monkeypatch.setattr(worker_shared.urllib.request, "urlopen", fake)

    def worker():
        worker_shared.sync(["a.bin"], tmp_path, "http://orch", "tok")

    threads = [threading.Thread(target=worker) for _ in range(2)]
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

    def fake(req, timeout=30):
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.03)
        try:
            url = req.full_url
            if url.endswith("/a.bin"):
                return _Resp(_meta("a.bin", data_a))
            if url.endswith("/b.bin"):
                return _Resp(_meta("b.bin", data_b))
            if url.endswith("/a.bin/download"):
                return _Resp(data_a)
            if url.endswith("/b.bin/download"):
                return _Resp(data_b)
            raise AssertionError(url)
        finally:
            in_flight[0] -= 1

    monkeypatch.setattr(worker_shared.urllib.request, "urlopen", fake)

    def worker(name):
        worker_shared.sync([name], tmp_path, "http://orch", "tok")

    threads = [
        threading.Thread(target=worker, args=("a.bin",)),
        threading.Thread(target=worker, args=("b.bin",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert peak[0] >= 2
    assert (tmp_path / "a.bin").exists()
    assert (tmp_path / "b.bin").exists()
