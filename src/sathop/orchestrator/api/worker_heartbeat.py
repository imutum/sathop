"""Worker heartbeat helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import LEASED_STATES, WorkerHeartbeat

from ..db import Granule, Worker
from ..pubsub import log_event as log


async def record_worker_version(s: AsyncSession, worker: Worker, req: WorkerHeartbeat) -> None:
    if not req.version or req.version == worker.version:
        return
    await log(
        s,
        req.worker_id,
        f"worker version changed {worker.version!r} → {req.version!r} "
        "(if this keeps flipping, two containers likely share the worker_id)",
        level="warn",
    )
    worker.version = req.version


def apply_worker_heartbeat(worker: Worker, req: WorkerHeartbeat, now) -> None:
    worker.last_seen = now
    worker.disk_used_gb = req.disk_used_gb
    worker.disk_total_gb = req.disk_total_gb
    worker.cpu_percent = req.cpu_percent
    worker.mem_percent = req.mem_percent
    worker.monthly_egress_gb = req.monthly_egress_gb
    worker.queue_pending_download = req.queue_pending_download
    worker.queue_downloading = req.queue_downloading
    worker.queue_pending_processing = req.queue_pending_processing
    worker.queue_processing = req.queue_processing
    worker.queue_pending_upload = req.queue_pending_upload
    worker.queue_uploading = req.queue_uploading
    worker.paused = req.paused


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


async def consume_restart_signal(s: AsyncSession, worker: Worker) -> bool:
    requested = worker.restart_requested_at is not None
    if requested:
        worker.restart_requested_at = None
        await log(s, worker.worker_id, "restart signal delivered to worker")
    return requested


async def consume_gc_signal(s: AsyncSession, worker: Worker) -> bool:
    requested = worker.gc_requested_at is not None
    if requested:
        worker.gc_requested_at = None
        await log(s, worker.worker_id, "cache GC signal delivered to worker")
    return requested
