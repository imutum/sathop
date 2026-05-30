"""Ephemeral worker/receiver telemetry (cpu, disk, queues, last_seen).

Heartbeat telemetry is display data plus the orphan-acked sweep's liveness
signal. Two paths, by mode:
  - **SQLite (single-process)**: kept in these in-memory dicts — writing it to
    SQLite on every beat was the main WAL write-amplifier, so it stays off the
    state DB. ``*_snapshot`` reads it back, falling back to the (stale) DB row.
  - **Postgres (multi-process)**: the heartbeat handlers write telemetry onto
    the Worker/Receiver row instead (PG has no WAL-amplification cost and the
    value must be cross-process). These dicts then stay empty, so ``get_*``
    returns None and ``*_snapshot`` reads straight from the row — which is now
    fresh, not stale. The orphan sweep likewise reads liveness from the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import Receiver, Worker

# ── Worker ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class WorkerTelemetry:
    last_seen: datetime
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    monthly_egress_gb: float = 0.0
    queue_pending_download: int = 0
    queue_downloading: int = 0
    queue_pending_processing: int = 0
    queue_processing: int = 0
    queue_pending_upload: int = 0
    queue_uploading: int = 0
    paused: bool = False


_WORKER_TELEM_FIELDS = tuple(f.name for f in WorkerTelemetry.__dataclass_fields__.values())

_workers: dict[str, WorkerTelemetry] = {}


def update_worker(worker_id: str, t: WorkerTelemetry) -> None:
    _workers[worker_id] = t


def get_worker(worker_id: str) -> WorkerTelemetry | None:
    return _workers.get(worker_id)


def evict_worker(worker_id: str) -> None:
    _workers.pop(worker_id, None)


def worker_snapshot(w: Worker) -> dict:
    """Telemetry dict for one worker: live in-memory telemetry if present (SQLite),
    else the DB row (Postgres, where the heartbeat persists it on the row)."""
    src = get_worker(w.worker_id) or w
    d = {f: getattr(src, f) for f in _WORKER_TELEM_FIELDS}
    d["last_seen"] = d["last_seen"].isoformat()
    for f in ("queue_pending_download", "queue_pending_processing", "queue_pending_upload"):
        d[f] = d[f] or 0
    return d


# ── Receiver ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ReceiverTelemetry:
    last_seen: datetime
    disk_free_gb: float = 0.0
    queue_pulling: int = 0
    recent_pull_bps: int = 0


_RECEIVER_TELEM_FIELDS = tuple(f.name for f in ReceiverTelemetry.__dataclass_fields__.values())

_receivers: dict[str, ReceiverTelemetry] = {}


def update_receiver(receiver_id: str, t: ReceiverTelemetry) -> None:
    _receivers[receiver_id] = t


def get_receiver(receiver_id: str) -> ReceiverTelemetry | None:
    return _receivers.get(receiver_id)


def evict_receiver(receiver_id: str) -> None:
    _receivers.pop(receiver_id, None)


def receiver_snapshot(r: Receiver) -> dict:
    """Telemetry dict for one receiver: live in-memory telemetry if present
    (SQLite), else the DB row (Postgres, where the heartbeat persists it)."""
    src = get_receiver(r.receiver_id) or r
    d = {f: getattr(src, f) for f in _RECEIVER_TELEM_FIELDS}
    d["last_seen"] = d["last_seen"].isoformat()
    d["queue_pulling"] = d["queue_pulling"] or 0
    d["recent_pull_bps"] = d["recent_pull_bps"] or 0
    return d


def _clear() -> None:
    _workers.clear()
    _receivers.clear()
