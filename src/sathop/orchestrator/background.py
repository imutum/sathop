from __future__ import annotations

import asyncio
import logging
import math
from datetime import timedelta

from sqlalchemy import delete, select, text, update

from sathop.shared.periodic import run_periodic
from sathop.shared.state_machine import LEASED_STATES, GranuleState, ReconcileOrphanDeleted, Scope

from . import db, event_store, telemetry
from .api._transition import apply_transition
from .api.progress import evict_granule, evict_granules
from .config import settings
from .db import Granule, GranuleObject, Rollout, Worker, get_session_maker, utcnow
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
        if grace > 0:
            cutoff = now - timedelta(seconds=grace)
            if db.is_postgres():
                # Liveness from the Worker row (heartbeats persist last_seen there
                # in PG mode), so it's correct across processes and orch restarts.
                live_ids = (
                    (
                        await s.execute(
                            select(Worker.worker_id)
                            .where(Worker.removed_at.is_(None))
                            .where(Worker.last_seen >= cutoff)
                        )
                    )
                    .scalars()
                    .all()
                )
            else:
                registered = (
                    (await s.execute(select(Worker.worker_id).where(Worker.removed_at.is_(None))))
                    .scalars()
                    .all()
                )
                live_ids = [
                    wid
                    for wid in registered
                    if (t := telemetry.get_worker(wid)) is not None and t.last_seen >= cutoff
                ]
        else:
            live_ids = (
                (await s.execute(select(Worker.worker_id).where(Worker.removed_at.is_(None)))).scalars().all()
            )
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

    async with get_session_maker()() as s:
        if ev_days > 0:
            # PG: DELETE old rows from the events table in this txn. SQLite: prune
            # the in-memory deque (needs no session, harmless inside the block).
            cutoff = now - timedelta(days=ev_days)
            if db.is_postgres():
                out["events"] = await event_store.prune_before_db(s, cutoff)
            else:
                out["events"] = event_store.prune_before(cutoff)
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


# ── Staged fleet rollout (L2) ─────────────────────────────────────────────
# The leader advances ONE active rollout canary→batch→fleet. The actuator is the
# existing per-worker update one-shot (worker contract unchanged); the gate is
# version-confirmed liveness. Because each wave's cohort is frozen at version!=
# target, "version==target" alone is sufficient proof of a post-stamp upgrade —
# we need not also check last_seen (which is RAM-only per-heartbeat under SQLite),
# and a crash-looping worker that L1 rolled back stays on the old version → never
# confirms → the wave times out and HALTs (hard fact #2). No telemetry is read.
ROLLOUT_TICK_SEC = 15
_WAVE_LABELS = ("canary", "batch", "fleet")


async def _active_rollout(s) -> Rollout | None:
    return await s.scalar(
        select(Rollout).where(Rollout.phase.in_(("pending", "running"))).order_by(Rollout.id.desc()).limit(1)
    )


async def _eligible_worker_ids(s, target: str) -> list[str]:
    """Registered, not operator-paused, not yet on target — ordered stably."""
    return list(
        (
            await s.execute(
                select(Worker.worker_id)
                .where(Worker.removed_at.is_(None))
                .where((Worker.operator_paused.is_(None)) | (Worker.operator_paused.is_(False)))
                .where(Worker.version != target)
                .order_by(Worker.worker_id)
            )
        )
        .scalars()
        .all()
    )


def _wave_size(wave_index: int, eligible_n: int, r: Rollout) -> int:
    if eligible_n == 0:
        return 0
    if wave_index == 0:  # canary
        return min(r.canary_count, eligible_n)
    if wave_index == 1:  # batch — a fraction of what's left, at least 1
        return min(eligible_n, max(1, math.ceil(eligible_n * r.batch_pct)))
    return eligible_n  # fleet — everyone remaining


async def rollout_member_breakdown(s, r: Rollout) -> tuple[list[str], list[str], list[str]]:
    """(confirmed, pending, excused) for the current frozen wave cohort. Excused =
    gone/removed/operator-paused (dropped from the denominator so a paused or
    deleted member can't block the wave forever)."""
    ids = list(r.wave_member_ids or [])
    if not ids:
        return [], [], []
    rows = {
        w.worker_id: w
        for w in (await s.execute(select(Worker).where(Worker.worker_id.in_(ids)))).scalars().all()
    }
    confirmed, pending, excused = [], [], []
    for wid in ids:
        w = rows.get(wid)
        if w is None or w.removed_at is not None or w.operator_paused:
            excused.append(wid)
        elif w.version == r.target_version:
            confirmed.append(wid)
        else:
            pending.append(wid)
    return confirmed, pending, excused


