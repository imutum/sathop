"""reap_granules: the single granule-children cascade used by both
delete_batch and the retention sweeper. Verifies children-before-parent
deletion is scoped to the given ids and reports accurate rowcounts."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import (
    Batch,
    Granule,
    GranuleObject,
    GranuleStageTiming,
    utcnow,
)
from sathop.orchestrator.reaping import reap_granules
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def session_maker(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db")
    await orch_db.init_db()
    try:
        yield orch_db._session_maker
    finally:
        await orch_db.shutdown_db()


def _granule(gid: str) -> Granule:
    return Granule(granule_id=gid, batch_id="b", state=GranuleState.UPLOADED.value, inputs=[])


def _object(gid: str) -> GranuleObject:
    return GranuleObject(
        granule_id=gid, worker_id="w", object_key=f"{gid}/o", presigned_url="u", sha256="s", size=1
    )


def _timing(gid: str) -> GranuleStageTiming:
    now = utcnow()
    return GranuleStageTiming(
        granule_id=gid, batch_id="b", stage="download", started_at=now, finished_at=now, duration_ms=1
    )


async def test_reaps_target_and_children_only(session_maker):
    async with session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        for gid in ("g1", "g2"):
            s.add(_granule(gid))
            s.add(_object(gid))
            s.add(_timing(gid))
        await s.commit()

    async with session_maker() as s:
        counts = await reap_granules(s, ["g1"])
        await s.commit()

    assert counts == {"objects": 1, "stage_timings": 1, "granules": 1}

    async with session_maker() as s:
        assert (await s.execute(select(func.count(Granule.granule_id)))).scalar_one() == 1
        assert (await s.execute(select(func.count(GranuleObject.id)))).scalar_one() == 1
        assert (await s.execute(select(func.count(GranuleStageTiming.id)))).scalar_one() == 1
        survivor = (await s.execute(select(Granule.granule_id))).scalar_one()
        assert survivor == "g2"


async def test_reaps_many_granules(session_maker):
    async with session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        for gid in ("g1", "g2", "g3"):
            s.add(_granule(gid))
            s.add(_object(gid))
        await s.commit()

    async with session_maker() as s:
        counts = await reap_granules(s, ["g1", "g2", "g3"])
        await s.commit()

    assert counts == {"objects": 3, "stage_timings": 0, "granules": 3}
    async with session_maker() as s:
        assert (await s.execute(select(func.count(Granule.granule_id)))).scalar_one() == 0


async def test_empty_input_is_noop(session_maker):
    async with session_maker() as s:
        counts = await reap_granules(s, [])
    assert counts == {"objects": 0, "stage_timings": 0, "granules": 0}
