from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class GranuleState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    ACKED = "acked"
    DELETED = "deleted"
    FAILED = "failed"
    BLACKLISTED = "blacklisted"


@dataclass(frozen=True)
class StateSpec:
    leased: bool = False
    in_flight: bool = False
    non_terminal: bool = False
    active: bool = False
    cancellable: bool = False
    retryable: bool = False
    predecessor: GranuleState | None = None
    closes_stage: str | None = None


STATE_TABLE: dict[GranuleState, StateSpec] = {
    GranuleState.PENDING: StateSpec(in_flight=True, non_terminal=True, cancellable=True),
    GranuleState.QUEUED: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        cancellable=True,
        predecessor=GranuleState.PENDING,
    ),
    GranuleState.DOWNLOADING: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        active=True,
        cancellable=True,
        predecessor=GranuleState.QUEUED,
        closes_stage="download_wait",
    ),
    GranuleState.DOWNLOADED: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        active=True,
        cancellable=True,
        predecessor=GranuleState.DOWNLOADING,
        closes_stage="download",
    ),
    GranuleState.PROCESSING: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        active=True,
        cancellable=True,
        predecessor=GranuleState.DOWNLOADED,
        closes_stage="process_wait",
    ),
    GranuleState.PROCESSED: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        active=True,
        cancellable=True,
        predecessor=GranuleState.PROCESSING,
        closes_stage="process",
    ),
    GranuleState.UPLOADING: StateSpec(
        leased=True,
        in_flight=True,
        non_terminal=True,
        active=True,
        cancellable=True,
        predecessor=GranuleState.PROCESSED,
        closes_stage="upload_wait",
    ),
    GranuleState.UPLOADED: StateSpec(
        non_terminal=True,
        active=True,
        predecessor=GranuleState.UPLOADING,
        closes_stage="upload",
    ),
    GranuleState.ACKED: StateSpec(non_terminal=True, closes_stage="deliver"),
    GranuleState.DELETED: StateSpec(),
    GranuleState.FAILED: StateSpec(retryable=True),
    GranuleState.BLACKLISTED: StateSpec(retryable=True),
}


def _values_where(predicate: Callable[[StateSpec], bool]) -> tuple[str, ...]:
    return tuple(state.value for state in GranuleState if predicate(STATE_TABLE[state]))


LEASED_STATES = _values_where(lambda spec: spec.leased)
IN_FLIGHT_STATES = _values_where(lambda spec: spec.in_flight)
NON_TERMINAL_STATES = _values_where(lambda spec: spec.non_terminal)
ACTIVE_STATES = _values_where(lambda spec: spec.active)
CANCELLABLE_STATES = set(_values_where(lambda spec: spec.cancellable))
RETRYABLE_STATES = set(_values_where(lambda spec: spec.retryable))
STATE_ORDER = tuple(
    state.value
    for state in (
        GranuleState.PENDING,
        GranuleState.QUEUED,
        GranuleState.DOWNLOADING,
        GranuleState.DOWNLOADED,
        GranuleState.PROCESSING,
        GranuleState.PROCESSED,
        GranuleState.UPLOADING,
        GranuleState.UPLOADED,
        GranuleState.ACKED,
        GranuleState.DELETED,
    )
)
STATE_PREDECESSOR = {
    state.value: spec.predecessor.value for state, spec in STATE_TABLE.items() if spec.predecessor is not None
}
STAGE_BY_CLOSER = {
    state.value: spec.closes_stage for state, spec in STATE_TABLE.items() if spec.closes_stage is not None
}


# ─── Events ────────────────────────────────────────────────────────────────
# Discriminated-union DTOs that ride POST /workers/events. Each event maps to
# exactly one Transition. Kept here (not in protocol.py) so the apply() pure
# function can pattern-match without crossing module boundaries.


class _EventBase(BaseModel):
    granule_id: str
    worker_id: str


class DownloadStarted(_EventBase):
    kind: Literal["download_started"] = "download_started"


class DownloadFinished(_EventBase):
    kind: Literal["download_finished"] = "download_finished"


