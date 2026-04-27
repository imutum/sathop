"""Retention sweeper: old events + aged-out DELETED granules get pruned;
recent rows stay. Exercises the module against a real temp-file SQLite DB."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import background as retention
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Event, Granule, GranuleObject, utcnow
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def orch_session(tmp_path):
    """Spin up an isolated orchestrator SQLite for one test. Settings is a frozen
    dataclass, so db_path is patched via object.__setattr__ (safe: test-only)."""
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    await orch_db.init_db()
    try:
        yield orch_db._session_maker
    finally:
        await orch_db.shutdown_db()


async def test_prunes_old_events_keeps_recent(orch_session):
    now = utcnow()
    async with orch_session() as s:
        s.add(Event(ts=now - timedelta(days=30), source="t", message="old"))
        s.add(Event(ts=now - timedelta(days=1), source="t", message="new"))
        await s.commit()

    counts = await retention.sweep_retention(events_days=7, deleted_days=0)
    assert counts["events"] == 1
    assert counts["granules"] == 0

    async with orch_session() as s:
        remaining = (await s.execute(Event.__table__.select())).all()
        assert len(remaining) == 1
        assert remaining[0].message == "new"


async def test_prunes_aged_deleted_granules_and_objects(orch_session):
    now = utcnow()
    old = now - timedelta(days=30)
    recent = now - timedelta(days=1)

    async with orch_session() as s:
        s.add(Batch(batch_id="b1", name="n", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id="g_old",
                batch_id="b1",
                state=GranuleState.DELETED.value,
                inputs_json="[]",
                updated_at=old,
            )
        )
        s.add(
            GranuleObject(
                granule_id="g_old",
                worker_id="w",
                object_key="k1",
                presigned_url="u",
                sha256="s",
                size=1,
                deleted_at=old,
            )
        )
        s.add(
            Granule(
                granule_id="g_recent",
                batch_id="b1",
                state=GranuleState.DELETED.value,
                inputs_json="[]",
                updated_at=recent,
            )
        )
        # Old but still acked (not deleted) → kept
        s.add(
            Granule(
                granule_id="g_acked",
                batch_id="b1",
                state=GranuleState.ACKED.value,
                inputs_json="[]",
                updated_at=old,
            )
        )
        await s.commit()

    counts = await retention.sweep_retention(events_days=0, deleted_days=7)
    assert counts["granules"] == 1
    assert counts["granule_objects"] == 1

    async with orch_session() as s:
        ids = sorted(
            r[0]
            for r in (await s.execute(Granule.__table__.select().with_only_columns(Granule.granule_id))).all()
        )
        assert ids == ["g_acked", "g_recent"]
        assert len((await s.execute(GranuleObject.__table__.select())).all()) == 0


async def test_zero_retention_days_skips_prune(orch_session):
    async with orch_session() as s:
        s.add(Event(ts=utcnow() - timedelta(days=365), source="t", message="ancient"))
        await s.commit()

    counts = await retention.sweep_retention(events_days=0, deleted_days=0)
    assert counts == {"events": 0, "granule_objects": 0, "granules": 0}

    async with orch_session() as s:
        assert len((await s.execute(Event.__table__.select())).all()) == 1
