"""Bundle reference: the `orch:<name>@<version>` identifier that addresses a
registered Bundle.

Lives in the bundle domain (not `protocol.py`): the wire DTOs carry the ref as
a plain `str` field — the *format* and its parser are Bundle-naming concerns,
shared verbatim by the Orchestrator (registry lookups), the Worker (cache dir
layout), and the batch-create handler."""

from __future__ import annotations

BUNDLE_REF_PREFIX = "orch:"


def format_bundle_ref(name: str, version: str) -> str:
    return f"{BUNDLE_REF_PREFIX}{name}@{version}"


def parse_bundle_ref(ref: str) -> tuple[str, str]:
    """Strict `orch:<name>@<version>` parser. Returns (name, version).
    Raises ValueError on any shape mismatch — wrap to HTTP 422 at API edges."""
    if not ref.startswith(BUNDLE_REF_PREFIX):
        raise ValueError(f"bundle ref must start with {BUNDLE_REF_PREFIX!r}, got {ref!r}")
    body = ref[len(BUNDLE_REF_PREFIX) :]
    if "@" not in body:
        raise ValueError(f"bundle ref missing '@<version>': {ref!r}")
    name, version = body.rsplit("@", 1)
    if not name or not version:
        raise ValueError(f"bundle ref name/version both required: {ref!r}")
    return name, version