class ProcessStarted(_EventBase):
    kind: Literal["process_started"] = "process_started"
    # Collapsed 3-event path: worker-measured fetch duration, so the orchestrator
    # records an accurate `download` stage row without a separate DownloadFinished
    # round-trip. None ⇒ legacy 6-event worker (download timed from state residence).
    download_ms: int | None = None


class ProcessFinished(_EventBase):
    kind: Literal["process_finished"] = "process_finished"


class UploadStarted(_EventBase):
    kind: Literal["upload_started"] = "upload_started"


class UploadedObject(BaseModel):
    object_key: str
    presigned_url: str
    sha256: str
    size: int


class UploadCompleted(_EventBase):
    kind: Literal["upload_completed"] = "upload_completed"
    objects: list[UploadedObject]
    # Collapsed 3-event path: worker-measured process duration, so the `process`
    # stage row stays accurate without the ProcessFinished / UploadStarted
    # round-trips. None ⇒ legacy 6-event worker (process timed from residence).
    process_ms: int | None = None


class ProcessingFailed(_EventBase):
    kind: Literal["processing_failed"] = "processing_failed"
    error: str
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    exit_code: int | None = None


class DeleteConfirmed(_EventBase):
    kind: Literal["delete_confirmed"] = "delete_confirmed"
    object_keys: list[str]


GranuleEvent = Annotated[
    DownloadStarted
    | DownloadFinished
    | ProcessStarted
    | ProcessFinished
    | UploadStarted
    | UploadCompleted
    | ProcessingFailed
    | DeleteConfirmed,
    Field(discriminator="kind"),
]


# ─── Internal events ──────────────────────────────────────────────────────
# Orch-only triggers — never deserialised from the wire (they would let a
# worker forge operator-only actions). apply() accepts them, but the
# POST /workers/events endpoint declares its body as `GranuleEvent`, which
# excludes these.


class ClaimByLease(BaseModel):
    """`/lease` claimed this granule. The lease_expires_at lives on the event
    because apply() can't compute it (orchestrator policy = now + 30min)."""

    granule_id: str
    worker_id: str
    lease_expires_at: datetime


class RevokedByOperator(BaseModel):
    """Operator clicked revoke-all on a worker — release this granule back to
    PENDING with retry_count++. Distinct from LeaseExpired (sweeper, no
    retry bump) and CancelGranule (operator, terminal BLACKLISTED)."""

    granule_id: str


class CancelGranule(BaseModel):
    """Operator cancelled this granule (batch cancel / per-granule cancel).
    Terminal — moves the granule to BLACKLISTED. retry_count is NOT bumped
    because the operator's intent is "stop, not retry."""

    granule_id: str


class RetryGranule(BaseModel):
    """Operator clicked retry on a failed / blacklisted granule. Clears retry
    state and returns it to PENDING for the next lease cycle."""

    granule_id: str


class RequeueGranule(BaseModel):
    """Operator re-queues an UPLOADED granule whose delivery is permanently stuck —
    its objects exhausted their pull retries (typically the hosting worker lost the
    output files on restart). Resets to PENDING for a full re-download/process/upload;
    the handler drops the dead object rows so the re-upload starts clean."""

    granule_id: str


class ObjectAcked(BaseModel):
    """All siblings of one of this granule's objects are now acked — the
    receiver-side handler decides the precondition, apply() does the
    UPLOADED → ACKED transition."""

    granule_id: str


class ReconcileOrphanDeleted(BaseModel):
    """Orchestrator backstop for the acked→deleted gap. An ACKED granule whose
    uploading worker is gone (removed / purged / restarted under a fresh id)
    never receives a worker DeleteConfirmed, so it strands in ACKED forever. The
    data already reached the receiver (ACKED ⟹ acked) and the worker's local copy
    left with it, so the orchestrator self-confirms the deletion — same terminal
    shape as DeleteConfirmed. Emitted only by the background orphan sweep; never
    deserialised from the wire."""

    granule_id: str


