"""Postgres-backend tests — the paths the default SQLite suite can't exercise.

Skipped unless ``SATHOP_TEST_PG_URL`` points at a reachable Postgres (e.g.
``postgresql+asyncpg://box:box_secret@127.0.0.1:15432/sathop_test``). CI wires it
to a postgres service; locally point it at the dev container. Each test gets a
fresh schema (drop_all + create_all).

Covers: the Event-table read/write helpers' semantic equivalence with the
in-memory backend (ordering, filters, pagination, count, evict, prune) and the
concurrent lease-claim disjointness that ``FOR UPDATE SKIP LOCKED`` guarantees
across processes — the multi-process correctness the SQLite single-writer model
never tests.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store
from sathop.orchestrator.api.worker_leases import claim_pending_granules
from sathop.orchestrator.db import Base, Batch, Granule, utcnow
from sathop.orchestrator.pubsub import commit_and_publish, log_event
from sathop.shared.protocol import GranuleState

PG_URL = os.getenv("SATHOP_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set SATHOP_TEST_PG_URL to run the Postgres backend tests")

_KEYS = {"id", "ts", "level", "source", "granule_id", "batch_id", "message"}


@pytest.fixture
async def pg(patch_settings):
    patch_settings(database_url=PG_URL, token="")
    assert orch_db.is_postgres()
    await orch_db.init_db()
    async with orch_db._engine.begin() as conn:  # fresh schema per test
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield orch_db.get_session_maker()
    finally:
        await orch_db.shutdown_db()


async def test_event_write_read_filters(pg):
    sm = pg
    async with sm() as s:
        await log_event(s, "worker-w1", "lease 5", granule_id="g1", batch_id="b1")
        await log_event(s, "worker-w11", "other", level="warn")
        await log_event(s, "worker-w1", "done", granule_id="g1", batch_id="b1", level="error")
        await commit_and_publish(s)

    async with sm() as s:
        allev = await event_store.query_db(s, limit=100)
        assert [e["message"] for e in allev] == ["done", "other", "lease 5"]  # newest-first
        assert set(allev[0]) == _KEYS
        # source is exact-match, NOT a prefix: worker-w1 must not match worker-w11.
        assert {e["message"] for e in await event_store.query_db(s, source="worker-w1")} == {
            "lease 5",
            "done",
        }
        assert len(await event_store.query_db(s, source="worker-w11")) == 1
        assert len(await event_store.query_db(s, batch_id="b1")) == 2
        assert [e["message"] for e in await event_store.query_db(s, level="error")] == ["done"]
        # pagination: since_id → id > N (newer); before_id → id < N (older).
        ids = sorted(e["id"] for e in allev)
        assert len(await event_store.query_db(s, since_id=ids[0])) == 2
        assert len(await event_store.query_db(s, before_id=ids[-1])) == 2
        top = await event_store.query_db(s, limit=1)
        assert len(top) == 1 and top[0]["message"] == "done"


async def test_count_by_level_since(pg):
    sm = pg
    now = utcnow()
    async with sm() as s:
        event_store.append_event_row(s, ts=now - timedelta(days=2), source="t", message="old", level="info")
        event_store.append_event_row(
            s, ts=now - timedelta(minutes=5), source="t", message="recent", level="warn"
        )
        await s.commit()
    async with sm() as s:
        counts = await event_store.count_by_level_since_db(s, now - timedelta(hours=24))
        assert counts == {"warn": 1}  # the 2-day-old info event is outside the window


async def test_evict_and_prune(pg):
    sm = pg
    now = utcnow()
    async with sm() as s:
        event_store.append_event_row(s, ts=now, source="t", message="g1ev", level="info", granule_id="g1")
        event_store.append_event_row(s, ts=now, source="t", message="g2ev", level="info", granule_id="g2")
        event_store.append_event_row(
            s, ts=now - timedelta(days=40), source="t", message="ancient", level="info"
        )
        await s.commit()
    async with sm() as s:
        assert await event_store.evict_by_granule_ids_db(s, {"g1"}) == 1
        await s.commit()
    async with sm() as s:
        assert {e["message"] for e in await event_store.query_db(s)} == {"g2ev", "ancient"}
        assert await event_store.prune_before_db(s, now - timedelta(days=1)) == 1
        await s.commit()
    async with sm() as s:
        assert {e["message"] for e in await event_store.query_db(s)} == {"g2ev"}


async def test_concurrent_lease_claims_disjoint(pg):
    sm = pg
    now = utcnow()
    expires = now + timedelta(minutes=30)
    async with sm() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="x"))
        for i in range(100):
            s.add(Granule(granule_id=f"g{i}", batch_id="b", state=GranuleState.PENDING.value, inputs=[]))
        await s.commit()

    async def claim(wid: str) -> list[str]:
        async with sm() as s:
            items = await claim_pending_granules(s, wid, 60, now, expires)
            await s.commit()
            return [it.granule_id for it in items]

    a, b = await asyncio.gather(claim("wa"), claim("wb"))
    assert set(a).isdisjoint(set(b))  # FOR UPDATE SKIP LOCKED → no granule claimed twice
    assert len(a) + len(b) <= 100  # never over-claim past what's pending
    assert len(a) + len(b) >= 60  # together they drain a healthy chunk
