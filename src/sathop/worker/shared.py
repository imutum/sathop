"""Shared-file sync: pull orchestrator-hosted files into a local cache keyed
by user-facing name. Orchestrator is the single source of truth.

Each cached file has a sidecar under `<root>/.sha256/<name>` holding the hex
digest so subsequent syncs can skip re-downloads without rehashing. Atomic
tmp-file + rename makes partial downloads invisible to running bundles.
Per-name threading lock prevents two granules from racing on the same name.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import urllib.request
from pathlib import Path

from sathop.shared.http import bearer_headers

_name_locks: dict[str, threading.Lock] = {}
_name_locks_guard = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _name_locks_guard:
        lock = _name_locks.get(name)
        if lock is None:
            lock = threading.Lock()
            _name_locks[name] = lock
        return lock


def _sidecar_path(root: Path, name: str) -> Path:
    return root / ".sha256" / name


def _local_sha(root: Path, name: str) -> str | None:
    if not (root / name).is_file():
        return None
    sidecar = _sidecar_path(root, name)
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8").strip() or None


def sync(names: list[str], shared_root: Path, orchestrator_url: str, token: str) -> None:
    """Ensure every listed name under `shared_root` matches orchestrator's
    current sha256. Missing or drifted files are re-pulled."""
    if not names:
        return
    shared_root.mkdir(parents=True, exist_ok=True)
    (shared_root / ".sha256").mkdir(parents=True, exist_ok=True)
    for name in names:
        with _lock_for(name):
            _sync_one(name, shared_root, orchestrator_url, token)


def _sync_one(name: str, shared_root: Path, orchestrator_url: str, token: str) -> None:
    base = orchestrator_url.rstrip("/")
    meta_req = urllib.request.Request(
        f"{base}/api/shared/{name}",
        headers=bearer_headers(token),
    )
    with urllib.request.urlopen(meta_req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"shared meta {name!r} failed: HTTP {resp.status}")
        meta = json.loads(resp.read().decode("utf-8"))
    remote_sha = meta["sha256"]

    if _local_sha(shared_root, name) == remote_sha:
        return

    dl_req = urllib.request.Request(
        f"{base}/api/shared/{name}/download",
        headers=bearer_headers(token),
    )
    tmp = tempfile.NamedTemporaryFile(dir=shared_root, prefix=f".{name}.", suffix=".part", delete=False)
    tmp_path = Path(tmp.name)
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(dl_req, timeout=600) as resp:
            if resp.status != 200:
                raise RuntimeError(f"shared download {name!r} failed: HTTP {resp.status}")
            with tmp:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    h.update(chunk)
        digest = h.hexdigest()
        if digest != remote_sha:
            raise RuntimeError(f"shared {name!r} sha256 mismatch: orch={remote_sha} got={digest}")
        dest = shared_root / name
        tmp_path.replace(dest)
        _sidecar_path(shared_root, name).write_text(digest, encoding="utf-8")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