# Union of every event `apply()` handles — wire-format GranuleEvent plus the
# five orchestrator-internal triggers. `apply_transition()` types its `event`
# parameter against this so internal-event call sites (worker_leases.claim /
# revoke, receivers.ack, batches.cancel / retry) type-check without forcing
# them to import Annotated. Runtime is unaffected: apply() match-cases on the
# concrete class regardless of the static union.
AnyGranuleEvent = (
    GranuleEvent
    | ClaimByLease
    | RevokedByOperator
    | CancelGranule
    | RetryGranule
    | RequeueGranule
    | ObjectAcked
    | ReconcileOrphanDeleted
)


# Tail caps applied by apply() — matches old mark_failed semantics so a
# misbehaving worker can't write multi-MB rows.
_ERROR_CAP = 2000
_TAIL_CAP = 16000


# ─── Transition machinery ─────────────────────────────────────────────────


@dataclass(frozen=True)
class StageRow:
    stage: str
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class ObjectRow:
    worker_id: str
    object_key: str
    presigned_url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class GranuleSnapshot:
    """The subset of granule state apply() needs to decide a transition.
    Built by the orch-side runner from the ORM row."""

    state: GranuleState
    updated_at: datetime
    retry_count: int = 0


class Scope(str, Enum):
    """SSE channel taxonomy. Every state-changing handler picks one (or several)
    when it commits; the frontend's TanStack-Query invalidator subscribes to
    matching scopes. Declared next to `TransitionResult` because that's where
    the state machine names its UI consequence; orchestrator handlers import
    from here too."""

    BATCHES = "batches"
    WORKERS = "workers"
    RECEIVERS = "receivers"
    BUNDLES = "bundles"
    SHARED = "shared"
    EVENTS = "events"
    ROLLOUT = "rollout"


@dataclass(frozen=True)
class TransitionResult:
    """What one applied event produces. Scope is strict: DB state mutations
    only — no logs, no metrics, no out-of-band side-effects. See ADR-0002."""

    new_state: GranuleState
    fields: dict[str, object] = field(default_factory=dict)
    stage_rows: tuple[StageRow, ...] = ()
    new_objects: tuple[ObjectRow, ...] = ()
    # When set, the runner marks every GranuleObject for this granule with
    # deleted_at=<this datetime>. Only emitted by DeleteConfirmed.
    objects_deleted_at: datetime | None = None
    publish_scope: Scope | None = Scope.BATCHES


class StateConflict(Exception):
    """Raised by apply() when an event is not valid against the current state.
    Orchestrator handler translates to HTTP 409."""


def _stage_row_closing(snap: GranuleSnapshot, target: GranuleState, now: datetime) -> StageRow | None:
    closer = STATE_TABLE[target].closes_stage
    if closer is None:
        return None
    return StageRow(stage=closer, started_at=snap.updated_at, finished_at=now)


def _require_predecessor(snap: GranuleSnapshot, target: GranuleState) -> None:
    expected = STATE_TABLE[target].predecessor
    if expected is None or snap.state != expected:
        raise StateConflict(f"cannot transition {snap.state.value!r} → {target.value!r}")


def _forward_stage_transition(snap: GranuleSnapshot, target: GranuleState, now: datetime) -> TransitionResult:
    """Shared shape for the legacy single-step stage events: predecessor check +
    state bump + one closing stage row."""
    _require_predecessor(snap, target)
    stage = _stage_row_closing(snap, target, now)
    return TransitionResult(
        new_state=target,
        fields={"updated_at": now},
        stage_rows=(stage,) if stage is not None else (),
    )


def _measured_stage(stage: str, duration_ms: int, now: datetime) -> StageRow:
    """Stage row from a worker-reported duration (collapsed 3-event path).
    started_at is back-dated from `now` so duration_ms is exact and the timeline
    view stays roughly aligned with wall-clock."""
    return StageRow(
        stage=stage,
        started_at=now - timedelta(milliseconds=max(0, duration_ms)),
        finished_at=now,
    )


