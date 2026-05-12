from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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
    CancelGranule,
    ClaimByLease,
    DeleteConfirmed,
    DownloadFinished,
    DownloadStarted,
    GranuleSnapshot,
    GranuleState,
    ObjectAcked,
    ProcessFinished,
    ProcessingFailed,
    ProcessStarted,
    RetryGranule,
    RevokedByOperator,
    StateConflict,
    UploadCompleted,
    UploadedObject,
    UploadStarted,
    apply,
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


def test_state_table_preserves_backend_sets():
    assert LEASED_STATES == (
        "queued",
        "downloading",
        "downloaded",
        "processing",
        "processed",
        "uploading",
    )
    assert IN_FLIGHT_STATES == ("pending", *LEASED_STATES)
    assert NON_TERMINAL_STATES == (*IN_FLIGHT_STATES, "uploaded", "acked")
    assert ACTIVE_STATES == (
        "downloading",
        "downloaded",
        "processing",
        "processed",
        "uploading",
        "uploaded",
    )
    assert CANCELLABLE_STATES == set(IN_FLIGHT_STATES)
    assert RETRYABLE_STATES == {"failed", "blacklisted"}


def test_state_predecessor_and_stage_closers_are_declarative():
    assert STATE_PREDECESSOR == {
        "queued": "pending",
        "downloading": "queued",
        "downloaded": "downloading",
        "processing": "downloaded",
        "processed": "processing",
        "uploading": "processed",
        "uploaded": "uploading",
    }
    assert STAGE_BY_CLOSER == {
        "downloading": "download_wait",
        "downloaded": "download",
        "processing": "process_wait",
        "processed": "process",
        "uploading": "upload_wait",
        "uploaded": "upload",
    }


def test_state_order_and_enum_values_are_stable():
    assert [state.value for state in GranuleState] == [
        "pending",
        "queued",
        "downloading",
        "downloaded",
        "processing",
        "processed",
        "uploading",
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
        "uploading",
        "uploaded",
        "acked",
        "deleted",
    )


def test_frontend_state_constants_match_backend_constants(project_root: Path):
    assert _frontend_array(project_root, "IN_FLIGHT_STATES") == list(IN_FLIGHT_STATES)
    assert _frontend_array(project_root, "STATE_ORDER") == list(STATE_ORDER)


# ─── apply() coverage ──────────────────────────────────────────────────────


_NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
_PREV = _NOW - timedelta(seconds=4)


def _snap(state: GranuleState, *, retry_count: int = 0) -> GranuleSnapshot:
    return GranuleSnapshot(state=state, updated_at=_PREV, retry_count=retry_count)


