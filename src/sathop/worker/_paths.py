"""Filesystem-safe path segment helper.

Granule IDs from the orchestrator are `<batch_id>:<user_gid>` — the colon is
fine on POSIX but illegal in NTFS path components, breaking the worker on
Windows operators. Centralized here so any path-component derivation that
incorporates a granule_id (work dir, staged-output dir, tmp prefix, ...) goes
through one normalizer."""

from __future__ import annotations

import re

# Reserved chars on Windows (<>:"/\|?*) plus NUL (illegal everywhere) plus the
# POSIX-only `/`. Replacement with `_` preserves uniqueness because the source
# IDs are short and don't already use underscores adjacent to these chars.
_BAD = re.compile(r'[<>:"/\\|?*\x00]')


def safe_segment(value: str) -> str:
    """Replace any character that isn't a valid filename component byte. The
    return is stable: same input → same output, so cache lookups keyed on the
    derived segment stay consistent across worker restarts."""
    return _BAD.sub("_", value)
