"""Background backstop: ACKED → DELETED when the uploading worker is gone.

A granule reaches ACKED once the receiver acks it, then waits for the uploading
worker's janitor to delete its local copy and emit DeleteConfirmed. If that
worker is removed / purged / restarted under a fresh id, no one ever confirms and
the granule strands in ACKED forever. `sweep_orphaned_acked` self-confirms such
orphans; a live worker always keeps the right to clean up (and free real disk) on
its own.

Liveness is judged from in-memory heartbeat telemetry, never the Worker.last_seen
DB column (which is frozen at register in production). Every worker here is seeded
with a deliberately *stale* DB last_seen, so any "live" verdict must come from the
telemetry the helper seeds separately — a regression guard for that very bug.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from sathop.orchestrator import background, telemetry
from sathop.orchestrator import db as orch_db
from sathop.orchestrator.background import sweep_orphaned_acked
from sathop.orchestrator.db import Batch, Granule, GranuleObject, Worker, utcnow
from sathop.orchestrator.telemetry import WorkerTelemetry
from sathop.shared.state_machine import (
    GranuleSnapshot,
    GranuleState,
    ReconcileOrphanDeleted,
    StateConflict,
    apply,
)


@pytest.fixture
async def db(tmp_path, patch_settings, monkeypatch):
    patch_settings(db_path=tmp_path / "test.db", token="", acked_orphan_grace_sec=600)
    # Pretend the process has been up well past `grace` so the cold-start guard
    # (which short-circuits every sweep to 0 right after start) is satisfied.
    monkeypatch.setattr(background, "_STARTED_AT", utcnow() - timedelta(seconds=100_000))
    await orch_db.init_db()
    try:
        yield
    finally:
        await orch_db.shutdown_db()


async def _seed_worker(worker_id: str, *, removed: bool = False, heartbeat_age_sec: float | None = None):
    """Register a worker. DB last_seen is always stale (mirrors prod, where heartbeats
    don't touch it). Pass heartbeat_age_sec to also seed in-memory telemetry — that is
    the only thing that makes a worker count as live."""
    async with orch_db._session_maker() as s:
        s.add(
            Worker(
                worker_id=worker_id,
                last_seen=utcnow() - timedelta(days=1),
                removed_at=utcnow() if removed else None,
            )
        )
        await s.commit()
    if heartbeat_age_sec is not None:
        telemetry.update_worker(
            worker_id, WorkerTelemetry(last_seen=utcnow() - timedelta(seconds=heartbeat_age_sec))
        )


async def _seed_acked(
    gid: str,
    *,
    owner: str,
    batch_id: str = "b",
    state: str = GranuleState.ACKED.value,
    object_deleted: bool = False,
):
    async with orch_db._session_maker() as s:
        if await s.get(Batch, batch_id) is None:
            s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        s.add(Granule(granule_id=gid, batch_id=batch_id, state=state, inputs=[]))
        s.add(
            GranuleObject(
                granule_id=gid,
                worker_id=owner,
                object_key="o.tif",
                presigned_url="http://w/o",
                sha256="0" * 64,
                size=1,
                acked_at=utcnow(),
                acked_by="r1",
                deleted_at=utcnow() if object_deleted else None,
            )
        )
        await s.commit()


async def _state(gid: str) -> str:
    async with orch_db._session_maker() as s:
        return (await s.get(Granule, gid)).state


async def _delivered(batch_id: str = "b") -> int:
    async with orch_db._session_maker() as s:
        return (await s.get(Batch, batch_id)).delivered_count or 0


async def test_reconciles_when_owner_removed(db):
    await _seed_worker("w1", removed=True, heartbeat_age_sec=5)  # removed dominates fresh telemetry
    await _seed_acked("g1", owner="w1")
    assert await sweep_orphaned_acked() == 1
    assert await _state("g1") == GranuleState.DELETED.value
    assert await _delivered() == 1  # counted exactly once, via the delete path
    async with orch_db._session_maker() as s:
        obj = (await s.execute(select(GranuleObject))).scalars().first()
        assert obj.deleted_at is not None


async def test_reconciles_when_owner_absent(db):
    # No Worker row for the owner at all (purged) → not registered → orphan.
    await _seed_acked("g1", owner="ghost")
    assert await sweep_orphaned_acked() == 1
    assert await _state("g1") == GranuleState.DELETED.value


async def test_reconciles_when_owner_heartbeat_lapsed(db):
    await _seed_worker("w1", heartbeat_age_sec=601)  # telemetry older than 600s grace
    await _seed_acked("g1", owner="w1")
    assert await sweep_orphaned_acked() == 1
    assert await _state("g1") == GranuleState.DELETED.value


async def test_reconciles_when_owner_registered_but_silent(db):
    # Registered row exists but the worker is not heartbeating (no telemetry). It must
    # NOT count as live just because a DB row lingers — that was the original bug.
    await _seed_worker("w1")  # no telemetry seeded
    await _seed_acked("g1", owner="w1")
    assert await sweep_orphaned_acked() == 1
    assert await _state("g1") == GranuleState.DELETED.value


async def test_reconciles_force_removed_acked(db):
    # force-remove set the object's deleted_at but left the granule ACKED; the
    # /deletable poll can never pick it up again → orphan caught by the backstop.
    await _seed_worker("w1", removed=True)
    await _seed_acked("g1", owner="w1", object_deleted=True)
    assert await sweep_orphaned_acked() == 1
    assert await _state("g1") == GranuleState.DELETED.value


async def test_skips_when_owner_live(db):
    # Fresh telemetry despite a stale DB last_seen — proves liveness reads telemetry,
    # so the live owner is left to clean up (and free real disk) itself.
    await _seed_worker("w1", heartbeat_age_sec=5)
    await _seed_acked("g1", owner="w1")
    assert await sweep_orphaned_acked() == 0
    assert await _state("g1") == GranuleState.ACKED.value
    assert await _delivered() == 0


async def test_grace_zero_treats_registered_as_live(db, patch_settings):
    # grace<=0 ignores telemetry: any non-removed registered worker is "live".
    patch_settings(acked_orphan_grace_sec=0)
    await _seed_worker("w1")  # registered, no telemetry, stale DB last_seen
    await _seed_acked("g1", owner="w1")
    assert await sweep_orphaned_acked() == 0
    assert await _state("g1") == GranuleState.ACKED.value


async def test_cold_start_holds_off(db, monkeypatch):
    # Process just started: telemetry is empty, so a not-yet-reported live worker would
    # look gone. The sweep must hold off entirely until uptime >= grace.
    monkeypatch.setattr(background, "_STARTED_AT", utcnow() - timedelta(seconds=30))
    await _seed_acked("g1", owner="ghost")  # would be an orphan if the sweep ran
    assert await sweep_orphaned_acked() == 0
    assert await _state("g1") == GranuleState.ACKED.value


async def test_skips_non_acked(db):
    await _seed_acked("g1", owner="ghost", state=GranuleState.UPLOADED.value)
    assert await sweep_orphaned_acked() == 0
    assert await _state("g1") == GranuleState.UPLOADED.value


def test_apply_orphan_reconcile_requires_acked():
    now = utcnow()
    with pytest.raises(StateConflict):
        apply(
            GranuleSnapshot(state=GranuleState.UPLOADED, updated_at=now),
            ReconcileOrphanDeleted(granule_id="g"),
            now=now,
            max_retries=3,
        )
    r = apply(
        GranuleSnapshot(state=GranuleState.ACKED, updated_at=now),
        ReconcileOrphanDeleted(granule_id="g"),
        now=now,
        max_retries=3,
    )
    assert r.new_state == GranuleState.DELETED
    assert r.objects_deleted_at is not None  # routes through the counted delete path
