"""Worker heartbeat helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import WorkerHeartbeat
from sathop.shared.state_machine import LEASED_STATES

from .. import db
from ..db import Granule, Worker
from ..telemetry import WorkerTelemetry, update_worker

# PG mode: cap how often a steady-state beat rewrites the whole Worker row.
# At N workers × every beat, that per-beat 15-column UPDATE + commit is the
# dominant PG write load (workers-table bloat + WAL). Persisting volatile
# telemetry only every _TELEMETRY_PERSIST_SEC (or on a material change) collapses
# it; last_seen still advances each persist, far inside acked_orphan_grace_sec
# (default 600s) so the orphan-acked sweep — which reads Worker.last_seen in PG
# mode — stays correct. The only cost is telemetry display lagging up to this.
_TELEMETRY_PERSIST_SEC = 45.0


def apply_worker_heartbeat(w: Worker, req: WorkerHeartbeat, now: datetime) -> bool:
    """Ingest one heartbeat. Volatile display telemetry (cpu/disk/queues) is kept
    off the SQLite hot path (in-memory) to avoid WAL write amplification; on
    Postgres (multi-process) it must be cross-process, so it lands on the Worker
    row instead — but only when something material changed or the row is due for a
    refresh (see _TELEMETRY_PERSIST_SEC), so a steady-state beat writes nothing.
    The worker's LIVE applied concurrency always lands on the row when it moves
    (UI compares it to the override). Returns True when the caller should commit."""
    if db.is_postgres():
        material = (
            w.live_download_concurrency != req.download_concurrency
            or w.live_process_concurrency != req.process_concurrency
            or w.paused != req.paused
        )
        due = w.last_seen is None or (now - w.last_seen).total_seconds() >= _TELEMETRY_PERSIST_SEC
        if not (material or due):
            return False  # steady-state beat — skip the row write + commit entirely
        w.last_seen = now
        w.disk_used_gb = req.disk_used_gb
        w.disk_total_gb = req.disk_total_gb
        w.cpu_percent = req.cpu_percent
        w.mem_percent = req.mem_percent
        w.monthly_egress_gb = req.monthly_egress_gb
        w.queue_pending_download = req.queue_pending_download or 0
        w.queue_downloading = req.queue_downloading
        w.queue_pending_processing = req.queue_pending_processing or 0
        w.queue_processing = req.queue_processing
        w.queue_pending_upload = req.queue_pending_upload or 0
        w.queue_uploading = req.queue_uploading
        w.paused = req.paused
        w.live_download_concurrency = req.download_concurrency
        w.live_process_concurrency = req.process_concurrency
        return True  # telemetry changed every beat → always persist
    update_worker(
        w.worker_id,
        WorkerTelemetry(
            last_seen=now,
            disk_used_gb=req.disk_used_gb,
            disk_total_gb=req.disk_total_gb,
            cpu_percent=req.cpu_percent,
            mem_percent=req.mem_percent,
            monthly_egress_gb=req.monthly_egress_gb,
            queue_pending_download=req.queue_pending_download or 0,
            queue_downloading=req.queue_downloading,
            queue_pending_processing=req.queue_pending_processing or 0,
            queue_processing=req.queue_processing,
            queue_pending_upload=req.queue_pending_upload or 0,
            queue_uploading=req.queue_uploading,
            paused=req.paused,
        ),
    )
    changed = (
        w.live_download_concurrency != req.download_concurrency
        or w.live_process_concurrency != req.process_concurrency
    )
    if changed:
        w.live_download_concurrency = req.download_concurrency
        w.live_process_concurrency = req.process_concurrency
    return changed


async def revoked_active_granules(s: AsyncSession, req: WorkerHeartbeat) -> list[str]:
    if not req.active_granule_ids:
        return []
    still_owned = (
        (
            await s.execute(
                select(Granule.granule_id)
                .where(Granule.granule_id.in_(req.active_granule_ids))
                .where(Granule.leased_by == req.worker_id)
                .where(Granule.state.in_(LEASED_STATES))
            )
        )
        .scalars()
        .all()
    )
    owned_set = set(still_owned)
    return [gid for gid in req.active_granule_ids if gid not in owned_set]