def _enter_processing(snap: GranuleSnapshot, ev: ProcessStarted, now: datetime) -> TransitionResult:
    """ProcessStarted accepts two predecessors so a rolling upgrade never strands
    a granule:
      DOWNLOADING — collapsed 3-event worker skipped the DOWNLOADED hop; the
        worker-measured ``download_ms`` is the authoritative `download` duration.
      DOWNLOADED — legacy 6-event worker; close `process_wait` from residence.
    """
    if snap.state == GranuleState.DOWNLOADING:
        stage = (
            _measured_stage("download", ev.download_ms, now)
            if ev.download_ms is not None
            else StageRow(stage="download", started_at=snap.updated_at, finished_at=now)
        )
    elif snap.state == GranuleState.DOWNLOADED:
        stage = StageRow(stage="process_wait", started_at=snap.updated_at, finished_at=now)
    else:
        raise StateConflict(f"cannot transition {snap.state.value!r} → 'processing'")
    return TransitionResult(
        new_state=GranuleState.PROCESSING,
        fields={"updated_at": now},
        stage_rows=(stage,),
    )


def _complete_upload(snap: GranuleSnapshot, ev: UploadCompleted, now: datetime) -> TransitionResult:
    """UploadCompleted accepts two predecessors (rolling-upgrade safe):
      PROCESSING — collapsed 3-event worker; worker-measured ``process_ms`` is the
        `process` stage (the sub-second upload is folded in, not separately timed).
      UPLOADING — legacy 6-event worker; close `upload` from residence.
    Clears lease + stale failure tails and inserts the uploaded object rows in
    either case.
    """
    if snap.state == GranuleState.PROCESSING:
        stage = (
            _measured_stage("process", ev.process_ms, now)
            if ev.process_ms is not None
            else StageRow(stage="process", started_at=snap.updated_at, finished_at=now)
        )
    elif snap.state == GranuleState.UPLOADING:
        stage = StageRow(stage="upload", started_at=snap.updated_at, finished_at=now)
    else:
        raise StateConflict(f"cannot transition {snap.state.value!r} → 'uploaded'")
    return TransitionResult(
        new_state=GranuleState.UPLOADED,
        fields={
            "leased_by": None,
            "lease_expires_at": None,
            "error": None,
            "stdout_tail": None,
            "stderr_tail": None,
            "updated_at": now,
        },
        stage_rows=(stage,),
        new_objects=tuple(
            ObjectRow(
                worker_id=ev.worker_id,
                object_key=o.object_key,
                presigned_url=o.presigned_url,
                sha256=o.sha256,
                size=o.size,
            )
            for o in ev.objects
        ),
    )


