"""Background tasks: lease-expiry sweeper + retention pruner."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select, update

from sathop.shared.protocol import GranuleState

from . import db
from .config import settings
from .db import Event, Granule, GranuleObject, GranuleStageTiming, utcnow
from .pubsub import log_event, publish

_log = logging.getLogger("sathop.orch.background")

SWEEP_INTERVAL_SEC = 60

# All states where a worker holds the lease. UPLOADED already clears
# leased_by, so it doesn't need reclaiming.
_RECLAIMABLE_STATES = (
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
)


async def sweep_expired_leases() -> int:
    assert db._session_maker is not None
    now = utcnow()
    async with db._session_maker() as s:
        stmt = (
            select(Granule)
            .where(Granule.state.in_(_RECLAIMABLE_STATES))
            .where(Granule.lease_expires_at.is_not(None))
            .where(Granule.lease_expires_at < now)
        )
        expired = (await s.execute(stmt)).scalars().all()
        if not expired:
            return 0
        ids = [g.granule_id for g in expired]
        await s.execute(
            update(Granule)
            .where(Granule.granule_id.in_(ids))
            .values(state=GranuleState.PENDING.value, leased_by=None, lease_expires_at=None, updated_at=now)
        )
        await log_event(s, "scheduler", f"reclaimed {len(ids)} expired leases", level="warn")
        await s.commit()
        publish({"scope": "batches"})
        return len(ids)


async def run_lease_sweeper() -> None:
    while True:
        try:
            n = await sweep_expired_leases()
            if n:
                _log.warning("reclaimed %d expired leases", n)
        except Exception as e:
            _log.warning("sweep failed: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL_SEC)


async def sweep_retention(
    *,
    events_days: int | None = None,
    deleted_days: int | None = None,
) -> dict[str, int]:
    assert db._session_maker is not None
    ev_days = settings.retain_events_days if events_days is None else events_days
    del_days = settings.retain_deleted_days if deleted_days is None else deleted_days
    now = utcnow()
    out = {"events": 0, "granule_objects": 0, "stage_timings": 0, "granules": 0}

    async with db._session_maker() as s:
        if ev_days > 0:
            cutoff = now - timedelta(days=ev_days)
            r = await s.execute(delete(Event).where(Event.ts < cutoff))
            out["events"] = getattr(r, "rowcount", 0) or 0

        if del_days > 0:
            cutoff = now - timedelta(days=del_days)
            r = await s.execute(
                delete(GranuleObject)
                .where(GranuleObject.deleted_at.is_not(None))
                .where(GranuleObject.deleted_at < cutoff)
            )
            out["granule_objects"] = getattr(r, "rowcount", 0) or 0
            # Children before parent: stage timings reference granules; SQLite FKs
            # aren't enforced but staying consistent keeps the table bounded.
            doomed = (
                (
                    await s.execute(
                        select(Granule.granule_id)
                        .where(Granule.state == GranuleState.DELETED.value)
                        .where(Granule.updated_at < cutoff)
                    )
                )
                .scalars()
                .all()
            )
            if doomed:
                r = await s.execute(
                    delete(GranuleStageTiming).where(GranuleStageTiming.granule_id.in_(doomed))
                )
                out["stage_timings"] = getattr(r, "rowcount", 0) or 0
                r = await s.execute(delete(Granule).where(Granule.granule_id.in_(doomed)))
                out["granules"] = getattr(r, "rowcount", 0) or 0

        await s.commit()

    if any(out.values()):
        if out["events"]:
            publish({"scope": "events"})
        if out["granules"] or out["granule_objects"]:
            publish({"scope": "batches"})
    return out


async def run_retention() -> None:
    interval = settings.retention_sweep_sec
    if interval <= 0:
        _log.info("retention sweeper disabled (SATHOP_RETENTION_SWEEP_SEC=%d)", interval)
        return
    while True:
        await asyncio.sleep(interval)
        try:
            counts = await sweep_retention()
            if any(counts.values()):
                _log.info("retention pruned %s", counts)
        except Exception as e:
            _log.warning("retention sweep failed: %s", e)
