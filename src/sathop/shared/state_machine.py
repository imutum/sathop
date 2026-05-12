from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class GranuleState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
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
        leased=True, in_flight=True, non_terminal=True, cancellable=True
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
    GranuleState.UPLOADED: StateSpec(non_terminal=True, active=True),
    GranuleState.ACKED: StateSpec(non_terminal=True),
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
WORKER_REPORTABLE_STATES = tuple(
    state.value for state, spec in STATE_TABLE.items() if spec.predecessor is not None
)
STATE_ORDER = tuple(
    state.value
    for state in (
        GranuleState.PENDING,
        GranuleState.QUEUED,
        GranuleState.DOWNLOADING,
        GranuleState.DOWNLOADED,
        GranuleState.PROCESSING,
        GranuleState.PROCESSED,
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
