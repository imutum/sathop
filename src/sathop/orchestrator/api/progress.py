"""Granule progress timeline: worker → orchestrator ingress + UI queries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import ProgressEvent

from ..config import require_token
from ..db import Batch, Granule, GranuleProgress, session, utcnow
from ..pubsub import publish

router = APIRouter(tags=["progress"], dependencies=[Depends(require_token)])


@router.post("/granules/{granule_id}/progress")
async def ingress(granule_id: str, event: ProgressEvent, s: AsyncSession = Depends(session)) -> dict:
    g = await s.get(Granule, granule_id)
    if g is None:
        raise HTTPException(404, "granule not found")
    s.add(
        GranuleProgress(
            granule_id=granule_id,
            batch_id=g.batch_id,
            ts=event.ts or utcnow(),
            step=event.step,
            pct=event.pct,
            detail=event.detail,
        )
    )
    await s.commit()
    publish({"scope": "progress", "granule_id": granule_id, "batch_id": g.batch_id})
    return {"ok": True}


@router.get("/granules/{granule_id}/progress")
async def granule_timeline(
    granule_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    s: AsyncSession = Depends(session),
) -> list[dict]:
    rows = (
        (
            await s.execute(
                select(GranuleProgress)
                .where(GranuleProgress.granule_id == granule_id)
                .order_by(GranuleProgress.id.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_row(r) for r in rows]


@router.get("/batches/{batch_id}/progress/latest")
async def batch_latest(batch_id: str, s: AsyncSession = Depends(session)) -> dict[str, dict]:
    """Latest checkpoint per granule in this batch — powers the batch-level
    "每个数据粒最近在做什么" view without pulling every row."""
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    sub = (
        select(func.max(GranuleProgress.id).label("mid"))
        .where(GranuleProgress.batch_id == batch_id)
        .group_by(GranuleProgress.granule_id)
        .subquery()
    )
    rows = (
        (await s.execute(select(GranuleProgress).join(sub, GranuleProgress.id == sub.c.mid))).scalars().all()
    )
    return {r.granule_id: _row(r) for r in rows}


def _row(r: GranuleProgress) -> dict:
    return {
        "id": r.id,
        "granule_id": r.granule_id,
        "batch_id": r.batch_id,
        "ts": r.ts.isoformat(),
        "step": r.step,
        "pct": r.pct,
        "detail": r.detail,
    }
