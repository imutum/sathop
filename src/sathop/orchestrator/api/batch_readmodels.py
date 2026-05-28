"""Batch view: the canonical read-model for `BatchSummary` and `GranuleRow`.

Two layers of public entry:

- **High-level** (`summary`, `summaries`, `granule_rows`) — what handlers reach
  for. Each one returns a fully composed DTO; callers never need to know
  about the underlying aggregate queries or their composition order.

- **Primitive** (`state_counts`, `eta_seconds`) — the bulk aggregates the
  high-level entries compose internally. Kept public because the ETA
  extrapolation is non-trivial and deserves direct test coverage; reach
  for these only when a caller genuinely wants raw counts, not a view.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import BatchSummary, GranuleRow
from sathop.shared.state_machine import IN_FLIGHT_STATES

from ..db import Batch, Granule, GranuleObject, GranuleStageTiming
from ._helpers import object_is_exhausted


async def summaries(s: AsyncSession, batches: list[Batch]) -> list[BatchSummary]:
    """Compose `BatchSummary` for each given Batch in one bulk pass.

    Three aggregates run once each (state counts, exhausted-pull objects,
    ETA extrapolation) and are zipped onto the input order. Empty input
    returns []."""
    if not batches:
        return []
    ids = [b.batch_id for b in batches]
    counts_map = await state_counts(s, ids)
    exh_map = await _exhausted_by_batch(s, ids)
    eta_map = await eta_seconds(s, counts_map)
    eta_rt_map = await eta_realtime(s, counts_map)
    return [
        _build_summary(
            b,
            counts=counts_map.get(b.batch_id, {}),
            objects_exhausted=exh_map.get(b.batch_id, 0),
            eta_seconds=eta_map.get(b.batch_id),
            eta_realtime=eta_rt_map.get(b.batch_id),
        )
        for b in batches
    ]


async def summary(s: AsyncSession, batch: Batch) -> BatchSummary:
    """Single-Batch convenience: delegates to `summaries([batch])`."""
    return (await summaries(s, [batch]))[0]


def summary_just_created(batch: Batch, *, counts: dict[str, int]) -> BatchSummary:
    """Fresh-from-create view: skips the exhausted/ETA queries because a
    just-committed Batch has neither. Caller supplies the counts (typically
    `await state_counts(s, [batch.batch_id])[batch.batch_id]`)."""
    return _build_summary(batch, counts=counts, objects_exhausted=0, eta_seconds=None, eta_realtime=None)


async def granule_rows(s: AsyncSession, granules: list[Granule]) -> list[GranuleRow]:
    """Compose `GranuleRow` for each Granule, joining the per-Granule
    exhausted-pull-object count in one bulk query."""
    if not granules:
        return []
    exh_map = await _exhausted_by_granule(s, [g.granule_id for g in granules])
    return [_build_granule_row(g, objects_exhausted=exh_map.get(g.granule_id, 0)) for g in granules]


async def state_counts(s: AsyncSession, batch_ids: list[str]) -> dict[str, dict[str, int]]:
    """Per-Batch state-bucket counts. Returns {} for empty input; for each
    requested batch_id, returns its (possibly empty) state→count mapping."""
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


async def eta_seconds(
    s: AsyncSession,
    counts_map: dict[str, dict[str, int]],
) -> dict[str, int | None]:
    """Extrapolate remaining-seconds per Batch from closed upload-stage timings.

    Heuristic: take the wall-time span between the earliest and latest stage
    rows for the Batch, divide by the count of closed upload stages, then
    multiply by the in-flight Granule count. Returns None when there's not
    enough timing data (<3 closed uploads) or nothing left in flight."""
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


async def eta_realtime(
    s: AsyncSession,
    counts_map: dict[str, dict[str, int]],
    window_sec: int = 60,
) -> dict[str, int | None]:
    """ETA from recent throughput: uploads finished in the last `window_sec`."""
    if not counts_map:
        return {}
    batch_ids = list(counts_map)
    cutoff_start = datetime.now(UTC) - timedelta(seconds=window_sec)

    rows = (
        await s.execute(
            select(
                GranuleStageTiming.batch_id,
                func.count(),
            )
            .where(GranuleStageTiming.batch_id.in_(batch_ids))
            .where(GranuleStageTiming.stage == "upload")
            .where(GranuleStageTiming.finished_at >= cutoff_start)
            .group_by(GranuleStageTiming.batch_id)
        )
    ).all()

    out: dict[str, int | None] = dict.fromkeys(batch_ids, None)
    for batch_id, recent_done in rows:
        if recent_done <= 0:
            continue
        remaining = sum(counts_map[batch_id].get(st, 0) for st in IN_FLIGHT_STATES)
        if remaining <= 0:
            continue
        out[batch_id] = int(remaining * window_sec / recent_done)
    return out


def _build_summary(
    batch: Batch,
    *,
    counts: dict[str, int],
    objects_exhausted: int,
    eta_seconds: int | None,
    eta_realtime: int | None,
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
        eta_realtime=eta_realtime,
    )


def _build_granule_row(granule: Granule, *, objects_exhausted: int) -> GranuleRow:
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


async def _exhausted_by_batch(s: AsyncSession, batch_ids: list[str]) -> dict[str, int]:
    if not batch_ids:
        return {}
    stmt = (
        select(Granule.batch_id, func.count(GranuleObject.id))
        .join(Granule, GranuleObject.granule_id == Granule.granule_id)
        .where(Granule.batch_id.in_(batch_ids))
        .where(object_is_exhausted())
        .group_by(Granule.batch_id)
    )
    return {bid: n for bid, n in (await s.execute(stmt)).all()}


async def _exhausted_by_granule(s: AsyncSession, granule_ids: list[str]) -> dict[str, int]:
    if not granule_ids:
        return {}
    stmt = (
        select(GranuleObject.granule_id, func.count(GranuleObject.id))
        .where(GranuleObject.granule_id.in_(granule_ids))
        .where(object_is_exhausted())
        .group_by(GranuleObject.granule_id)
    )
    return {gid: n for gid, n in (await s.execute(stmt)).all()}