async def _enter_wave(s, r: Rollout, wave_index: int, now) -> None:
    """Select + freeze + stamp the wave's cohort, or finish if nothing's left."""
    eligible = await _eligible_worker_ids(s, r.target_version)
    size = _wave_size(wave_index, len(eligible), r)
    if size == 0:  # nothing eligible at/after this wave → rollout is complete
        r.phase, r.finished_at, r.updated_at = "done", now, now
        await log_event(s, "operator", f"rollout v{r.target_version} complete (no workers left to upgrade)")
        return
    members = eligible[:size]
    rows = (await s.execute(select(Worker).where(Worker.worker_id.in_(members)))).scalars().all()
    for w in rows:  # the existing per-worker update one-shot — consumed on next heartbeat
        w.update_requested_at = now
        w.update_to_version = r.target_version
    r.phase, r.wave_index = "running", wave_index
    r.wave_member_ids = members
    r.wave_started_at = now
    r.wave_deadline_at = now + timedelta(seconds=r.wave_timeout_sec)
    r.updated_at = now
    await log_event(
        s, "operator", f"rollout v{r.target_version}: {_WAVE_LABELS[wave_index]} wave → {len(members)} worker(s)"
    )


async def advance_rollout() -> bool:
    """One leader tick: drive the active rollout's state machine. Returns True when
    it changed something (committed)."""
    now = utcnow()
    async with get_session_maker()() as s:
        r = await _active_rollout(s)
        if r is None:
            return False
        if r.phase == "pending":
            await _enter_wave(s, r, 0, now)
            await commit_and_publish(s, Scope.WORKERS, Scope.ROLLOUT)
            return True
        # phase == "running": gate the current wave on version-confirmed liveness.
        _confirmed, pending, _excused = await rollout_member_breakdown(s, r)
        if not pending:  # wave done → next wave, or finish after fleet
            if r.wave_index >= 2:
                r.phase, r.finished_at, r.updated_at = "done", now, now
                await log_event(s, "operator", f"rollout v{r.target_version} complete")
            else:
                await _enter_wave(s, r, r.wave_index + 1, now)
            await commit_and_publish(s, Scope.WORKERS, Scope.ROLLOUT)
            return True
        if r.wave_deadline_at is not None and now >= r.wave_deadline_at:
            r.phase, r.updated_at = "halted", now
            r.halt_reason = f"{_WAVE_LABELS[r.wave_index]} wave timed out; unconfirmed: {', '.join(pending)}"
            await log_event(s, "operator", f"rollout v{r.target_version} HALTED — {r.halt_reason}", level="warn")
            await commit_and_publish(s, Scope.ROLLOUT)
            return True
        return False  # still waiting within the window — no change


async def run_rollout() -> None:
    await run_periodic(advance_rollout, interval=ROLLOUT_TICK_SEC, log=_log, name="rollout")


# Session-level advisory-lock key: the holder is the background-task leader. The
# lock lives on that session's connection, so if the leader process dies the
# connection drops and Postgres auto-releases it for another process to claim.
_LEADER_KEY = 0x5A7410


async def run_leader_tasks() -> None:
    """Run the periodic sweepers in exactly one process.

    SQLite (single-process): run them directly. Postgres (multi-process): contend
    for a session-level advisory lock; only the holder runs the sweepers. A
    crashed leader's connection drops → Postgres frees the lock → a contender
    picks it up on the next retry."""
    if not db.is_postgres():
        await asyncio.gather(run_lease_sweeper(), run_retention(), run_rollout())
        return
    from .db import get_session_maker

    while True:
        async with get_session_maker()() as lock_s:
            got = bool(await lock_s.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LEADER_KEY}))
            if got:
                _log.info("became background-task leader (pg advisory lock)")
                try:
                    # Holds the lock for as long as lock_s stays open; gather only
                    # returns on cancellation (shutdown), which releases it.
                    await asyncio.gather(run_lease_sweeper(), run_retention(), run_rollout())
                finally:
                    await lock_s.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LEADER_KEY})
                return
        await asyncio.sleep(7)  # not leader — retry so a dead leader is replaced
