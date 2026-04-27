"""Granule progress ingress + timeline query on the orchestrator side."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleProgress
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


async def _seed_batch_and_granule(batch_id: str, granule_id: str) -> None:
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=granule_id,
                batch_id=batch_id,
                state=GranuleState.PROCESSING.value,
                inputs_json="[]",
            )
        )
        await s.commit()


async def test_ingress_persists_row_and_backfills_batch_id(client):
    await _seed_batch_and_granule("b1", "g1")
    r = client.post(
        "/api/granules/g1/progress",
        json={"step": "read", "pct": 20, "detail": "loading hdf"},
    )
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        rows = (await s.execute(select(GranuleProgress))).scalars().all()
        assert len(rows) == 1
        assert rows[0].granule_id == "g1"
        assert rows[0].batch_id == "b1"  # denormalized
        assert rows[0].step == "read"
        assert rows[0].pct == 20
        assert rows[0].detail == "loading hdf"


async def test_ingress_unknown_granule_returns_404(client):
    r = client.post("/api/granules/nope/progress", json={"step": "read"})
    assert r.status_code == 404


async def test_ingress_rejects_malformed_body(client):
    await _seed_batch_and_granule("b1", "g1")
    # missing required "step"
    r = client.post("/api/granules/g1/progress", json={"pct": 10})
    assert r.status_code == 422


async def test_timeline_returns_rows_in_insertion_order(client):
    await _seed_batch_and_granule("b1", "g1")
    for step, pct in [("a", 10), ("b", 50), ("c", 90)]:
        client.post("/api/granules/g1/progress", json={"step": step, "pct": pct})

    r = client.get("/api/granules/g1/progress")
    assert r.status_code == 200
    rows = r.json()
    assert [row["step"] for row in rows] == ["a", "b", "c"]
    assert [row["pct"] for row in rows] == [10, 50, 90]


async def test_batch_latest_returns_last_row_per_granule(client):
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="local:x"))
        for gid in ("g1", "g2"):
            s.add(
                Granule(
                    granule_id=gid,
                    batch_id="b1",
                    state=GranuleState.PROCESSING.value,
                    inputs_json="[]",
                )
            )
        await s.commit()

    # g1: 3 steps, g2: 1 step
    client.post("/api/granules/g1/progress", json={"step": "a"})
    client.post("/api/granules/g1/progress", json={"step": "b"})
    client.post("/api/granules/g1/progress", json={"step": "c"})
    client.post("/api/granules/g2/progress", json={"step": "x"})

    r = client.get("/api/batches/b1/progress/latest")
    assert r.status_code == 200
    latest = r.json()
    assert set(latest.keys()) == {"g1", "g2"}
    assert latest["g1"]["step"] == "c"
    assert latest["g2"]["step"] == "x"


async def test_batch_latest_unknown_batch_404(client):
    r = client.get("/api/batches/nope/progress/latest")
    assert r.status_code == 404
