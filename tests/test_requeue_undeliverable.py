"""POST /api/admin/requeue-undeliverable.

Re-queues UPLOADED granules whose objects exhausted their pull retries (receiver
gave up — typically the hosting worker lost the output files on restart). Each
resets to PENDING (no retry penalty) and its dead object rows are dropped, so the
re-download/process/upload starts clean. Pullable / non-uploaded granules are left
untouched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleObject
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed(
    gid: str, *, batch_id: str = "b", failed_pulls: int, state: str = GranuleState.UPLOADED.value
):
    async with orch_db._session_maker() as s:
        if await s.get(Batch, batch_id) is None:
            s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        s.add(Granule(granule_id=gid, batch_id=batch_id, state=state, inputs=[]))
        s.add(
            GranuleObject(
                granule_id=gid,
                worker_id="w1",
                object_key="o.tif",
                presigned_url="http://w/o",
                sha256="0" * 64,
                size=1,
                failed_pulls=failed_pulls,
            )
        )
        await s.commit()


async def test_requeue_resets_exhausted_uploaded(client):
    await _seed("g1", failed_pulls=settings.max_pull_failures)
    r = client.post("/api/admin/requeue-undeliverable")
    assert r.status_code == 200, r.text
    assert r.json()["requeued"] == 1
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.PENDING.value
        assert g.leased_by is None
        assert g.retry_count == 0  # redelivery, not a failure — no retry penalty
        objs = (
            (await s.execute(select(GranuleObject).where(GranuleObject.granule_id == "g1"))).scalars().all()
        )
        assert objs == []  # dead object rows dropped


async def test_requeue_skips_pullable(client):
    await _seed("g1", failed_pulls=0)  # below max_pull_failures → still pullable
    assert client.post("/api/admin/requeue-undeliverable").json()["requeued"] == 0
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.UPLOADED.value


async def test_requeue_skips_non_uploaded(client):
    await _seed("g1", failed_pulls=settings.max_pull_failures, state=GranuleState.DOWNLOADING.value)
    assert client.post("/api/admin/requeue-undeliverable").json()["requeued"] == 0
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.DOWNLOADING.value


async def test_requeue_batch_scope(client):
    await _seed("g1", batch_id="b1", failed_pulls=settings.max_pull_failures)
    await _seed("g2", batch_id="b2", failed_pulls=settings.max_pull_failures)
    assert client.post("/api/admin/requeue-undeliverable?batch_id=b1").json()["requeued"] == 1
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.PENDING.value
        assert (await s.get(Granule, "g2")).state == GranuleState.UPLOADED.value  # other batch untouched
