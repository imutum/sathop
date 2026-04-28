"""Hard-delete batch endpoint.

Cancel-then-delete is the supported workflow. The endpoint refuses by default
when any granule is still mid-flight on a worker (downloading / downloaded /
processing / processed) so a stop-the-world delete can't strand worker tasks
that would later 404 on state report. `?force=true` overrides; everything
referencing the batch is wiped (granules, objects, progress, timings, events).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import (
    Batch,
    Event,
    Granule,
    GranuleObject,
    GranuleProgress,
    GranuleStageTiming,
    utcnow,
)
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_full_batch(batch_id: str = "b") -> None:
    """Seed a batch with granules in two states + child rows in every table
    that references the granule, so the cascade actually has something to do.
    granule_ids are namespaced by batch to allow multi-batch seeding."""
    g1, g2 = f"{batch_id}:g1", f"{batch_id}:g2"
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name="t", bundle_ref="orch:x@1"))
        s.add(Granule(granule_id=g1, batch_id=batch_id, state=GranuleState.UPLOADED.value, inputs_json="[]"))
        s.add(Granule(granule_id=g2, batch_id=batch_id, state=GranuleState.ACKED.value, inputs_json="[]"))
        s.add(
            GranuleObject(
                granule_id=g1,
                worker_id="w1",
                object_key=f"{batch_id}/g1/out.bin",
                presigned_url="http://w1/x",
                sha256="abc",
                size=10,
            )
        )
        s.add(GranuleProgress(granule_id=g1, batch_id=batch_id, step="read", pct=50.0))
        now = utcnow()
        s.add(
            GranuleStageTiming(
                granule_id=g1,
                batch_id=batch_id,
                stage="download",
                started_at=now,
                finished_at=now,
                duration_ms=100,
            )
        )
        s.add(Event(level="info", source="x", granule_id=g1, message="hello"))
        await s.commit()


async def _counts() -> dict[str, int]:
    """Snapshot of every table that should be empty after a clean delete."""
    async with orch_db._session_maker() as s:
        from sqlalchemy import func, select

        return {
            "batches": (await s.execute(select(func.count(Batch.batch_id)))).scalar_one(),
            "granules": (await s.execute(select(func.count(Granule.granule_id)))).scalar_one(),
            "objects": (await s.execute(select(func.count(GranuleObject.id)))).scalar_one(),
            "progress": (await s.execute(select(func.count(GranuleProgress.id)))).scalar_one(),
            "timings": (await s.execute(select(func.count(GranuleStageTiming.id)))).scalar_one(),
            "events_with_gid": (
                await s.execute(select(func.count(Event.id)).where(Event.granule_id.is_not(None)))
            ).scalar_one(),
        }


async def test_delete_terminal_batch_cascades(client):
    await _seed_full_batch()
    r = client.request("DELETE", "/api/batches/b")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["granules"] == 2
    assert body["objects"] == 1
    assert body["progress"] == 1
    assert body["stage_timings"] == 1
    assert body["events"] == 1

    # Batch + every granule-scoped child row gone.
    counts = await _counts()
    assert counts["batches"] == 0
    assert counts["granules"] == 0
    assert counts["objects"] == 0
    assert counts["progress"] == 0
    assert counts["timings"] == 0
    assert counts["events_with_gid"] == 0


async def test_delete_missing_batch_404(client):
    r = client.request("DELETE", "/api/batches/no-such")
    assert r.status_code == 404


async def test_delete_inflight_batch_refused_without_force(client):
    """Mid-flight states (worker holds a lease) require explicit ?force=true."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b",
                state=GranuleState.PROCESSING.value,
                inputs_json="[]",
                leased_by="w1",
                lease_expires_at=utcnow(),
            )
        )
        await s.commit()

    r = client.request("DELETE", "/api/batches/b")
    assert r.status_code == 409
    assert "mid-flight" in r.json()["detail"]
    # Untouched.
    assert (await _counts())["batches"] == 1


async def test_delete_inflight_batch_with_force_succeeds(client):
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b",
                state=GranuleState.PROCESSING.value,
                inputs_json="[]",
                leased_by="w1",
                lease_expires_at=utcnow(),
            )
        )
        await s.commit()

    r = client.request("DELETE", "/api/batches/b?force=true")
    assert r.status_code == 200
    assert r.json()["granules"] == 1
    assert (await _counts())["batches"] == 0


async def test_delete_pending_batch_succeeds_without_force(client):
    """PENDING isn't mid-flight (no worker lease), so default delete works."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        await s.commit()

    r = client.request("DELETE", "/api/batches/b")
    assert r.status_code == 200
    assert r.json()["granules"] == 1


async def test_delete_does_not_touch_other_batches(client):
    """Cascade scoped to one batch — sibling batch's data must survive."""
    await _seed_full_batch("keep")
    await _seed_full_batch("drop")

    r = client.request("DELETE", "/api/batches/drop")
    assert r.status_code == 200

    counts = await _counts()
    assert counts["batches"] == 1
    assert counts["granules"] == 2
    assert counts["objects"] == 1
    assert counts["progress"] == 1
    assert counts["timings"] == 1
    assert counts["events_with_gid"] == 1