@pytest.mark.parametrize(
    ("event_cls", "from_state", "to_state", "stage"),
    [
        (DownloadStarted, GranuleState.QUEUED, GranuleState.DOWNLOADING, "download_wait"),
        (DownloadFinished, GranuleState.DOWNLOADING, GranuleState.DOWNLOADED, "download"),
        (ProcessStarted, GranuleState.DOWNLOADED, GranuleState.PROCESSING, "process_wait"),
        (ProcessFinished, GranuleState.PROCESSING, GranuleState.PROCESSED, "process"),
        (UploadStarted, GranuleState.PROCESSED, GranuleState.UPLOADING, "upload_wait"),
    ],
)
def test_stage_events_advance_and_close_one_stage(event_cls, from_state, to_state, stage):
    result = apply(
        _snap(from_state),
        event_cls(granule_id="g", worker_id="w"),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == to_state
    assert result.fields == {"updated_at": _NOW}
    assert [r.stage for r in result.stage_rows] == [stage]
    assert result.stage_rows[0].started_at == _PREV
    assert result.stage_rows[0].finished_at == _NOW


def test_upload_completed_inserts_objects_and_clears_lease_fields():
    obj = UploadedObject(object_key="out.tif", presigned_url="http://w/out.tif", sha256="0" * 64, size=42)
    result = apply(
        _snap(GranuleState.UPLOADING),
        UploadCompleted(granule_id="g", worker_id="w1", objects=[obj]),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.UPLOADED
    assert result.fields["leased_by"] is None
    assert result.fields["lease_expires_at"] is None
    assert result.fields["error"] is None
    assert result.fields["stdout_tail"] is None
    assert result.fields["stderr_tail"] is None
    assert [r.stage for r in result.stage_rows] == ["upload"]
    assert [o.worker_id for o in result.new_objects] == ["w1"]
    assert [o.object_key for o in result.new_objects] == ["out.tif"]


def test_stage_event_rejects_wrong_predecessor():
    with pytest.raises(StateConflict, match="downloading"):
        apply(
            _snap(GranuleState.PROCESSING),
            DownloadStarted(granule_id="g", worker_id="w"),
            now=_NOW,
            max_retries=3,
        )


def test_processing_failed_under_retry_cap_goes_pending():
    result = apply(
        _snap(GranuleState.PROCESSING, retry_count=1),
        ProcessingFailed(granule_id="g", worker_id="w", error="boom", exit_code=7),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.PENDING
    assert result.fields["retry_count"] == 2
    assert result.fields["error"] == "boom"
    assert result.fields["leased_by"] is None


def test_processing_failed_at_retry_cap_blacklists():
    result = apply(
        _snap(GranuleState.PROCESSING, retry_count=2),
        ProcessingFailed(granule_id="g", worker_id="w", error="boom", exit_code=7),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.BLACKLISTED
    assert result.fields["retry_count"] == 3


def test_processing_failed_rejects_outside_leased_states():
    with pytest.raises(StateConflict, match="lease was revoked"):
        apply(
            _snap(GranuleState.UPLOADED),
            ProcessingFailed(granule_id="g", worker_id="w", error="late", exit_code=None),
            now=_NOW,
            max_retries=3,
        )


def test_processing_failed_caps_long_tails():
    huge = "x" * 50_000
    result = apply(
        _snap(GranuleState.PROCESSING),
        ProcessingFailed(
            granule_id="g",
            worker_id="w",
            error="boom",
            stdout_tail=huge,
            stderr_tail=huge,
        ),
        now=_NOW,
        max_retries=3,
    )
    assert len(result.fields["stdout_tail"]) == 16000
    assert len(result.fields["stderr_tail"]) == 16000


def test_delete_confirmed_transitions_to_deleted_and_marks_objects():
    result = apply(
        _snap(GranuleState.UPLOADED),
        DeleteConfirmed(granule_id="g", worker_id="w", object_keys=["out.tif"]),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.DELETED
    assert result.objects_deleted_at == _NOW


# ─── internal events ──────────────────────────────────────────────────────


def test_claim_by_lease_pending_to_queued_with_lease_fields():
    expires = _NOW + timedelta(minutes=30)
    result = apply(
        _snap(GranuleState.PENDING),
        ClaimByLease(granule_id="g", worker_id="w1", lease_expires_at=expires),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.QUEUED
    assert result.fields["leased_by"] == "w1"
    assert result.fields["lease_expires_at"] == expires
    assert result.fields["updated_at"] == _NOW
    assert result.publish_scope is None  # caller publishes once after the bulk loop


def test_claim_by_lease_rejects_non_pending():
    with pytest.raises(StateConflict):
        apply(
            _snap(GranuleState.QUEUED),
            ClaimByLease(granule_id="g", worker_id="w1", lease_expires_at=_NOW),
            now=_NOW,
            max_retries=3,
        )


@pytest.mark.parametrize(
    "state",
    [
        GranuleState.QUEUED,
        GranuleState.DOWNLOADING,
        GranuleState.PROCESSING,
        GranuleState.UPLOADING,
    ],
)
def test_revoked_by_operator_releases_lease_and_bumps_retry(state):
    result = apply(
        _snap(state, retry_count=2),
        RevokedByOperator(granule_id="g"),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.PENDING
    assert result.fields["leased_by"] is None
    assert result.fields["lease_expires_at"] is None
    assert result.fields["retry_count"] == 3


def test_revoked_by_operator_rejects_unleased():
    with pytest.raises(StateConflict, match="revoke"):
        apply(
            _snap(GranuleState.UPLOADED),
            RevokedByOperator(granule_id="g"),
            now=_NOW,
            max_retries=3,
        )


@pytest.mark.parametrize("state", sorted(CANCELLABLE_STATES))
def test_cancel_granule_blacklists_from_any_cancellable_state(state):
    result = apply(
        _snap(GranuleState(state)),
        CancelGranule(granule_id="g"),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.BLACKLISTED
    assert result.fields["leased_by"] is None
    assert result.fields["lease_expires_at"] is None


def test_cancel_granule_rejects_non_cancellable():
    with pytest.raises(StateConflict, match="cancel"):
        apply(
            _snap(GranuleState.UPLOADED),
            CancelGranule(granule_id="g"),
            now=_NOW,
            max_retries=3,
        )


@pytest.mark.parametrize("state", [GranuleState.FAILED, GranuleState.BLACKLISTED])
def test_retry_granule_clears_state_and_returns_to_pending(state):
    result = apply(
        _snap(state, retry_count=5),
        RetryGranule(granule_id="g"),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.PENDING
    assert result.fields["retry_count"] == 0
    assert result.fields["error"] is None
    assert result.fields["leased_by"] is None


def test_retry_granule_rejects_non_retryable():
    with pytest.raises(StateConflict, match="retry"):
        apply(
            _snap(GranuleState.UPLOADED),
            RetryGranule(granule_id="g"),
            now=_NOW,
            max_retries=3,
        )


def test_object_acked_uploaded_to_acked():
    result = apply(
        _snap(GranuleState.UPLOADED),
        ObjectAcked(granule_id="g"),
        now=_NOW,
        max_retries=3,
    )
    assert result.new_state == GranuleState.ACKED


def test_object_acked_rejects_non_uploaded():
    with pytest.raises(StateConflict, match="object-ack"):
        apply(
            _snap(GranuleState.PROCESSED),
            ObjectAcked(granule_id="g"),
            now=_NOW,
            max_retries=3,
        )
