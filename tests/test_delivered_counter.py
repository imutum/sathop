"""Persistent per-batch delivered counter (Batch.delivered_count).

Replaces COUNTing state='deleted' rows on the read path. The counter is bumped
once per DeleteConfirmed; a re-sent delete on an already-deleted granule must NOT
double it. Read models (admin overview, per-batch state_counts) source 'deleted'
from the counter, never from a row scan. The one-shot backfill seeds the counter
from existing deleted rows the first boot the column appears.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.admin_readmodels import admin_overview
from sathop.orchestrator.api.batch_readmodels import state_counts
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


async def _seed_uploaded_acked(granule_id: str = "g1", worker_id: str = "w1") -> None:
    """A granule in UPLOADED with one acked object — the DeleteConfirmed precondition."""
    async with orch_db._session_maker() as s:
        if await s.get(Batch, "b") is None:
            s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=granule_id,
                batch_id="b",
                state=GranuleState.UPLOADED.value,
                inputs=[],
            )
        )
        s.add(
            GranuleObject(
                granule_id=granule_id,
                worker_id=worker_id,
                object_key="out.tif",
                presigned_url="http://w/out.tif",
                sha256="0" * 64,
                size=100,
                acked_at=utcnow(),
                acked_by="r1",
            )
        )
        await s.commit()


def _delete_payload(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {
        "kind": "delete_confirmed",
        "granule_id": granule_id,
        "worker_id": worker_id,
        "object_keys": ["out.tif"],
    }


async def _delivered(batch_id: str = "b") -> int:
    async with orch_db._session_maker() as s:
        return (await s.get(Batch, batch_id)).delivered_count or 0


async def test_delete_confirmed_increments_counter(client):
    await _seed_uploaded_acked()
    r = client.post("/api/workers/events", json=_delete_payload())
    assert r.status_code == 200, r.text
    assert r.json()["state"] == GranuleState.DELETED.value
    assert await _delivered() == 1


async def test_resent_delete_does_not_double_count(client):
    """The double-count guard: a re-sent delete on an already-deleted granule
    still returns DELETED but must NOT bump the counter again."""
    await _seed_uploaded_acked()
    assert client.post("/api/workers/events", json=_delete_payload()).status_code == 200
    assert await _delivered() == 1
    # Re-send — apply() has no predecessor check for DeleteConfirmed.
    assert client.post("/api/workers/events", json=_delete_payload()).status_code == 200
    assert await _delivered() == 1


async def test_read_models_source_deleted_from_counter(client):
    """admin overview + per-batch state_counts report 'deleted' from the counter,
    not from scanning deleted rows."""
    await _seed_uploaded_acked()
    client.post("/api/workers/events", json=_delete_payload())
    async with orch_db._session_maker() as s:
        overview = await admin_overview(s, now=utcnow())
        assert overview["state_counts"]["deleted"] == 1
        per_batch = await state_counts(s, ["b"])
        assert per_batch["b"]["deleted"] == 1


async def test_counter_independent_of_deleted_rows(client):
    """The cumulative count survives pruning of deleted rows: bump the counter,
    then drop the deleted granule — overview still reports the cumulative total."""
    await _seed_uploaded_acked()
    client.post("/api/workers/events", json=_delete_payload())
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        await s.delete(g)
        await s.commit()
    async with orch_db._session_maker() as s:
        overview = await admin_overview(s, now=utcnow())
        assert overview["state_counts"]["deleted"] == 1


async def test_one_shot_backfill_seeds_existing_deleted_rows(tmp_path, patch_settings):
    """First boot after deploy: the column is created and seeded from the live
    deleted rows. Simulate by creating a DB without the column, inserting deleted
    granules, then re-init (which runs _ensure_columns)."""
    from sqlalchemy import text

    db_path = tmp_path / "backfill.db"
    patch_settings(db_path=db_path, token="")
    await orch_db.init_db()
    # Seed batches + deleted granules, then strip the column to emulate an old DB.
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="local:x"))
        s.add(Batch(batch_id="b2", name="t", bundle_ref="local:x"))
        for i in range(3):
            s.add(Granule(granule_id=f"b1:{i}", batch_id="b1", state=GranuleState.DELETED.value, inputs=[]))
        s.add(Granule(granule_id="b1:up", batch_id="b1", state=GranuleState.UPLOADED.value, inputs=[]))
        s.add(Granule(granule_id="b2:0", batch_id="b2", state=GranuleState.DELETED.value, inputs=[]))
        await s.commit()
    async with orch_db._engine.begin() as conn:
        await conn.execute(text("ALTER TABLE batches DROP COLUMN delivered_count"))
    await orch_db.shutdown_db()

    # Re-init: create_all + _ensure_columns re-adds the column and seeds it once.
    await orch_db.init_db()
    try:
        async with orch_db._session_maker() as s:
            assert (await s.get(Batch, "b1")).delivered_count == 3
            assert (await s.get(Batch, "b2")).delivered_count == 1
    finally:
        await orch_db.shutdown_db()


async def test_overview_cache_single_flight(client):
    """The 1s TTL cache collapses rapid overview calls onto one snapshot — a new
    delete between two calls within the window is not visible until reset/expiry."""
    from sathop.orchestrator.api.admin import reset_overview_cache

    await _seed_uploaded_acked("g1")
    reset_overview_cache()
    first = client.get("/api/admin/overview").json()
    assert first["state_counts"].get("deleted", 0) == 0
    # Deliver one, then hit overview again inside the TTL window → cached (stale).
    client.post("/api/workers/events", json=_delete_payload("g1"))
    cached = client.get("/api/admin/overview").json()
    assert cached["state_counts"].get("deleted", 0) == 0
    # After reset the fresh value shows.
    reset_overview_cache()
    fresh = client.get("/api/admin/overview").json()
    assert fresh["state_counts"]["deleted"] == 1
