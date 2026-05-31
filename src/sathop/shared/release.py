"""Release-bundle helpers shared by the orchestrator upgrade endpoint and the
worker update path.

`.pending-version` is the one-shot stamp the runtime entrypoint
(`deploy/runtime/entrypoint.sh`) consumes on its next boot to install a specific
release. Both the orchestrator (operator clicks "升级到 vX") and a worker
(receives a versioned update signal over heartbeat) write it into the same
`REPO_DIR` the entrypoint reads — so the install path is identical regardless of
which component triggered it."""

from __future__ import annotations

import os
import re
from pathlib import Path

PENDING_VERSION_FILE = ".pending-version"


def repo_root() -> Path:
    """The bundle root (the dir holding ``pyproject.toml`` + ``src/``). Found by
    walking up from this module so it works at any install depth, not a brittle
    ``parents[N]``. Under the A/B-slots layout this is the *slot* dir
    (``<REPO_DIR>/slots/<ver>``), since the editable install lives there — use
    :func:`stamp_dir` for the entrypoint's stamp location, not this."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[3]  # fallback: src/sathop/shared/release.py → repo root


def stamp_dir() -> Path:
    """Dir the entrypoint reads ``.pending-version`` from (its ``REPO_DIR``).

    The entrypoint may export ``SATHOP_REPO_DIR`` explicitly. Otherwise derive it
    from :func:`repo_root`: under the A/B-slots layout the editable src lives at
    ``<REPO_DIR>/slots/<ver>/``, so ``repo_root()`` resolves to the slot — climb to
    the slots parent (the dir the entrypoint owns). In a plain dev checkout
    ``repo_root()`` already IS that dir. Writing the stamp into the slot instead is
    the bug that made UI upgrades silently no-op (entrypoint reads ``REPO_DIR``)."""
    env = os.environ.get("SATHOP_REPO_DIR", "").strip()
    if env:
        return Path(env)
    root = repo_root()
    if root.parent.name == "slots":  # <REPO_DIR>/slots/<ver> → <REPO_DIR>
        return root.parent.parent
    return root


def normalize_version(version: str) -> str:
    """Strip a leading ``v`` and validate ``MAJOR.MINOR[.PATCH][suffix]``. The
    pattern is FULLY anchored and excludes ``/`` ``\\`` and whitespace: the value
    is concatenated into a release-asset URL and written to ``.pending-version``,
    so an unanchored match (e.g. ``0.8.1/../v0.7.0``) would be a path-traversal /
    arbitrary-version-install vector. Raises ValueError on anything else."""
    v = version.strip().lstrip("v")
    if not re.fullmatch(r"\d+\.\d+[0-9A-Za-z.+-]*", v):
        raise ValueError(f"invalid version: {version!r}")
    return v


def write_pending_version(version: str) -> Path:
    """Stamp ``REPO_DIR/.pending-version`` so the next entrypoint boot installs
    ``version``. Returns the path written. Targets :func:`stamp_dir` (the dir the
    entrypoint reads), not the slot the running code is installed in."""
    path = stamp_dir() / PENDING_VERSION_FILE
    path.write_text(normalize_version(version))
    return path
