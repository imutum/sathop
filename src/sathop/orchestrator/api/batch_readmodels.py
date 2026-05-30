"""Batch view: the canonical read-model for `BatchSummary` and `GranuleRow`.

Two layers of public entry:

- **High-level** (`summary`, `summaries`, `granule_rows`) — what handlers reach
  for. Each one returns a fully composed DTO; callers never need to know
  about the underlying aggregate queries or their composition order.

- **Primitive** (`state_counts`) — the bulk aggregate the high-level entries
  compose internally. Kept public for direct test coverage; reach for it only
  when a caller genuinely wants raw counts, not a view.

ETA is realtime-only: extrapolated from deliveries in the recent `_WINDOW_SEC`
window (`_recent_delivered`, served by the (stage, finished_at) index). The old
historical ETA — min/max/sum over a batch's *entire* stage-timing history — was
dropped: it grew unbounded with delivered volume (an O(rows) scan per list call,
seconds on a multi-million-row batch) while duplicating the realtime figure the
UI already preferred. No recent delivery now simply means no ETA (a stall), not
a fallback to a whole-table scan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import BatchSummary, GranuleRow
from sathop.shared.state_machine import IN_FLIGHT_STATES, GranuleState

from ..db import Batch, Granule, GranuleObject, GranuleStageTiming
from ._helpers import object_is_exhausted

# Rolling window for "recent" delivery rate (realtime ETA + throughput).
_WINDOW_SEC = 60


def _remaining_to_deliver(counts: dict[str, int]) -> int:
    """Granules still expected to be delivered: everything in flight plus the
    uploaded-but-not-yet-acked backlog. Excludes acked/deleted (delivered) and
    failed/blacklisted (won't deliver without operator action)."""
    return sum(counts.get(st, 0) for st in IN_FLIGHT_STATES) + counts.get(GranuleState.UPLOADED.value, 0)


def _eta_from_recent(
    counts: dict[str, int], recent_delivered: int, window_sec: int = _WINDOW_SEC
) -> int | None:
    """Remaining-seconds from the recent delivery rate. None when nothing was
    delivered in the window (rate unknown) or nothing is left to deliver."""
    if recent_delivered <= 0:
        return None
    remaining = _remaining_to_deliver(counts)
    if remaining <= 0:
        return None
    return int(remaining * window_sec / recent_delivered)


def _throughput_per_min(recent_delivered: int, window_sec: int = _WINDOW_SEC) -> float:
    """Deliveries per minute over the rolling window. 0.0 when none recently —
    a meaningful 'delivery stalled' signal, distinct from a None freshly-created
    batch."""
    return recent_delivered * 60.0 / window_sec


async def summaries(s: AsyncSession, batches: list[Batch]) -> list[BatchSummary]:
    """Compose `BatchSummary` for each given Batch in one bulk pass.

    Three aggregates run once each (state counts, exhausted-pull objects,
    recent-delivery count) and are zipped onto the input order. The recent-
    delivery count drives both realtime ETA and throughput, so it's fetched once
    and the two are derived purely — all window-bounded, none scanning a batch's
    full history. Empty input returns []."""
    if not batches:
        return []
    ids = [b.batch_id for b in batches]
    counts_map = await state_counts(s, ids)
    exh_map = await _exhausted_by_batch(s, ids)
    recent_map = await _recent_delivered(s, ids)
    return [
        _build_summary(
            b,
            counts=counts_map.get(b.batch_id, {}),
            objects_exhausted=exh_map.get(b.batch_id, 0),
            eta_realtime=_eta_from_recent(counts_map.get(b.batch_id, {}), recent_map.get(b.batch_id, 0)),
            throughput_per_min=_throughput_per_min(recent_map.get(b.batch_id, 0)),
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
    return _build_summary(batch, counts=counts, objects_exhausted=0, eta_realtime=None)


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
        .where(Granule.state != GranuleState.DELETED.value)
        .group_by(Granule.batch_id, Granule.state)
    )
    out: dict[str, dict[str, int]] = {bid: {} for bid in batch_ids}
    for batch_id, state, n in (await s.execute(stmt)).all():
        out[batch_id][state] = n
    # deleted = cumulative delivered, from the persistent per-batch counter.
    delivered = (
        await s.execute(select(Batch.batch_id, Batch.delivered_count).where(Batch.batch_id.in_(batch_ids)))
    ).all()
    for bid, n in delivered:
        out[bid]["deleted"] = n or 0
    return out


async def system_delivery_rate(
    s: AsyncSession,
    state_counts: dict[str, int],
    window_sec: int = _WINDOW_SEC,
) -> tuple[float, int | None]:
    """System-wide (all batches) delivery throughput (granules/min) and realtime
    ETA, from deliver-stage closures in the recent window. Same definitions as
    the per-batch figures, so the dashboard and a batch's progress tab agree."""
    cutoff = datetime.now(UTC) - timedelta(seconds=window_sec)
    recent = int(
        await s.scalar(
            select(func.count())
            .select_from(GranuleStageTiming)
            .where(GranuleStageTiming.stage == "deliver")
            .where(GranuleStageTiming.finished_at >= cutoff)
        )
        or 0
    )
    return _throughput_per_min(recent, window_sec), _eta_from_recent(state_counts, recent, window_sec)


async def _recent_delivered(
    s: AsyncSession,
    batch_ids: list[str],
    window_sec: int = _WINDOW_SEC,
) -> dict[str, int]:
    """Per-Batch count of deliveries (deliver-stage closures) finished in the
    last `window_sec`. One query feeds both the realtime ETA and the throughput
    figure — keep them derived from this so they never disagree."""
    if not batch_ids:
        return {}
    cutoff_start = datetime.now(UTC) - timedelta(seconds=window_sec)
    rows = (
        await s.execute(
            select(GranuleStageTiming.batch_id, func.count())
            .where(GranuleStageTiming.batch_id.in_(batch_ids))
            .where(GranuleStageTiming.stage == "deliver")
            .where(GranuleStageTiming.finished_at >= cutoff_start)
            .group_by(GranuleStageTiming.batch_id)
        )
    ).all()
    return {batch_id: int(n) for batch_id, n in rows}


def _build_summary(
    batch: Batch,
    *,
    counts: dict[str, int],
    objects_exhausted: int,
    eta_realtime: int | None,
    throughput_per_min: float | None = None,
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
        eta_realtime=eta_realtime,
        throughput_per_min=throughput_per_min,
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
