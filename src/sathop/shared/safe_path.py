"""Path-traversal guards.

Two layers, used together:

  - `is_safe_name(s)` rejects strings containing path separators, parent
    refs, NULs, or absolute prefixes — applied at input boundaries
    (Pydantic validators on user-supplied DTO fields, bundle manifest
    parsers) so malicious payloads are refused with a clear 422.

  - `safe_join(base, segment)` resolves the combined path and verifies
    containment under `base` — defense in depth at I/O sites (worker
    download dest, shared-file write, storage put) so a bypass of the
    input layer can't escape the data root."""

from __future__ import annotations

from pathlib import Path

_UNSAFE_SUBSTRINGS = ("/", "\\", "..", "\x00")


def is_safe_name(name: str) -> bool:
    """True iff `name` is safe to use as a single path segment (no path
    separators, no parent traversal, no NULs, no absolute-path prefixes)."""
    if not name:
        return False
    if any(s in name for s in _UNSAFE_SUBSTRINGS):
        return False
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        return False
    return True


def safe_join(base: Path, segment: str) -> Path:
    """Combine `base` with `segment` and verify the result stays under
    `base.resolve()`. Raises ValueError on escape. Accepts multi-segment
    inputs (e.g. storage object keys with '/') as long as the final path
    is contained."""
    base_resolved = base.resolve()
    candidate = (base / segment).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ValueError(f"path segment escapes base: {segment!r}")
    return candidate
