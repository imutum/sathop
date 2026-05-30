"""Ephemeral worker/receiver telemetry (cpu, disk, queues, last_seen).

Heartbeat telemetry is display data plus the orphan-acked sweep's liveness
signal; writing it to SQLite on every beat was the main WAL write-amplifier, so
it lives off the state DB. Two backends behind one sync API:
  - **in-memory** dict (single-process default).
  - **Redis KV** (multi-process): one TTL'd key per node, so a worker beating to
    any uvicorn process is visible to the (single, leader) sweeper and to a UI
    request served by any process. DB columns remain the stale fallback until a
    node re-reports after a restart.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from . import redis_bus
from .db import Receiver, Worker

_log = logging.getLogger("sathop.orch.telemetry")

# Generous safety-net TTL refreshed on every beat; liveness within the sweep
# window is decided by last_seen, not by expiry. Truly-gone nodes that were
# never evict()'d lapse after a day.
_TTL = 86_400


def _r():
    return redis_bus.sync() if redis_bus.enabled() else None


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


def _wkey(worker_id: str) -> str:
    return f"sathop:tw:{worker_id}"


def _dump_worker(t: WorkerTelemetry) -> str:
    d = {f: getattr(t, f) for f in _WORKER_TELEM_FIELDS}
    d["last_seen"] = t.last_seen.isoformat()
    return json.dumps(d)


def _load_worker(s: str) -> WorkerTelemetry:
    d = json.loads(s)
    d["last_seen"] = datetime.fromisoformat(d["last_seen"])
    return WorkerTelemetry(**d)


def update_worker(worker_id: str, t: WorkerTelemetry) -> None:
    r = _r()
    if r is not None:
        # Best-effort: a Redis hiccup must not 500 the heartbeat (which would
        # stop lease renewal). DB columns are the stale fallback meanwhile.
        try:
            r.set(_wkey(worker_id), _dump_worker(t), ex=_TTL)
        except Exception:
            _log.warning("telemetry.update_worker: redis unavailable", exc_info=False)
        return
    _workers[worker_id] = t


def get_worker(worker_id: str) -> WorkerTelemetry | None:
    r = _r()
    if r is not None:
        try:
            raw = r.get(_wkey(worker_id))
            return _load_worker(raw) if raw else None
        except Exception:
            return None
    return _workers.get(worker_id)


def evict_worker(worker_id: str) -> None:
    r = _r()
    if r is not None:
        r.delete(_wkey(worker_id))
        return
    _workers.pop(worker_id, None)


def worker_snapshot(w: Worker) -> dict:
    """Telemetry dict for one worker: live telemetry if available, DB row fallback."""
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


def _rkey(receiver_id: str) -> str:
    return f"sathop:tr:{receiver_id}"


def _dump_receiver(t: ReceiverTelemetry) -> str:
    d = {f: getattr(t, f) for f in _RECEIVER_TELEM_FIELDS}
    d["last_seen"] = t.last_seen.isoformat()
    return json.dumps(d)


def _load_receiver(s: str) -> ReceiverTelemetry:
    d = json.loads(s)
    d["last_seen"] = datetime.fromisoformat(d["last_seen"])
    return ReceiverTelemetry(**d)


def update_receiver(receiver_id: str, t: ReceiverTelemetry) -> None:
    r = _r()
    if r is not None:
        try:
            r.set(_rkey(receiver_id), _dump_receiver(t), ex=_TTL)
        except Exception:
            _log.warning("telemetry.update_receiver: redis unavailable", exc_info=False)
        return
    _receivers[receiver_id] = t


def get_receiver(receiver_id: str) -> ReceiverTelemetry | None:
    r = _r()
    if r is not None:
        try:
            raw = r.get(_rkey(receiver_id))
            return _load_receiver(raw) if raw else None
        except Exception:
            return None
    return _receivers.get(receiver_id)


def evict_receiver(receiver_id: str) -> None:
    r = _r()
    if r is not None:
        r.delete(_rkey(receiver_id))
        return
    _receivers.pop(receiver_id, None)


def receiver_snapshot(r: Receiver) -> dict:
    """Telemetry dict for one receiver: live telemetry if available, DB row fallback."""
    src = get_receiver(r.receiver_id) or r
    d = {f: getattr(src, f) for f in _RECEIVER_TELEM_FIELDS}
    d["last_seen"] = d["last_seen"].isoformat()
    d["queue_pulling"] = d["queue_pulling"] or 0
    d["recent_pull_bps"] = d["recent_pull_bps"] or 0
    return d


def _clear() -> None:
    _workers.clear()
    _receivers.clear()