def apply(
    snap: GranuleSnapshot,
    event: object,
    *,
    now: datetime,
    max_retries: int,
) -> TransitionResult:
    """Pure transition function. Inputs are values; output is a description of
    every DB mutation the orchestrator should make. The caller (runner) holds
    the AsyncSession; apply() never sees one."""
    match event:
        case DownloadStarted():
            return _forward_stage_transition(snap, GranuleState.DOWNLOADING, now)
        case DownloadFinished():
            return _forward_stage_transition(snap, GranuleState.DOWNLOADED, now)
        case ProcessStarted() as ev:
            # Collapsed (downloading→processing) or legacy (downloaded→processing).
            return _enter_processing(snap, ev, now)
        case ProcessFinished():
            return _forward_stage_transition(snap, GranuleState.PROCESSED, now)
        case UploadStarted():
            return _forward_stage_transition(snap, GranuleState.UPLOADING, now)
        case UploadCompleted() as ev:
            # Collapsed (processing→uploaded) or legacy (uploading→uploaded).
            return _complete_upload(snap, ev, now)
        case ProcessingFailed(error=error, stdout_tail=stdout_tail, stderr_tail=stderr_tail):
            if snap.state.value not in LEASED_STATES:
                raise StateConflict(f"failure not accepted in state {snap.state.value!r} (lease was revoked)")
            new_retry = snap.retry_count + 1
            new_state = GranuleState.BLACKLISTED if new_retry >= max_retries else GranuleState.PENDING
            fields: dict[str, object] = {
                "retry_count": new_retry,
                "error": error[:_ERROR_CAP],
                "leased_by": None,
                "lease_expires_at": None,
                "updated_at": now,
            }
            if stdout_tail is not None:
                fields["stdout_tail"] = stdout_tail[:_TAIL_CAP]
            if stderr_tail is not None:
                fields["stderr_tail"] = stderr_tail[:_TAIL_CAP]
            return TransitionResult(new_state=new_state, fields=fields)
        case DeleteConfirmed():
            return TransitionResult(
                new_state=GranuleState.DELETED,
                fields={"updated_at": now},
                objects_deleted_at=now,
            )
        case ClaimByLease() as ev:
            _require_predecessor(snap, GranuleState.QUEUED)
            return TransitionResult(
                new_state=GranuleState.QUEUED,
                fields={
                    "leased_by": ev.worker_id,
                    "lease_expires_at": ev.lease_expires_at,
                    "updated_at": now,
                },
                # /lease publishes scope itself after the loop; per-row publish
                # would fan out N times.
                publish_scope=None,
            )
        case RevokedByOperator():
            if snap.state.value not in LEASED_STATES:
                raise StateConflict(f"revoke not accepted in state {snap.state.value!r}")
            return TransitionResult(
                new_state=GranuleState.PENDING,
                fields={
                    "leased_by": None,
                    "lease_expires_at": None,
                    "retry_count": snap.retry_count + 1,
                    "updated_at": now,
                },
                publish_scope=None,
            )
        case CancelGranule():
            if snap.state.value not in CANCELLABLE_STATES:
                raise StateConflict(f"cancel not accepted in state {snap.state.value!r}")
            return TransitionResult(
                new_state=GranuleState.BLACKLISTED,
                fields={
                    "leased_by": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                },
            )
        case RetryGranule():
            if snap.state.value not in RETRYABLE_STATES:
                raise StateConflict(f"retry not accepted in state {snap.state.value!r}")
            return TransitionResult(
                new_state=GranuleState.PENDING,
                fields={
                    "retry_count": 0,
                    "error": None,
                    "leased_by": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                },
            )
        case RequeueGranule():
            if snap.state != GranuleState.UPLOADED:
                raise StateConflict(f"requeue not accepted in state {snap.state.value!r}")
            # Object rows are dropped by the handler (objects_deleted_at is wired to
            # the DELETE path + delivered counter, so it must not be reused here).
            return TransitionResult(
                new_state=GranuleState.PENDING,
                fields={
                    "retry_count": 0,
                    "error": None,
                    "leased_by": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                },
            )
        case ObjectAcked():
            if snap.state != GranuleState.UPLOADED:
                raise StateConflict(f"object-ack not accepted in state {snap.state.value!r}")
            # Close the `deliver` stage: started when the granule entered
            # UPLOADED (snap.updated_at), finished now. Duration = how long the
            # product waited for the receiver — the receiver-bottleneck signal,
            # and the rate source for delivery throughput / ETA.
            stage = _stage_row_closing(snap, GranuleState.ACKED, now)
            return TransitionResult(
                new_state=GranuleState.ACKED,
                fields={"updated_at": now},
                stage_rows=(stage,) if stage is not None else (),
            )
        case ReconcileOrphanDeleted():
            # Orchestrator self-confirm of an orphaned ACKED granule. Guarded to
            # ACKED so a concurrent worker DeleteConfirmed that already moved it to
            # DELETED makes this a skip (on_conflict="skip" at the call site). Same
            # terminal shape as DeleteConfirmed — objects_deleted_at routes it
            # through the rowcount-gated delete path, counted exactly once.
            if snap.state != GranuleState.ACKED:
                raise StateConflict(f"orphan-reconcile not accepted in state {snap.state.value!r}")
            return TransitionResult(
                new_state=GranuleState.DELETED,
                fields={"updated_at": now},
                objects_deleted_at=now,
            )
        case _:
            raise StateConflict(f"unknown event: {type(event).__name__}")
