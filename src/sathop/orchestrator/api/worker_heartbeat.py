"""Worker heartbeat helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import WorkerHeartbeat
from sathop.shared.state_machine import LEASED_STATES

from ..db import Granule, Worker
from ..telemetry import WorkerTelemetry, update_worker


def apply_worker_heartbeat(w: Worker, req: WorkerHeartbeat, now: datetime) -> bool:
    """Ingest one heartbeat. Volatile display telemetry (cpu/disk/queues) goes to
    in-memory telemetry; the worker's LIVE applied concurrency is ground truth the
    UI compares against the override, so it lands on the DB row. Returns True when
    a live value changed, so the caller commits (no write on a steady heartbeat)."""
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
