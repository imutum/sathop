"""BatchSummary now carries an authoritative `objects_exhausted` count so the
batches list / detail can flag stuck-delivery batches without paging through
the granules endpoint (which caps at 200 rows).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleObject
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "max_pull_failures", 3)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_batch(batch_id: str, *, exhausted: int = 0, healthy: int = 0, acked: int = 0) -> None:
    """Seed one batch with N exhausted (failed_pulls >= cap), N healthy
    (failed_pulls < cap), and N acked (acked_at set) objects under one granule.
    Granule lives in UPLOADED state so the predicate's other branches are
    valid (state isn't part of the exhausted predicate, but objects need a
    parent granule)."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name="t", bundle_ref="orch:x@1"))
        gid = f"{batch_id}:g"
        s.add(Granule(granule_id=gid, batch_id=batch_id, state=GranuleState.UPLOADED.value, inputs_json="[]"))
        for i in range(exhausted):
            s.add(
                GranuleObject(
                    granule_id=gid,
                    worker_id="w1",
                    object_key=f"{batch_id}/g/exh{i}.bin",
                    presigned_url="http://w1/x",
                    sha256="a",
                    size=10,
                    failed_pulls=settings.max_pull_failures,
                )
            )
        for i in range(healthy):
            s.add(
                GranuleObject(
                    granule_id=gid,
                    worker_id="w1",
                    object_key=f"{batch_id}/g/ok{i}.bin",
                    presigned_url="http://w1/x",
                    sha256="a",
                    size=10,
                    failed_pulls=settings.max_pull_failures - 1,
                )
            )
        for i in range(acked):
            s.add(
                GranuleObject(
                    granule_id=gid,
                    worker_id="w1",
                    object_key=f"{batch_id}/g/ack{i}.bin",
                    presigned_url="http://w1/x",
                    sha256="a",
                    size=10,
                    failed_pulls=settings.max_pull_failures,
                    acked_at=orch_db.utcnow(),
                    acked_by="r1",
                )
            )
        await s.commit()


async def test_detail_returns_exhausted_count(client):
    await _seed_batch("b", exhausted=4, healthy=2, acked=1)
    r = client.get("/api/batches/b")
    assert r.status_code == 200
    body = r.json()
    # Healthy excluded (under cap); acked excluded (already delivered).
    assert body["objects_exhausted"] == 4


async def test_detail_returns_zero_when_nothing_stuck(client):
    await _seed_batch("b", healthy=10)
    body = client.get("/api/batches/b").json()
    assert body["objects_exhausted"] == 0


async def test_list_returns_exhausted_per_batch(client):
    await _seed_batch("a", exhausted=3)
    await _seed_batch("b", exhausted=1, acked=2)
    await _seed_batch("c", healthy=5)
    rows = client.get("/api/batches").json()
    by_id = {r["batch_id"]: r for r in rows}
    assert by_id["a"]["objects_exhausted"] == 3
    assert by_id["b"]["objects_exhausted"] == 1
    assert by_id["c"]["objects_exhausted"] == 0


async def test_summary_field_present_even_with_no_objects(client):
    """A batch with granules but no objects yet still returns the field as 0,
    not missing — the UI's badge logic relies on `> 0` to render."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(Granule(granule_id="b:g", batch_id="b", state=GranuleState.PENDING.value, inputs_json="[]"))
        await s.commit()

    body = client.get("/api/batches/b").json()
    assert "objects_exhausted" in body
    assert body["objects_exhausted"] == 0


async def test_reset_endpoint_zeros_summary_count(client):
    """Batch-level reset action should be reflected in the summary on next read."""
    await _seed_batch("b", exhausted=3)
    assert client.get("/api/batches/b").json()["objects_exhausted"] == 3
    client.post("/api/batches/b/reset-exhausted-objects")
    assert client.get("/api/batches/b").json()["objects_exhausted"] == 0
