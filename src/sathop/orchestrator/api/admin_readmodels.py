"""Admin dashboard read models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import ACTIVE_STATES, NON_TERMINAL_STATES, GranuleState

from .. import event_store
from ..config import settings
from ..db import Batch, Granule
from .batch_readmodels import system_delivery_rate

NON_TERMINAL = set(NON_TERMINAL_STATES)
ACTIVE = set(ACTIVE_STATES)
# Single source: the env-backed setting. Kept as a module symbol because admin.py
# and tests import it; reads the configured value at import time.
STUCK_AGE_HOURS = settings.stuck_age_hours


def clamp_limit(limit: int, *, min_value: int = 1, max_value: int = 200) -> int:
    return max(min_value, min(max_value, limit))


def stuck_threshold(now: datetime) -> datetime:
    return now - timedelta(hours=STUCK_AGE_HOURS)


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
    state_counts = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state != GranuleState.DELETED.value)
                .group_by(Granule.state)
            )
        ).all()
    }
    # deleted = cumulative delivered, read from the persistent counter instead of
    # COUNTing the (huge, terminal) deleted rows.
    state_counts["deleted"] = int(await s.scalar(select(func.coalesce(func.sum(Batch.delivered_count), 0))) or 0)
    stuck = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state.in_(list(NON_TERMINAL)))
                .where(Granule.updated_at < stuck_threshold(now))
                .group_by(Granule.state)
            )
        ).all()
    }
    throughput_per_min, eta_realtime = await system_delivery_rate(s, state_counts)
    return {
        "state_counts": state_counts,
        "stuck_over_hours": STUCK_AGE_HOURS,
        "stuck_by_state": stuck,
        "last_events": event_store.last_n(10),
        "throughput_per_min": throughput_per_min,
        "eta_realtime": eta_realtime,
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
