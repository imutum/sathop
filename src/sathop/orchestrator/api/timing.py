"""Per-stage timing query endpoints.

Granule-level: full closed-stage timeline (one row per attempt × stage).
Batch-level: per-stage aggregates (count / avg / p50 / p95 / max). Aggregates
are computed live from `granule_stage_timing`; granule counts in the millions
would warrant materialization but we're nowhere close."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import require_token
from ..db import Batch, Granule, GranuleStageTiming, session

router = APIRouter(tags=["timing"], dependencies=[Depends(require_token)])

_STAGES = ("download", "process", "upload")


def _stats(durations: list[int]) -> dict:
    """Empty-safe count/avg/p50/p95/max. Percentiles use nearest-rank — exact
    enough for ops dashboards; we are not publishing financial figures."""
    n = len(durations)
    if n == 0:
        return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}
    xs = sorted(durations)
    return {
        "count": n,
        "avg_ms": sum(xs) // n,
        "p50_ms": xs[min(n - 1, n * 50 // 100)],
        "p95_ms": xs[min(n - 1, n * 95 // 100)],
        "max_ms": xs[-1],
    }


@router.get("/granules/{granule_id}/timing")
async def granule_timing(granule_id: str, s: AsyncSession = Depends(session)) -> list[dict]:
    if await s.get(Granule, granule_id) is None:
        raise HTTPException(404, "granule not found")
    rows = (
        (
            await s.execute(
                select(GranuleStageTiming)
                .where(GranuleStageTiming.granule_id == granule_id)
                .order_by(GranuleStageTiming.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "stage": r.stage,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat(),
            "duration_ms": r.duration_ms,
        }
        for r in rows
    ]


@router.get("/batches/{batch_id}/timing")
async def batch_timing(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    if await s.get(Batch, batch_id) is None:
        raise HTTPException(404, "batch not found")
    rows = (
        await s.execute(
            select(
                GranuleStageTiming.stage,
                GranuleStageTiming.duration_ms,
                GranuleStageTiming.started_at,
                GranuleStageTiming.finished_at,
            ).where(GranuleStageTiming.batch_id == batch_id)
        )
    ).all()
    by_stage: dict[str, list[int]] = {st: [] for st in _STAGES}
    first_started = None
    last_finished = None
    for stage, dur, started, finished in rows:
        if stage in by_stage:
            by_stage[stage].append(int(dur))
        if first_started is None or started < first_started:
            first_started = started
        if last_finished is None or finished > last_finished:
            last_finished = finished
    wall_ms = (
        int((last_finished - first_started).total_seconds() * 1000)
        if first_started is not None and last_finished is not None
        else 0
    )
    return {
        "stages": {st: _stats(by_stage[st]) for st in _STAGES},
        "wall_ms": wall_ms,
        "first_started_at": first_started.isoformat() if first_started else None,
        "last_finished_at": last_finished.isoformat() if last_finished else None,
    }
