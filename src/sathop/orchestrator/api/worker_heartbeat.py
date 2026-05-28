"""Worker heartbeat helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import WorkerHeartbeat
from sathop.shared.state_machine import LEASED_STATES

from ..db import Granule
from ..telemetry import WorkerTelemetry, update_worker


def apply_worker_heartbeat(worker_id: str, req: WorkerHeartbeat, now: datetime) -> None:
    update_worker(
        worker_id,
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
