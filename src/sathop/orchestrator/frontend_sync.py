"""Keep frontend/dist in lockstep with the running orchestrator version.

The dist for version V ships as a GitHub Release asset (frontend-dist.tar.gz on
tag vV). `ensure_frontend` fetches and unpacks it, stamping the dir with the
version (.version) and asset sha256 (.sha256) so a later boot can tell — cheaply,
by version — whether the deployed UI matches the code now running.

Two callers:
- startup (version-gated, force=False): a code upgrade pulled new backend code,
  so the dist a version behind is refreshed to match. No network when versions
  already agree.
- admin endpoint (force=True): operator-triggered, content-hashed — always fetch
  to detect a same-version-but-rebuilt asset.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tarfile
from io import BytesIO
from pathlib import Path

import httpx

# orchestrator/frontend_sync.py → parents[3] is the repo root (same depth as main.py).
_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"

# Serialize mutations so two rapid operator clicks (or boot-sync racing an
# endpoint call) can't interleave their directory swaps.
_lock = asyncio.Lock()


def _stamps() -> tuple[Path, Path]:
    return _DIST_DIR / ".version", _DIST_DIR / ".sha256"


def _asset_url(version: str) -> str:
    git_repo = os.environ.get("SATHOP_GIT_REPO", "https://github.com/imutum/sathop.git")
    clean = git_repo.removesuffix(".git")
    return os.environ.get(
        "SATHOP_FRONTEND_URL",
        f"{clean}/releases/download/v{version}/frontend-dist.tar.gz",
    )


async def ensure_frontend(version: str, *, force: bool = False, timeout: float = 60) -> dict:
    """Make frontend/dist match `version`. Version-gated unless `force`.

    Returns ``{action, version[, sha]}`` where action is ``already_up_to_date``
    or ``downloaded``. Network / archive errors propagate — callers decide
    whether to swallow (startup) or surface (endpoint). `timeout` bounds the
    download so a hanging GitHub can't stall a caller (e.g. startup) for long."""
    version_stamp, sha_stamp = _stamps()

    if not force and _DIST_DIR.is_dir() and version_stamp.is_file():
        if version_stamp.read_text().strip() == version:
            return {"action": "already_up_to_date", "version": version}

    async with _lock:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            r = await client.get(_asset_url(version))
            r.raise_for_status()

        digest = hashlib.sha256(r.content).hexdigest()
        # Same bytes already deployed → just (re)stamp the version, skip the swap.
        if sha_stamp.is_file() and sha_stamp.read_text().strip() == digest:
            version_stamp.write_text(version)
            return {"action": "already_up_to_date", "version": version, "sha": digest}

        _extract(r.content, digest=digest, version=version)
        return {"action": "downloaded", "version": version, "sha": digest}


def _extract(content: bytes, *, digest: str, version: str) -> None:
    """Stage into a sibling tmp dir — stamps included — then swap into place by
    rename. A concurrent reader (/assets, spa_fallback, /api/health) sees either
    the fully-stamped old tree or the fully-stamped new one; the only gap is the
    two rename syscalls where dist is briefly absent, not a whole rmtree."""
    tmp_dir = _DIST_DIR.parent / ".dist-tmp"
    backup = _DIST_DIR.parent / ".dist-old"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    with tarfile.open(fileobj=BytesIO(content), mode="r:gz") as tf:
        tf.extractall(tmp_dir, filter="data")  # reject path-traversal entries

    extracted = tmp_dir / "dist"
    if not extracted.is_dir():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ValueError("archive does not contain a dist/ directory")

    # Stamp inside the staged tree so the swapped-in dir is already complete.
    (extracted / ".sha256").write_text(digest)
    (extracted / ".version").write_text(version)

    if backup.exists():
        shutil.rmtree(backup)
    if _DIST_DIR.exists():
        _DIST_DIR.rename(backup)
    extracted.rename(_DIST_DIR)
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
