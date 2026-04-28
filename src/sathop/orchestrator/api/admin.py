"""Admin / operational endpoints. Used by reconcile CLI and Web UI dashboards."""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import GranuleState

from ..config import require_token, settings
from ..db import Event, Granule, session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_token)])

NON_TERMINAL = {
    GranuleState.PENDING.value,
    GranuleState.QUEUED.value,
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
    GranuleState.UPLOADED.value,
    GranuleState.ACKED.value,
}

# States where the worker is actively doing work (excluding pending — queued but
# nothing is happening yet — and acked — receiver-side state). Powers the
# Dashboard "currently running" list.
ACTIVE = {
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
    GranuleState.UPLOADED.value,
}

STUCK_AGE_HOURS = 6


@router.get("/overview")
async def overview(s: AsyncSession = Depends(session)) -> dict:
    state_counts = dict(
        (await s.execute(select(Granule.state, func.count(Granule.granule_id)).group_by(Granule.state))).all()
    )

    now = datetime.now(UTC)
    threshold = now - timedelta(hours=STUCK_AGE_HOURS)
    stuck_stmt = (
        select(Granule.state, func.count(Granule.granule_id))
        .where(Granule.state.in_(list(NON_TERMINAL)))
        .where(Granule.updated_at < threshold)
        .group_by(Granule.state)
    )
    stuck = dict((await s.execute(stuck_stmt)).all())

    last_events = (await s.execute(select(Event).order_by(Event.id.desc()).limit(10))).scalars().all()

    return {
        "state_counts": state_counts,
        "stuck_over_hours": STUCK_AGE_HOURS,
        "stuck_by_state": stuck,
        "last_events": [
            {"id": e.id, "ts": e.ts.isoformat(), "level": e.level, "source": e.source, "message": e.message}
            for e in last_events
        ],
    }


@router.get("/in-flight")
async def list_in_flight(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    """Granules the fleet is actively working on right now. Most-recently-updated
    first, which tracks the pipeline's pulse better than by-id or by-created.
    pending is excluded — queued, not running."""
    limit = max(1, min(200, limit))
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.state.in_(list(ACTIVE)))
                .order_by(Granule.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "granule_id": g.granule_id,
            "batch_id": g.batch_id,
            "state": g.state,
            "leased_by": g.leased_by,
            "retry_count": g.retry_count,
            "updated_at": g.updated_at.isoformat(),
        }
        for g in rows
    ]


@router.get("/stuck/{state}")
async def list_stuck(state: str, s: AsyncSession = Depends(session)) -> list[dict]:
    if state not in NON_TERMINAL:
        return []
    now = datetime.now(UTC)
    threshold = now - timedelta(hours=STUCK_AGE_HOURS)
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.state == state)
                .where(Granule.updated_at < threshold)
                .order_by(Granule.updated_at.asc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "granule_id": g.granule_id,
            "batch_id": g.batch_id,
            "state": g.state,
            "leased_by": g.leased_by,
            "retry_count": g.retry_count,
            "error": g.error,
            "updated_at": g.updated_at.isoformat(),
            "age_hours": (now - g.updated_at).total_seconds() / 3600,
        }
        for g in rows
    ]


@router.get("/stuck")
async def list_stuck_all(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    """Top-N oldest stuck granules across every non-terminal state. Powers the
    Dashboard's drill-down — operator sees count → clicks → sees the actual
    rows to investigate without paging through every state separately."""
    limit = max(1, min(500, limit))
    now = datetime.now(UTC)
    threshold = now - timedelta(hours=STUCK_AGE_HOURS)
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.state.in_(list(NON_TERMINAL)))
                .where(Granule.updated_at < threshold)
                .order_by(Granule.updated_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "granule_id": g.granule_id,
            "batch_id": g.batch_id,
            "state": g.state,
            "leased_by": g.leased_by,
            "retry_count": g.retry_count,
            "error": g.error,
            "updated_at": g.updated_at.isoformat(),
            "age_hours": (now - g.updated_at).total_seconds() / 3600,
        }
        for g in rows
    ]


class OrchestratorInfo(BaseModel):
    version: str
    python_version: str
    platform: str
    db_path: str
    retain_events_days: int
    retain_deleted_days: int
    retention_sweep_sec: int
    max_inflight_per_worker: int
    max_retries: int
    max_pull_failures: int
    stuck_age_hours: int
    dev_mode: bool
    auth_open: bool


@router.get("/settings/info", response_model=OrchestratorInfo)
async def orchestrator_info() -> OrchestratorInfo:
    return OrchestratorInfo(
        version="0.1.0",
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        db_path=str(settings.db_path),
        retain_events_days=settings.retain_events_days,
        retain_deleted_days=settings.retain_deleted_days,
        retention_sweep_sec=settings.retention_sweep_sec,
        max_inflight_per_worker=settings.max_inflight_per_worker,
        max_retries=settings.max_retries,
        max_pull_failures=settings.max_pull_failures,
        stuck_age_hours=STUCK_AGE_HOURS,
        dev_mode=settings.dev,
        auth_open=not settings.token,
    )
