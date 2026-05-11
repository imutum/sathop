"""Batch API read-model helpers."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import IN_FLIGHT_STATES, BatchSummary, GranuleRow

from ..config import settings
from ..db import Batch, Granule, GranuleObject, GranuleStageTiming


def batch_summary(
    batch: Batch,
    *,
    counts: dict[str, int],
    objects_exhausted: int = 0,
    eta_seconds: int | None = None,
) -> BatchSummary:
    return BatchSummary(
        batch_id=batch.batch_id,
        name=batch.name,
        bundle_ref=batch.bundle_ref,
        target_receiver_id=batch.target_receiver_id,
        status=batch.status,
        created_at=batch.created_at,
        counts=counts,
        objects_exhausted=objects_exhausted,
        eta_seconds=eta_seconds,
    )


def granule_row(granule: Granule, *, objects_exhausted: int = 0) -> GranuleRow:
    return GranuleRow(
        granule_id=granule.granule_id,
        batch_id=granule.batch_id,
        state=granule.state,
        retry_count=granule.retry_count,
        leased_by=granule.leased_by,
        error=granule.error,
        stdout_tail=granule.stdout_tail,
        stderr_tail=granule.stderr_tail,
        updated_at=granule.updated_at,
        objects_exhausted=objects_exhausted,
    )


async def batch_state_counts(s: AsyncSession, batch_id: str) -> dict[str, int]:
    return (await batch_state_counts_bulk(s, [batch_id]))[batch_id]


async def batch_state_counts_bulk(s: AsyncSession, batch_ids: list[str]) -> dict[str, dict[str, int]]:
    if not batch_ids:
        return {}
    stmt = (
        select(Granule.batch_id, Granule.state, func.count(Granule.granule_id))
        .where(Granule.batch_id.in_(batch_ids))
        .group_by(Granule.batch_id, Granule.state)
    )
    out: dict[str, dict[str, int]] = {bid: {} for bid in batch_ids}
    for batch_id, state, n in (await s.execute(stmt)).all():
        out[batch_id][state] = n
    return out


async def batch_exhausted_objects(s: AsyncSession, batch_id: str) -> int:
    return int(
        await s.scalar(
            select(func.count(GranuleObject.id))
            .join(Granule, GranuleObject.granule_id == Granule.granule_id)
            .where(Granule.batch_id == batch_id)
            .where(GranuleObject.acked_at.is_(None))
            .where(GranuleObject.deleted_at.is_(None))
            .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        )
        or 0
    )


async def batch_eta_seconds_bulk(
    s: AsyncSession,
    counts_map: dict[str, dict[str, int]],
) -> dict[str, int | None]:
    if not counts_map:
        return {}
    batch_ids = list(counts_map)
    rows = (
        await s.execute(
            select(
                GranuleStageTiming.batch_id,
                func.min(GranuleStageTiming.started_at),
                func.max(GranuleStageTiming.finished_at),
                func.sum(case((GranuleStageTiming.stage == "upload", 1), else_=0)),
            )
            .where(GranuleStageTiming.batch_id.in_(batch_ids))
            .group_by(GranuleStageTiming.batch_id)
        )
    ).all()

    out: dict[str, int | None] = dict.fromkeys(batch_ids, None)
    for batch_id, first, last, done in rows:
        done_n = int(done or 0)
        if done_n < 3 or first is None or last is None:
            continue
        wall_sec = (last - first).total_seconds()
        if wall_sec <= 0:
            continue
        remaining = sum(counts_map[batch_id].get(st, 0) for st in IN_FLIGHT_STATES)
        if remaining <= 0:
            continue
        out[batch_id] = int(remaining * wall_sec / done_n)
    return out


async def batch_exhausted_objects_bulk(s: AsyncSession, batch_ids: list[str]) -> dict[str, int]:
    if not batch_ids:
        return {}
    stmt = (
        select(Granule.batch_id, func.count(GranuleObject.id))
        .join(Granule, GranuleObject.granule_id == Granule.granule_id)
        .where(Granule.batch_id.in_(batch_ids))
        .where(GranuleObject.acked_at.is_(None))
        .where(GranuleObject.deleted_at.is_(None))
        .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        .group_by(Granule.batch_id)
    )
    return dict((await s.execute(stmt)).all())


async def exhausted_objects_by_granule(s: AsyncSession, granule_ids: list[str]) -> dict[str, int]:
    if not granule_ids:
        return {}
    stmt = (
        select(GranuleObject.granule_id, func.count(GranuleObject.id))
        .where(GranuleObject.granule_id.in_(granule_ids))
        .where(GranuleObject.acked_at.is_(None))
        .where(GranuleObject.deleted_at.is_(None))
        .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        .group_by(GranuleObject.granule_id)
    )
    return dict((await s.execute(stmt)).all())
