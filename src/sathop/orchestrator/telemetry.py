"""In-memory telemetry for workers and receivers.

Heartbeat telemetry (cpu, disk, queues) is ephemeral display data — writing it
to SQLite on every heartbeat was the primary source of WAL write amplification
(~0.4 commits/sec per worker, each dirtying 13 ORM columns).  This module keeps
telemetry in RAM.  Workers/receivers re-report within one heartbeat interval
after an orchestrator restart; DB columns serve as stale fallback until then.
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
    """Telemetry dict for one worker: in-memory if available, DB row as fallback."""
    src = _workers.get(w.worker_id) or w
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


def _clear() -> None:
    _workers.clear()
    _receivers.clear()


def receiver_snapshot(r: Receiver) -> dict:
    """Telemetry dict for one receiver: in-memory if available, DB row as fallback."""
    src = _receivers.get(r.receiver_id) or r
    d = {f: getattr(src, f) for f in _RECEIVER_TELEM_FIELDS}
    d["last_seen"] = d["last_seen"].isoformat()
    d["queue_pulling"] = d["queue_pulling"] or 0
    d["recent_pull_bps"] = d["recent_pull_bps"] or 0
    return d
