"""Worker runtime helper pure functions — called per granule, no infra needed."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sathop.shared.protocol import Credential
from sathop.worker.runtime_helpers import (
    PROCESS_OUTPUT_TAIL_CHARS,
    PROCESSING_FAILURE_TAIL_CHARS,
    WORKER_TRACEBACK_TAIL_CHARS,
    auth_for,
    download_progress_detail,
    processing_failure_message,
    render_key,
    tail_or_none,
    traceback_tail,
)

# ─── auth_for ──────────────────────────────────────────────────────────────


def _cred(name: str = "edl", scheme: str = "bearer", token: str = "t") -> Credential:
    return Credential(name=name, scheme=scheme, token=token)  # type: ignore[arg-type]


def test_auth_for_returns_none_when_name_missing(caplog):
    """No credential requested → returns None without warning."""
    caplog.set_level(logging.WARNING)
    assert auth_for({}, None, "g1", logging.getLogger()) is None
    assert auth_for({"edl": _cred()}, None, "g1", logging.getLogger()) is None
    assert caplog.records == []


def test_auth_for_returns_credential_when_present():
    c = _cred("edl")
    assert auth_for({"edl": c}, "edl", "g1", logging.getLogger()) is c


def test_auth_for_returns_none_with_warning_when_missing(caplog):
    """Bundle requested a name the batch didn't carry → warn (so an operator
    can see why the download will fail auth) but don't raise."""
    caplog.set_level(logging.WARNING)
    log = logging.getLogger("test_auth_for")
    assert auth_for({}, "missing", "granule-xyz", log) is None
    assert any(
        "granule-xyz" in rec.getMessage() and "'missing'" in rec.getMessage() for rec in caplog.records
    )


def test_auth_for_returns_none_with_warning_when_other_creds_present(caplog):
    """A non-matching name set in creds still triggers the missing-name warning."""
    caplog.set_level(logging.WARNING)
    log = logging.getLogger("test_auth_for")
    assert auth_for({"other": _cred("other")}, "edl", "g1", log) is None
    assert any("'edl'" in rec.getMessage() for rec in caplog.records)


# ─── processing_failure_message ────────────────────────────────────────────


def test_processing_failure_message_empty_replaced_with_placeholder():
    assert processing_failure_message("") == "no output"


def test_processing_failure_message_passes_through_small_text():
    assert processing_failure_message("boom") == "boom"


def test_processing_failure_message_tails_long_text():
    big = "x" * (PROCESSING_FAILURE_TAIL_CHARS + 100)
    out = processing_failure_message(big)
    assert len(out) == PROCESSING_FAILURE_TAIL_CHARS
    assert out == big[-PROCESSING_FAILURE_TAIL_CHARS:]


def test_processing_failure_message_keeps_tail_visible():
    """Tail is what an operator scans for — confirm the tail end is preserved."""
    body = "head" + "x" * PROCESSING_FAILURE_TAIL_CHARS + "TAIL_MARKER"
    out = processing_failure_message(body)
    assert out.endswith("TAIL_MARKER")


# ─── tail_or_none ──────────────────────────────────────────────────────────


def test_tail_or_none_returns_none_for_empty():
    assert tail_or_none("", 100) is None


def test_tail_or_none_returns_full_when_under_cap():
    assert tail_or_none("short", 100) == "short"


def test_tail_or_none_trims_to_tail():
    assert tail_or_none("0123456789", 4) == "6789"


def test_tail_or_none_boundary_exact_size():
    """len == n is not truncated."""
    assert tail_or_none("abcd", 4) == "abcd"


# ─── traceback_tail ────────────────────────────────────────────────────────


def test_traceback_tail_contains_exception_message():
    try:
        raise RuntimeError("boom-msg")
    except RuntimeError as e:
        out = traceback_tail(e)
    assert "boom-msg" in out
    assert "RuntimeError" in out


def test_traceback_tail_caps_length():
    """A deeply nested exception's traceback is capped to WORKER_TRACEBACK_TAIL_CHARS."""

    def recurse(n: int) -> None:
        if n == 0:
            raise RuntimeError("deep")
        recurse(n - 1)

    try:
        recurse(500)
    except RuntimeError as e:
        out = traceback_tail(e)
    assert len(out) <= WORKER_TRACEBACK_TAIL_CHARS


# ─── download_progress_detail ──────────────────────────────────────────────


def test_download_progress_detail_with_known_total():
    assert download_progress_detail(5_000_000, 10_000_000) == "5.0/10.0 MB"


def test_download_progress_detail_with_zero_total():
    """total=0 is falsy → treated as unknown total."""
    assert download_progress_detail(2_000_000, 0) == "2.0 MB"


def test_download_progress_detail_with_none_total():
    assert download_progress_detail(2_000_000, None) == "2.0 MB"


def test_download_progress_detail_rounds_to_one_decimal():
    assert download_progress_detail(1_234_567, 10_000_000) == "1.2/10.0 MB"


def test_download_progress_detail_zero_bytes():
    assert download_progress_detail(0, 10_000_000) == "0.0/10.0 MB"


# ─── render_key ────────────────────────────────────────────────────────────


def test_render_key_basic_stem_ext_name():
    p = Path("/tmp/MOD09A1.A2024.tif")
    assert render_key("{stem}{ext}", p, {}) == "MOD09A1.A2024.tif"
    assert render_key("{name}", p, {}) == "MOD09A1.A2024.tif"
    assert render_key("{stem}", p, {}) == "MOD09A1.A2024"
    assert render_key("{ext}", p, {}) == ".tif"


def test_render_key_with_meta_fields():
    p = Path("/tmp/out.tif")
    assert render_key("y{year}/{stem}{ext}", p, {"year": 2024}) == "y2024/out.tif"


def test_render_key_meta_values_stringified():
    """Non-string meta values are str()-coerced (granule_id may be int internally)."""
    p = Path("/tmp/out.tif")
    assert render_key("{gid}/{stem}", p, {"gid": 42}) == "42/out"


def test_render_key_falls_back_to_name_on_missing_placeholder():
    """An unknown {placeholder} → fall back to bare filename rather than crash."""
    p = Path("/tmp/out.tif")
    assert render_key("{nope}/{stem}", p, {}) == "out.tif"


def test_render_key_user_meta_overrides_built_in():
    """If `meta` provides `stem`, it wins over the auto-derived one. Documents
    the actual behaviour — built-ins are seeded first and overwritten by **meta."""
    p = Path("/tmp/out.tif")
    assert render_key("{stem}{ext}", p, {"stem": "user"}) == "user.tif"


# ─── constants exist + have plausible values ───────────────────────────────


def test_tail_constants_are_positive():
    assert PROCESSING_FAILURE_TAIL_CHARS > 0
    assert WORKER_TRACEBACK_TAIL_CHARS > 0
    assert PROCESS_OUTPUT_TAIL_CHARS > 0


def test_process_output_tail_larger_than_processing_failure_tail():
    """Worker keeps more output than the orchestrator persists — 4× headroom
    is the contract in M-023, regressions here matter for `_drain_to_cap`."""
    assert PROCESS_OUTPUT_TAIL_CHARS >= PROCESSING_FAILURE_TAIL_CHARS * 4
