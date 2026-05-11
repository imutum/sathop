"""Shared-file sync: pull orchestrator-hosted files into a local cache keyed
by user-facing name. Orchestrator is the single source of truth.

Each cached file has a sidecar under `<root>/.sha256/<name>` holding the hex
digest so subsequent syncs can skip re-downloads without rehashing. Atomic
tmp-file + rename makes partial downloads invisible to running bundles.
Per-name threading lock prevents two granules from racing on the same name.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path

from sathop.shared.http import make_sync_orch_client
from sathop.shared.locks import NamedLockRegistry
from sathop.shared.safe_path import safe_join

log = logging.getLogger("sathop.worker.shared")

_name_locks = NamedLockRegistry()


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
        with _name_locks.get(name):
            _sync_one(name, shared_root, orchestrator_url, token)


def prune_orphans(shared_root: Path, orchestrator_url: str, token: str) -> dict:
    """Remove cached shared files whose name is no longer in the orchestrator
    registry. Returns {removed, freed_bytes}. Sidecars (`.sha256/<name>`) are
    cleaned up alongside their data file. The per-name lock keeps a concurrent
    `_sync_one()` from re-creating a file we just unlinked (sync acquires
    first ⇒ we wait; we acquire first ⇒ sync sees missing local + refetches).

    Re-uploading a previously-deleted name to the orch registry is the safety
    net for a wrongly-pruned file: the next ensure() on a bundle declaring it
    will re-fetch."""
    if not shared_root.is_dir():
        return {"removed": 0, "freed_bytes": 0}
    candidates = [p for p in shared_root.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not candidates:
        return {"removed": 0, "freed_bytes": 0}

    with make_sync_orch_client(orchestrator_url, token, timeout=30) as c:
        r = c.get("/api/shared")
        if r.status_code != 200:
            raise RuntimeError(f"shared list failed: HTTP {r.status_code}")
        rows = r.json()
    valid: set[str] = {row["name"] for row in rows}

    sidecar_dir = shared_root / ".sha256"
    removed = 0
    freed = 0
    for entry in candidates:
        if entry.name in valid:
            continue
        with _name_locks.get(entry.name):
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            try:
                entry.unlink()
            except OSError:
                continue
            (sidecar_dir / entry.name).unlink(missing_ok=True)
        removed += 1
        freed += size
        log.info("dropped orphan shared %s (%d bytes)", entry.name, size)
    return {"removed": removed, "freed_bytes": freed}


def _sync_one(name: str, shared_root: Path, orchestrator_url: str, token: str) -> None:
    with make_sync_orch_client(orchestrator_url, token, timeout=30) as c:
        r = c.get(f"/api/shared/{name}")
        if r.status_code != 200:
            raise RuntimeError(f"shared meta {name!r} failed: HTTP {r.status_code}")
        remote_sha = r.json()["sha256"]

        if _local_sha(shared_root, name) == remote_sha:
            return

        tmp = tempfile.NamedTemporaryFile(dir=shared_root, prefix=f".{name}.", suffix=".part", delete=False)
        tmp_path = Path(tmp.name)
        h = hashlib.sha256()
        try:
            with c.stream("GET", f"/api/shared/{name}/download", timeout=600) as dl:
                if dl.status_code != 200:
                    raise RuntimeError(f"shared download {name!r} failed: HTTP {dl.status_code}")
                with tmp:
                    for chunk in dl.iter_bytes(1 << 20):
                        tmp.write(chunk)
                        h.update(chunk)
            digest = h.hexdigest()
            if digest != remote_sha:
                raise RuntimeError(f"shared {name!r} sha256 mismatch: orch={remote_sha} got={digest}")
            dest = safe_join(shared_root, name)
            tmp_path.replace(dest)
            _sidecar_path(shared_root, name).write_text(digest, encoding="utf-8")
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
