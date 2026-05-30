"""Multi-process (route A) building blocks: the Redis-backed ephemeral stores,
cross-process pub/sub fan-out, the background-task leader lock, and the atomic
lease claim that replaces the in-process lock.

Redis is faked (fakeredis, shared FakeServer for sync+async on one keyspace), so
these run without a real server. The in-memory path is covered by the rest of
the suite running with redis disabled.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import fakeredis
import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store, redis_bus, telemetry
from sathop.orchestrator.api import progress
from sathop.orchestrator.api.worker_leases import claim_pending_granules
from sathop.orchestrator.db import Batch, Granule, utcnow
from sathop.orchestrator.telemetry import ReceiverTelemetry, WorkerTelemetry
from sathop.shared.protocol import ProgressEvent
from sathop.shared.state_machine import GranuleState


@pytest.fixture
def redis_on(monkeypatch):
    """Wire fakeredis into redis_bus and force enabled() True for one test."""
    server = fakeredis.FakeServer()
    sync = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    aio = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    monkeypatch.setattr(redis_bus, "_sync", sync)
    monkeypatch.setattr(redis_bus, "_async", aio)
    monkeypatch.setattr(redis_bus, "enabled", lambda: True)
    yield server
    sync.flushall()


# ── events ────────────────────────────────────────────────────────────────


def test_events_redis_roundtrip(redis_on):
    now = utcnow()
    i1 = event_store.append(ts=now, level="info", source="w", message="a", granule_id="g1", batch_id="b1")
    i2 = event_store.append(ts=now, level="warn", source="w", message="b", granule_id="g2", batch_id="b1")
    i3 = event_store.append(ts=now, level="info", source="x", message="c", granule_id="g1", batch_id="b1")
    assert i1 < i2 < i3  # INCR ids preserve the int since_id contract

    # newest-first, since_id pagination
    rows = event_store.query(limit=10)
    assert [r["id"] for r in rows] == [i3, i2, i1]
    assert [r["id"] for r in event_store.query(since_id=i1)] == [i3, i2]

    # filters
    assert [r["id"] for r in event_store.query(level="warn")] == [i2]
    assert {r["id"] for r in event_store.query(granule_id="g1")} == {i1, i3}

    assert event_store.last_n(2) == event_store.query(limit=2)
    assert event_store.count_by_level_since(now - timedelta(minutes=1)) == {"info": 2, "warn": 1}

    # evict by granule, then prune by ts
    assert event_store.evict_by_granule_ids({"g1"}) == 2
    assert [r["id"] for r in event_store.query()] == [i2]
    event_store.append(ts=now - timedelta(days=40), level="info", source="w", message="old")
    assert event_store.prune_before(now - timedelta(days=1)) == 1


def test_redis_reads_are_bounded(redis_on, monkeypatch):
    """The read paths must scan a bounded window, never the whole list — the
    regression that saturated Redis and stalled the event loop was last_n/query
    pulling all 20k entries every call."""
    monkeypatch.setattr(event_store, "_SCAN_CAP", 5)
    now = utcnow()
    # Oldest event carries a rare source; it sits beyond the scan cap from head.
    event_store.append(ts=now, level="info", source="rare", message="oldest")
    for i in range(10):
        event_store.append(ts=now, level="info", source="common", message=f"e{i}")
    # query scans only the newest _SCAN_CAP entries → never reaches the rare one.
    assert event_store.query(source="rare") == []
    assert len(event_store.query(source="common", limit=100)) == 5
    # last_n is bounded by its own n regardless of list length.
    assert len(event_store.last_n(3)) == 3


# ── telemetry ───────────────────────────────────────────────────────────────


def test_telemetry_redis_roundtrip(redis_on):
    t = WorkerTelemetry(last_seen=utcnow(), cpu_percent=42.0, queue_processing=3)
    telemetry.update_worker("w1", t)
    got = telemetry.get_worker("w1")
    assert got is not None and got.cpu_percent == 42.0 and got.queue_processing == 3
    assert got.last_seen == t.last_seen  # datetime round-trips through isoformat

    rt = ReceiverTelemetry(last_seen=utcnow(), queue_pulling=7)
    telemetry.update_receiver("r1", rt)
    assert telemetry.get_receiver("r1").queue_pulling == 7

    telemetry.evict_worker("w1")
    assert telemetry.get_worker("w1") is None


def test_worker_snapshot_prefers_redis_telemetry(redis_on):
    class FakeRow:
        worker_id = "w9"
        last_seen = utcnow()
        disk_used_gb = disk_total_gb = cpu_percent = mem_percent = monthly_egress_gb = 0.0
        queue_pending_download = queue_downloading = queue_pending_processing = 0
        queue_processing = queue_pending_upload = queue_uploading = 0
        paused = False

    telemetry.update_worker("w9", WorkerTelemetry(last_seen=utcnow(), cpu_percent=55.5))
    snap = telemetry.worker_snapshot(FakeRow())
    assert snap["cpu_percent"] == 55.5  # live telemetry wins over the DB row


# ── progress ──────────────────────────────────────────────────────────────


async def test_progress_redis_roundtrip(redis_on):
    await progress.ingress("g1", ProgressEvent(batch_id="b1", step="download", pct=10.0, detail="x"))
    await progress.ingress("g1", ProgressEvent(batch_id="b1", step="download", pct=50.0, detail="y"))
    timeline = await progress.granule_timeline("g1")
    assert [e["pct"] for e in timeline] == [10.0, 50.0]

    latest = await progress.batch_latest("b1")
    assert latest["g1"]["pct"] == 50.0

    progress.evict_granule("g1")
    assert await progress.granule_timeline("g1") == []
    assert await progress.batch_latest("b1") == {}


# ── cross-process pub/sub ───────────────────────────────────────────────────


async def test_pubsub_fans_out_across_processes(redis_on):
    from sathop.orchestrator import pubsub

    listener = asyncio.create_task(pubsub.run_listener())
    await asyncio.sleep(0.1)  # let it SUBSCRIBE
    try:
        with pubsub.subscribe() as q:
            pubsub.publish({"scope": "batches"})  # sync PUBLISH → listener → local fan-out
            evt = await asyncio.wait_for(q.get(), timeout=2)
        assert evt == {"scope": "batches"}
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)


# ── leader lock ─────────────────────────────────────────────────────────────


async def test_leader_lock_single_holder(redis_on):
    assert await redis_bus.acquire_leader("ldr", "t1", 10_000) is True
    assert await redis_bus.acquire_leader("ldr", "t2", 10_000) is False  # t1 holds it
    assert await redis_bus.renew_leader("ldr", "t1", 10_000) is True
    assert await redis_bus.renew_leader("ldr", "t2", 10_000) is False  # not owner
    await redis_bus.release_leader("ldr", "t2")  # wrong owner → no-op
    assert await redis_bus.acquire_leader("ldr", "t2", 10_000) is False
    await redis_bus.release_leader("ldr", "t1")  # owner releases
    assert await redis_bus.acquire_leader("ldr", "t2", 10_000) is True  # now free


# ── atomic lease claim (no in-process lock) ─────────────────────────────────


@pytest.fixture
async def orch_session(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "lease.db")
    await orch_db.init_db()
    try:
        yield orch_db._session_maker
    finally:
        await orch_db.shutdown_db()


async def test_concurrent_claims_are_disjoint(orch_session):
    """Two concurrent /lease callers must split the PENDING set, never double-claim
    — the property the dropped _LEASE_LOCK used to enforce, now from the atomic
    UPDATE…RETURNING under SQLite's single writer."""
    now = utcnow()
    async with orch_session() as s:
        s.add(Batch(batch_id="b", name="n", bundle_ref="orch:x@1"))
        for i in range(20):
            s.add(Granule(granule_id=f"g{i}", batch_id="b", state=GranuleState.PENDING.value, inputs=[]))
        await s.commit()

    exp = now + timedelta(minutes=30)

    async def claim(worker):
        async with orch_session() as s:
            items = await claim_pending_granules(s, worker, 20, now, exp)
            await s.commit()
            return {it.granule_id for it in items}

    a, b = await asyncio.gather(claim("wa"), claim("wb"))
    assert not (a & b)  # disjoint — no granule leased to both
    assert len(a) + len(b) == 20  # and all claimed exactly once
    async with orch_session() as s:
        from sqlalchemy import func, select

        pending = await s.scalar(
            select(func.count()).select_from(Granule).where(Granule.state == GranuleState.PENDING.value)
        )
    assert pending == 0
