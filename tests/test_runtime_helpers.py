"""Worker runtime helper pure functions — called per granule, no infra needed."""

from __future__ import annotations

import logging

from sathop.shared.protocol import Credential
from sathop.worker.runtime_helpers import (
    PROCESS_OUTPUT_TAIL_CHARS,
    PROCESSING_FAILURE_TAIL_CHARS,
    WORKER_TRACEBACK_TAIL_CHARS,
    auth_for,
    processing_failure_message,
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


# ─── constants exist + have plausible values ───────────────────────────────


def test_tail_constants_are_positive():
    assert PROCESSING_FAILURE_TAIL_CHARS > 0
    assert WORKER_TRACEBACK_TAIL_CHARS > 0
    assert PROCESS_OUTPUT_TAIL_CHARS > 0


def test_process_output_tail_larger_than_processing_failure_tail():
    """Worker keeps more output than the orchestrator persists — 4× headroom
    is the contract in M-023, regressions here matter for `_drain_to_cap`."""
    assert PROCESS_OUTPUT_TAIL_CHARS >= PROCESSING_FAILURE_TAIL_CHARS * 4
