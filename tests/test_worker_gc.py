"""Worker-side cache GC: bundle.prune_caches + shared.prune_orphans.

Covers LRU eviction order, total-bytes threshold, lock-held skipping, stale
sidecar cleanup, and orphan removal against a mocked orchestrator listing."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from sathop.worker import bundle
from sathop.worker import shared as worker_shared


def _make_venv(venv_root: Path, ref: str, *, file_size: int = 1024) -> Path:
    """Create a fake venv tree under venv_root/<ref> with a file of `file_size`
    bytes; also drop the LRU sidecar so prune_caches sees it."""
    venv_dir = venv_root / ref
    (venv_dir / "lib").mkdir(parents=True, exist_ok=True)
    (venv_dir / "lib" / "blob.bin").write_bytes(b"x" * file_size)
    sidecar = venv_root / bundle._LAST_USED_DIR / ref
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.touch()
    return venv_dir


def _set_sidecar_mtime(venv_root: Path, ref: str, when: float) -> None:
    sidecar = venv_root / bundle._LAST_USED_DIR / ref
    os.utime(sidecar, (when, when))


def test_prune_caches_under_limit_is_noop(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    cache_root.mkdir()
    _make_venv(venv_root, "a@1", file_size=1024)
    _make_venv(venv_root, "b@1", file_size=1024)

    r = bundle.prune_caches(venv_root, cache_root, limit_bytes=10 * 1024)

    assert r["removed"] == 0
    assert r["freed_bytes"] == 0
    assert (venv_root / "a@1").is_dir()
    assert (venv_root / "b@1").is_dir()


def test_prune_caches_evicts_oldest_first(tmp_path: Path) -> None:
    """Total exceeds limit → evict by sidecar mtime ascending until under."""
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    cache_root.mkdir()
    # 3 venvs at 1024 bytes each; limit forces 1 eviction.
    for ref in ("old@1", "mid@1", "new@1"):
        _make_venv(venv_root, ref, file_size=1024)
        # Also create matching bundle source dir (prune deletes both).
        (cache_root / ref).mkdir()
        (cache_root / ref / "manifest.yaml").write_text("name: t\n", encoding="utf-8")

    now = time.time()
    _set_sidecar_mtime(venv_root, "old@1", now - 1000)
    _set_sidecar_mtime(venv_root, "mid@1", now - 500)
    _set_sidecar_mtime(venv_root, "new@1", now - 1)

    r = bundle.prune_caches(venv_root, cache_root, limit_bytes=2200)

    assert r["removed"] == 1
    assert r["freed_bytes"] >= 1024
    assert not (venv_root / "old@1").exists()
    assert not (cache_root / "old@1").exists()
    assert not (venv_root / bundle._LAST_USED_DIR / "old@1").exists()
    # Newer ones survive.
    assert (venv_root / "mid@1").is_dir()
    assert (venv_root / "new@1").is_dir()


def test_prune_caches_skips_locked_ref(tmp_path: Path) -> None:
    """A ref whose ensure() lock is held is mid-fetch/build; prune must not
    touch it. The prune should fall through to the next-oldest candidate."""
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    cache_root.mkdir()
    _make_venv(venv_root, "locked@1", file_size=1024)
    _make_venv(venv_root, "second@1", file_size=1024)

    now = time.time()
    _set_sidecar_mtime(venv_root, "locked@1", now - 1000)  # would be evicted first
    _set_sidecar_mtime(venv_root, "second@1", now - 500)

    held = bundle._ref_locks.get("orch:locked@1")
    held.acquire()
    try:
        r = bundle.prune_caches(venv_root, cache_root, limit_bytes=1024)
    finally:
        held.release()

    # locked@1 skipped; second@1 evicted instead.
    assert r["removed"] == 1
    assert (venv_root / "locked@1").is_dir()
    assert not (venv_root / "second@1").exists()


def test_prune_caches_cleans_stale_sidecar(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    cache_root.mkdir()
    sidecar_dir = venv_root / bundle._LAST_USED_DIR
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "ghost@1").touch()

    r = bundle.prune_caches(venv_root, cache_root, limit_bytes=10 * 1024)

    assert r["removed"] == 0
    assert not (sidecar_dir / "ghost@1").exists()


def test_prune_caches_evicts_dependency_free_bundle_sources(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    sidecar_dir = venv_root / bundle._LAST_USED_DIR
    bundle_dir = cache_root / "stdlib@1"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.yaml").write_text("name: stdlib\n", encoding="utf-8")
    (bundle_dir / "payload.bin").write_bytes(b"x" * 2048)
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "stdlib@1").touch()

    r = bundle.prune_caches(venv_root, cache_root, limit_bytes=1024)

    assert r["removed"] == 1
    assert r["freed_bytes"] >= 2048
    assert not bundle_dir.exists()
    assert not (sidecar_dir / "stdlib@1").exists()


def test_prune_caches_disabled_when_limit_zero(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    cache_root = tmp_path / "bundles"
    cache_root.mkdir()
    _make_venv(venv_root, "a@1", file_size=10_000)

    r = bundle.prune_caches(venv_root, cache_root, limit_bytes=0)

    assert r == {"removed": 0, "freed_bytes": 0, "total_bytes": 0}
    assert (venv_root / "a@1").is_dir()


def test_touch_last_used_creates_sidecar(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    bundle._touch_last_used(venv_root, "demo", "1.0")
    sidecar = venv_root / bundle._LAST_USED_DIR / "demo@1.0"
    assert sidecar.is_file()


def test_touch_last_used_refreshes_mtime(tmp_path: Path) -> None:
    venv_root = tmp_path / "venvs"
    bundle._touch_last_used(venv_root, "demo", "1.0")
    sidecar = venv_root / bundle._LAST_USED_DIR / "demo@1.0"
    old = time.time() - 500
    os.utime(sidecar, (old, old))
    bundle._touch_last_used(venv_root, "demo", "1.0")
    assert sidecar.stat().st_mtime > old


# ─── shared.prune_orphans ─────────────────────────────────────────────────


class _FakeResp:
    """Minimal context-managed urlopen-stand-in returning canned JSON."""

    def __init__(self, payload: list[dict]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._payload


def test_prune_orphans_removes_files_not_in_orch_list(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    (shared_root / ".sha256").mkdir()
    # 3 cached files; orch only knows about 1.
    for name in ("keep.tif", "orphan_a.tif", "orphan_b.json"):
        (shared_root / name).write_bytes(b"x" * 100)
        (shared_root / ".sha256" / name).write_text("0" * 64, encoding="utf-8")

    fake = _FakeResp([{"name": "keep.tif"}])
    with patch("urllib.request.urlopen", return_value=fake):
        r = worker_shared.prune_orphans(shared_root, "http://orch", "tok")

    assert r["removed"] == 2
    assert r["freed_bytes"] == 200
    assert (shared_root / "keep.tif").is_file()
    assert not (shared_root / "orphan_a.tif").exists()
    assert not (shared_root / "orphan_b.json").exists()
    # Sidecars cleaned up too.
    assert (shared_root / ".sha256" / "keep.tif").is_file()
    assert not (shared_root / ".sha256" / "orphan_a.tif").exists()


def test_prune_orphans_ignores_dotfiles_and_dirs(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    (shared_root / ".sha256").mkdir()
    (shared_root / ".tmpfile").write_bytes(b"x")  # dotfile guard
    (shared_root / "subdir").mkdir()  # someone left a dir; never our concern
    (shared_root / "real.tif").write_bytes(b"x" * 50)

    fake = _FakeResp([])  # orch returns nothing
    with patch("urllib.request.urlopen", return_value=fake):
        r = worker_shared.prune_orphans(shared_root, "http://orch", "tok")

    # Only real.tif should be removed; dotfile + subdir untouched.
    assert r["removed"] == 1
    assert (shared_root / ".tmpfile").is_file()
    assert (shared_root / "subdir").is_dir()
    assert not (shared_root / "real.tif").exists()


def test_prune_orphans_noop_when_root_missing(tmp_path: Path) -> None:
    """Worker that's never run a bundle has no shared_root yet; prune mustn't
    crash trying to enumerate a non-existent directory."""
    r = worker_shared.prune_orphans(tmp_path / "missing", "http://orch", "tok")
    assert r == {"removed": 0, "freed_bytes": 0}


def test_prune_orphans_noop_when_cache_has_no_data_files(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    (shared_root / ".sha256").mkdir()
    with patch("urllib.request.urlopen") as urlopen:
        r = worker_shared.prune_orphans(shared_root, "http://orch", "tok")
    assert r == {"removed": 0, "freed_bytes": 0}
    urlopen.assert_not_called()
