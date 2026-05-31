"""Event feed for Web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db, event_store, telemetry
from ..config import require_token
from ..db import Receiver, Worker, session

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
    if db.is_postgres():
        return await event_store.query_db(
            s,
            limit=limit,
            since_id=since_id,
            before_id=before_id,
            batch_id=batch_id,
            granule_id=granule_id,
            source=source,
            level=level,
        )
    return event_store.query(
        limit=limit,
        since_id=since_id,
        before_id=before_id,
        batch_id=batch_id,
        granule_id=granule_id,
        source=source,
        level=level,
    )


@router.get("/workers")
async def list_workers(s: AsyncSession = Depends(session)) -> list[dict]:
    rows = (await s.execute(select(Worker))).scalars().all()
    result = []
    for w in rows:
        d = {
            "worker_id": w.worker_id,
            "version": w.version,
            "capacity": w.capacity,
            "public_url": w.public_url,
            "download_concurrency": w.download_concurrency,
            "process_concurrency": w.process_concurrency,
            "live_download_concurrency": w.live_download_concurrency,
            "live_process_concurrency": w.live_process_concurrency,
            "operator_paused": bool(w.operator_paused),
            "removed_at": w.removed_at.isoformat() if w.removed_at else None,
        }
        d.update(telemetry.worker_snapshot(w))
        result.append(d)
    return result


@router.get("/receivers")
async def list_receivers(s: AsyncSession = Depends(session)) -> list[dict]:
    rows = (await s.execute(select(Receiver))).scalars().all()
    result = []
    for r in rows:
        d = {
            "receiver_id": r.receiver_id,
            "version": r.version,
            "platform": r.platform,
            "enabled": r.enabled,
        }
        d.update(telemetry.receiver_snapshot(r))
        result.append(d)
    return result
