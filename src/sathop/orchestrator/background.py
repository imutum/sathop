from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select, update

from sathop.shared.periodic import run_periodic
from sathop.shared.state_machine import LEASED_STATES, GranuleState, ReconcileOrphanDeleted, Scope

from . import event_store, telemetry
from .api._transition import apply_transition
from .api.progress import evict_granule, evict_granules
from .config import settings
from .db import Granule, GranuleObject, Worker, get_session_maker, utcnow
from .pubsub import commit_and_publish, log_event, publish
from .reaping import reap_granules

_log = logging.getLogger("sathop.orch.background")

SWEEP_INTERVAL_SEC = 60
# Stamped at import (≈ process start). The orphan-acked sweep needs it to hold off
# until workers have had a chance to re-heartbeat after an orchestrator restart —
# in-memory telemetry is empty until then, so absence ≠ "worker gone".
_STARTED_AT = utcnow()


async def sweep_expired_leases() -> int:
    """The single carve-out from `state_machine.apply()`: stays as a bulk
    UPDATE with a re-asserted predicate. Why: between the SELECT and the
    write, a concurrent /heartbeat::renew_worker_leases call may have pushed
    a granule's `lease_expires_at` forward. A per-row apply() would have to
    `s.refresh(g)` each row to see that fresh value — doubling round-trips.
    The bulk UPDATE re-evaluates the same predicate at write time, so a
    just-renewed lease falls outside the WHERE clause and survives untouched.

    All other granule state transitions go through state_machine.apply()."""
    now = utcnow()
    async with get_session_maker()() as s:
        stmt = (
            select(Granule.granule_id)
            .where(Granule.state.in_(LEASED_STATES))
            .where(Granule.lease_expires_at.is_not(None))
            .where(Granule.lease_expires_at < now)
        )
        ids = (await s.execute(stmt)).scalars().all()
        if not ids:
            return 0
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
        evict_granules(ids)
        await log_event(s, "scheduler", f"reclaimed {actually_reclaimed} expired leases", level="warn")
        await commit_and_publish(s, Scope.BATCHES)
        return actually_reclaimed


async def sweep_orphaned_acked() -> int:
    """Backstop for the acked→deleted gap. A granule reaches ACKED once the
    receiver has acked its objects, then waits for the uploading worker to delete
    its local copy and emit DeleteConfirmed (the worker janitor). If that worker
    is gone — removed, purged, or restarted under a fresh id — no one ever
    confirms and the granule strands in ACKED forever. The data is already
    delivered and the worker's bytes left with it, so the orchestrator
    self-confirms the deletion for any ACKED granule with no live worker still
    owning an undeleted object.

    A worker counts as live while `removed_at` is NULL and (when grace > 0) it has
    heartbeated within the grace window — so a worker mid-restart keeps its own
    cleanup right and only true orphans flip. Each flip rides the same
    rowcount-gated delete path as DeleteConfirmed, so `delivered_count` stays
    correct even if a straggling worker confirm races this sweep.

    Liveness is read from in-memory heartbeat telemetry, NOT the Worker.last_seen DB
    column — that column is only stamped at (re)register (heartbeats keep liveness in
    RAM to avoid WAL write amplification), so a long-running worker's row looks stale
    forever. Right after an orchestrator restart that telemetry is empty until workers
    re-report (~one heartbeat interval), so the sweep holds off until the process has
    been up at least `grace`; only then is absence-from-telemetry real. grace<=0 falls
    back to "any non-removed registered worker is live" — telemetry-independent and
    restart-safe (reads only the DB), the most conservative setting."""
    now = utcnow()
    grace = settings.acked_orphan_grace_sec
    if grace > 0 and now - _STARTED_AT < timedelta(seconds=grace):
        return 0  # cold start: let workers re-heartbeat before trusting telemetry absence
    async with get_session_maker()() as s:
        registered = (
            (await s.execute(select(Worker.worker_id).where(Worker.removed_at.is_(None)))).scalars().all()
        )
        if grace > 0:
            cutoff = now - timedelta(seconds=grace)
            live_ids = [
                wid
                for wid in registered
                if (t := telemetry.get_worker(wid)) is not None and t.last_seen >= cutoff
            ]
        else:
            live_ids = list(registered)
        orphans = (
            (
                await s.execute(
                    select(Granule)
                    .where(Granule.state == GranuleState.ACKED.value)
                    .where(
                        ~select(GranuleObject.id)
                        .where(GranuleObject.granule_id == Granule.granule_id)
                        .where(GranuleObject.deleted_at.is_(None))
                        .where(GranuleObject.worker_id.in_(live_ids))
                        .exists()
                    )
                )
            )
            .scalars()
            .all()
        )
        if not orphans:
            return 0
        for g in orphans:
            await apply_transition(
                s, g, ReconcileOrphanDeleted(granule_id=g.granule_id), now=now, on_conflict="skip"
            )
            evict_granule(g.granule_id)
        await log_event(
            s,
            "scheduler",
            f"reconciled {len(orphans)} orphaned acked granule(s) → deleted (owner gone)",
            level="warn",
        )
        await commit_and_publish(s, Scope.BATCHES)
        return len(orphans)


async def run_lease_sweeper() -> None:
    async def body() -> None:
        n = await sweep_expired_leases()
        if n:
            _log.warning("reclaimed %d expired leases", n)
        m = await sweep_orphaned_acked()
        if m:
            _log.warning("reconciled %d orphaned acked granules → deleted", m)

    await run_periodic(body, interval=SWEEP_INTERVAL_SEC, log=_log, name="lease sweep")


async def sweep_retention(
    *,
    events_days: int | None = None,
    deleted_days: int | None = None,
) -> dict[str, int]:
    ev_days = settings.retain_events_days if events_days is None else events_days
    del_days = settings.retain_deleted_days if deleted_days is None else deleted_days
    now = utcnow()
    out = {"events": 0, "granule_objects": 0, "stage_timings": 0, "granules": 0, "workers": 0}

    if ev_days > 0:
        cutoff = now - timedelta(days=ev_days)
        out["events"] = event_store.prune_before(cutoff)

    async with get_session_maker()() as s:
        if del_days > 0:
            cutoff = now - timedelta(days=del_days)
            r = await s.execute(
                delete(GranuleObject)
                .where(GranuleObject.deleted_at.is_not(None))
                .where(GranuleObject.deleted_at < cutoff)
            )
            out["granule_objects"] = getattr(r, "rowcount", 0) or 0
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
                reaped = await reap_granules(s, doomed)
                out["stage_timings"] = reaped["stage_timings"]
                out["granules"] = reaped["granules"]
                out["granule_objects"] += reaped["objects"]

        if del_days > 0:
            cutoff_w = now - timedelta(days=del_days)
            r = await s.execute(
                delete(Worker).where(Worker.removed_at.is_not(None)).where(Worker.removed_at < cutoff_w)
            )
            out["workers"] = getattr(r, "rowcount", 0) or 0

        await s.commit()

    if any(out.values()):
        if out["events"]:
            publish({"scope": "events"})
        if out["granules"] or out["granule_objects"]:
            publish({"scope": "batches"})
        if out["workers"]:
            publish({"scope": "workers"})
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
