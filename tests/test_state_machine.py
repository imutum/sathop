from __future__ import annotations

import ast
import re
from pathlib import Path

from sathop.shared.state_machine import (
    ACTIVE_STATES,
    CANCELLABLE_STATES,
    IN_FLIGHT_STATES,
    LEASED_STATES,
    NON_TERMINAL_STATES,
    RETRYABLE_STATES,
    STAGE_BY_CLOSER,
    STATE_ORDER,
    STATE_PREDECESSOR,
    WORKER_REPORTABLE_STATES,
    GranuleState,
)


def _frontend_array(root: Path, name: str) -> list[str]:
    src = (root / "frontend" / "src" / "apiTypes.ts").read_text(encoding="utf-8")
    match = re.search(rf"export const {name}: GranuleState\[\] = \[(.*?)\];", src, re.S)
    assert match is not None
    values: list[str] = []
    for line in match.group(1).splitlines():
        text = line.strip().rstrip(",")
        if not text or text.startswith("//"):
            continue
        if text.startswith("..."):
            values.extend(_frontend_array(root, text.removeprefix("...")))
        else:
            values.append(ast.literal_eval(text))
    return values


def test_state_table_preserves_existing_backend_sets():
    assert LEASED_STATES == ("queued", "downloading", "downloaded", "processing", "processed")
    assert IN_FLIGHT_STATES == ("pending", *LEASED_STATES)
    assert NON_TERMINAL_STATES == (*IN_FLIGHT_STATES, "uploaded", "acked")
    assert ACTIVE_STATES == ("downloading", "downloaded", "processing", "processed", "uploaded")
    assert CANCELLABLE_STATES == set(IN_FLIGHT_STATES)
    assert RETRYABLE_STATES == {"failed", "blacklisted"}
    assert WORKER_REPORTABLE_STATES == ("downloading", "downloaded", "processing", "processed")


def test_worker_reportable_state_rules_stay_declarative():
    assert STATE_PREDECESSOR == {
        "downloading": "queued",
        "downloaded": "downloading",
        "processing": "downloaded",
        "processed": "processing",
    }
    assert STAGE_BY_CLOSER == {
        "downloading": "download_wait",
        "downloaded": "download",
        "processing": "process_wait",
        "processed": "process",
    }


def test_state_order_and_enum_values_are_stable():
    assert [state.value for state in GranuleState] == [
        "pending",
        "queued",
        "downloading",
        "downloaded",
        "processing",
        "processed",
        "uploaded",
        "acked",
        "deleted",
        "failed",
        "blacklisted",
    ]
    assert STATE_ORDER == (
        "pending",
        "queued",
        "downloading",
        "downloaded",
        "processing",
        "processed",
        "uploaded",
        "acked",
        "deleted",
    )


def test_frontend_state_constants_match_backend_constants(project_root: Path):
    assert _frontend_array(project_root, "IN_FLIGHT_STATES") == list(IN_FLIGHT_STATES)
    assert _frontend_array(project_root, "STATE_ORDER") == list(STATE_ORDER)
