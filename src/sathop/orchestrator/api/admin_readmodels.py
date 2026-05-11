"""Admin dashboard read models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import NON_TERMINAL_STATES, GranuleState

from ..db import Event, Granule

NON_TERMINAL = set(NON_TERMINAL_STATES)
ACTIVE = {
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
    GranuleState.UPLOADED.value,
}
STUCK_AGE_HOURS = 6


def clamp_limit(limit: int, *, min_value: int = 1, max_value: int = 200) -> int:
    return max(min_value, min(max_value, limit))


def stuck_threshold(now: datetime) -> datetime:
    return now - timedelta(hours=STUCK_AGE_HOURS)


def event_summary(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": event.ts.isoformat(),
        "level": event.level,
        "source": event.source,
        "message": event.message,
    }


def granule_activity_row(granule: Granule) -> dict[str, Any]:
    return {
        "granule_id": granule.granule_id,
        "batch_id": granule.batch_id,
        "state": granule.state,
        "leased_by": granule.leased_by,
        "retry_count": granule.retry_count,
        "updated_at": granule.updated_at.isoformat(),
    }


def stuck_granule_row(granule: Granule, *, now: datetime) -> dict[str, Any]:
    return {
        **granule_activity_row(granule),
        "error": granule.error,
        "age_hours": (now - granule.updated_at).total_seconds() / 3600,
    }


async def admin_overview(s: AsyncSession, *, now: datetime) -> dict[str, Any]:
    state_counts = dict(
        (await s.execute(select(Granule.state, func.count(Granule.granule_id)).group_by(Granule.state))).all()
    )
    stuck = dict(
        (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state.in_(list(NON_TERMINAL)))
                .where(Granule.updated_at < stuck_threshold(now))
                .group_by(Granule.state)
            )
        ).all()
    )
    last_events = (await s.execute(select(Event).order_by(Event.id.desc()).limit(10))).scalars().all()
    return {
        "state_counts": state_counts,
        "stuck_over_hours": STUCK_AGE_HOURS,
        "stuck_by_state": stuck,
        "last_events": [event_summary(e) for e in last_events],
    }


async def in_flight_granule_rows(s: AsyncSession, *, limit: int) -> list[dict[str, Any]]:
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
    return [granule_activity_row(g) for g in rows]


async def stuck_granule_rows(
    s: AsyncSession,
    *,
    now: datetime,
    state: str | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(Granule)
        .where(Granule.updated_at < stuck_threshold(now))
        .order_by(Granule.updated_at.asc())
        .limit(limit)
    )
    if state is None:
        stmt = stmt.where(Granule.state.in_(list(NON_TERMINAL)))
    else:
        stmt = stmt.where(Granule.state == state)
    rows = (await s.execute(stmt)).scalars().all()
    return [stuck_granule_row(g, now=now) for g in rows]
