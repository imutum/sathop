from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select, update

from sathop.shared.periodic import run_periodic
from sathop.shared.state_machine import LEASED_STATES, GranuleState

from .config import settings
from .db import Event, Granule, GranuleObject, GranuleStageTiming, get_session_maker, utcnow
from .pubsub import commit_and_publish, log_event, publish

_log = logging.getLogger("sathop.orch.background")

SWEEP_INTERVAL_SEC = 60


async def sweep_expired_leases() -> int:
    now = utcnow()
    async with get_session_maker()() as s:
        stmt = (
            select(Granule)
            .where(Granule.state.in_(LEASED_STATES))
            .where(Granule.lease_expires_at.is_not(None))
            .where(Granule.lease_expires_at < now)
        )
        expired = (await s.execute(stmt)).scalars().all()
        if not expired:
            return 0
        ids = [g.granule_id for g in expired]
        # Re-assert the expiry predicate on the UPDATE: between our SELECT and
        # this write, lease() may have refreshed the lease for some of these
        # IDs. Without this guard the sweeper would clobber a freshly-acquired
        # lease, and the worker that just got it would see its state report
        # 409 a few seconds later.
        result = await s.execute(
            update(Granule)
            .where(Granule.granule_id.in_(ids))
            .where(Granule.state.in_(LEASED_STATES))
            .where(Granule.lease_expires_at.is_not(None))
            .where(Granule.lease_expires_at < now)
            .values(state=GranuleState.PENDING.value, leased_by=None, lease_expires_at=None, updated_at=now)
        )
        actually_reclaimed = getattr(result, "rowcount", 0) or 0
        if actually_reclaimed == 0:
            return 0
        await log_event(s, "scheduler", f"reclaimed {actually_reclaimed} expired leases", level="warn")
        await commit_and_publish(s, "batches")
        return actually_reclaimed


async def run_lease_sweeper() -> None:
    async def body() -> None:
        n = await sweep_expired_leases()
        if n:
            _log.warning("reclaimed %d expired leases", n)

    await run_periodic(body, interval=SWEEP_INTERVAL_SEC, log=_log, name="lease sweep")


async def sweep_retention(
    *,
    events_days: int | None = None,
    deleted_days: int | None = None,
) -> dict[str, int]:
    ev_days = settings.retain_events_days if events_days is None else events_days
    del_days = settings.retain_deleted_days if deleted_days is None else deleted_days
    now = utcnow()
    out = {"events": 0, "granule_objects": 0, "stage_timings": 0, "granules": 0}

    async with get_session_maker()() as s:
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
    async def body() -> None:
        counts = await sweep_retention()
        if any(counts.values()):
            _log.info("retention pruned %s", counts)

    interval = settings.retention_sweep_sec
    await run_periodic(
        body,
        interval=interval,
        log=_log,
        name="retention sweep",
        initial_delay=interval,
        disabled_when_non_positive=True,
    )
