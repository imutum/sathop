"""Release-bundle helpers shared by the orchestrator upgrade endpoint and the
worker update path.

`.pending-version` is the one-shot stamp the runtime entrypoint
(`deploy/runtime/entrypoint.sh`) consumes on its next boot to install a specific
release. Both the orchestrator (operator clicks "升级到 vX") and a worker
(receives a versioned update signal over heartbeat) write it into the same
`REPO_DIR` the entrypoint reads — so the install path is identical regardless of
which component triggered it."""

from __future__ import annotations

import re
from pathlib import Path

PENDING_VERSION_FILE = ".pending-version"


def repo_root() -> Path:
    """The bundle root (the dir holding ``pyproject.toml`` + ``src/``) that the
    entrypoint owns. Found by walking up from this module so it works at any
    install depth (container ``/app/repo`` or a dev checkout), not a brittle
    ``parents[N]``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[3]  # fallback: src/sathop/shared/release.py → repo root


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
    ``version``. Returns the path written."""
    path = repo_root() / PENDING_VERSION_FILE
    path.write_text(normalize_version(version))
    return path
