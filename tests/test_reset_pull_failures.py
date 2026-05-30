"""POST /api/admin/reset-pull-failures.

Zeroes failed_pulls on still-pending objects that hit the cap, re-offering them to
the receiver WITHOUT redownloading (the worker still holds the bytes). Unlike
requeue-undeliverable, the object rows and granule state are left intact.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleObject, utcnow
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


async def _seed(gid: str, *, batch_id: str = "b", failed_pulls: int, acked: bool = False):
    async with orch_db._session_maker() as s:
        if await s.get(Batch, batch_id) is None:
            s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        s.add(Granule(granule_id=gid, batch_id=batch_id, state=GranuleState.UPLOADED.value, inputs=[]))
        s.add(
            GranuleObject(
                granule_id=gid,
                worker_id="w1",
                object_key="o.tif",
                presigned_url="http://w/o",
                sha256="0" * 64,
                size=1,
                failed_pulls=failed_pulls,
                acked_at=utcnow() if acked else None,
            )
        )
        await s.commit()


async def _failed_pulls(gid: str) -> int:
    async with orch_db._session_maker() as s:
        obj = (await s.execute(select(GranuleObject).where(GranuleObject.granule_id == gid))).scalar_one()
        return obj.failed_pulls


async def test_reset_clears_exhausted(client):
    await _seed("g1", failed_pulls=settings.max_pull_failures)
    r = client.post("/api/admin/reset-pull-failures")
    assert r.status_code == 200, r.text
    assert r.json()["reset"] == 1
    assert await _failed_pulls("g1") == 0  # re-offered, row + granule untouched
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.UPLOADED.value


async def test_reset_skips_still_pullable(client):
    await _seed("g1", failed_pulls=settings.max_pull_failures - 1)  # below cap
    assert client.post("/api/admin/reset-pull-failures").json()["reset"] == 0
    assert await _failed_pulls("g1") == settings.max_pull_failures - 1


async def test_reset_skips_acked(client):
    """Acked objects are no longer pending — resetting them would wrongly re-offer
    already-delivered bytes."""
    await _seed("g1", failed_pulls=settings.max_pull_failures, acked=True)
    assert client.post("/api/admin/reset-pull-failures").json()["reset"] == 0
    assert await _failed_pulls("g1") == settings.max_pull_failures


async def test_reset_batch_scope(client):
    await _seed("g1", batch_id="b1", failed_pulls=settings.max_pull_failures)
    await _seed("g2", batch_id="b2", failed_pulls=settings.max_pull_failures)
    assert client.post("/api/admin/reset-pull-failures?batch_id=b1").json()["reset"] == 1
    assert await _failed_pulls("g1") == 0
    assert await _failed_pulls("g2") == settings.max_pull_failures  # other batch untouched
