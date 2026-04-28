"""Event feed for Web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import require_token
from ..db import Event, Granule, Receiver, Worker, session

router = APIRouter(tags=["observability"], dependencies=[Depends(require_token)])


@router.get("/events")
async def recent_events(
    limit: int = Query(100, ge=1, le=1000),
    since_id: int = 0,
    before_id: int | None = Query(default=None, description="Page backward: only events with id < before_id"),
    batch_id: str | None = Query(default=None, description="Filter to events tied to this batch"),
    granule_id: str | None = Query(default=None),
    source: str | None = Query(
        default=None,
        description="Exact match on Event.source — typically a worker_id / receiver_id, "
        "or 'orchestrator'/'scheduler'/'admin'. Powers the per-node event drill-down.",
    ),
    level: str | None = Query(default=None, description="'warn' or 'error' to narrow"),
    s: AsyncSession = Depends(session),
) -> list[dict]:
    # Outer-join to Granule so events carry their batch_id — lets the UI
    # link granule_id cells straight to /batches/:batchId. Events without a
    # granule (orchestrator-level log lines) get batch_id=null.
    stmt = (
        select(Event, Granule.batch_id)
        .join(Granule, Event.granule_id == Granule.granule_id, isouter=True)
        .where(Event.id > since_id)
    )
    if before_id is not None:
        stmt = stmt.where(Event.id < before_id)
    if batch_id is not None:
        # Events tie to a batch via their granule's batch_id. Batch-level
        # events without a granule (create/bulk-cancel) live on the global
        # Events page instead — they're rare and noisy to disambiguate reliably.
        stmt = stmt.where(Granule.batch_id == batch_id)
    if granule_id is not None:
        stmt = stmt.where(Event.granule_id == granule_id)
    if source is not None:
        stmt = stmt.where(Event.source == source)
    if level is not None:
        stmt = stmt.where(Event.level == level)
    stmt = stmt.order_by(Event.id.desc()).limit(limit)
    rows = (await s.execute(stmt)).all()
    return [
        {
            "id": e.id,
            "ts": e.ts.isoformat(),
            "level": e.level,
            "source": e.source,
            "granule_id": e.granule_id,
            "batch_id": b_id,
            "message": e.message,
        }
        for e, b_id in rows
    ]


@router.get("/workers")
async def list_workers(s: AsyncSession = Depends(session)) -> list[dict]:
    rows = (await s.execute(select(Worker))).scalars().all()
    return [
        {
            "worker_id": w.worker_id,
            "version": w.version,
            "capacity": w.capacity,
            "public_url": w.public_url,
            "last_seen": w.last_seen.isoformat(),
            "disk_used_gb": w.disk_used_gb,
            "disk_total_gb": w.disk_total_gb,
            "cpu_percent": w.cpu_percent,
            "mem_percent": w.mem_percent,
            "monthly_egress_gb": w.monthly_egress_gb,
            "queue_queued": w.queue_queued or 0,
            "queue_downloading": w.queue_downloading,
            "queue_processing": w.queue_processing,
            "queue_uploading": w.queue_uploading,
            "enabled": w.enabled,
            "paused": w.paused,
            "desired_capacity": w.desired_capacity,
        }
        for w in rows
    ]


@router.get("/receivers")
async def list_receivers(s: AsyncSession = Depends(session)) -> list[dict]:
    rows = (await s.execute(select(Receiver))).scalars().all()
    return [
        {
            "receiver_id": r.receiver_id,
            "version": r.version,
            "platform": r.platform,
            "last_seen": r.last_seen.isoformat(),
            "disk_free_gb": r.disk_free_gb,
            "enabled": r.enabled,
            "queue_pulling": r.queue_pulling or 0,
            "recent_pull_bps": r.recent_pull_bps or 0,
        }
        for r in rows
    ]
