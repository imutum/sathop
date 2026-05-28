"""Granule progress ingress + timeline query — in-memory store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.progress import _clear as clear_progress, evict_granule
from sathop.orchestrator.db import Batch, Granule
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture(autouse=True)
def _isolate_progress():
    yield
    clear_progress()


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
    )
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
                inputs=[],
            )
        )
        await s.commit()


async def test_ingress_stores_in_memory(client):
    await _seed_batch_and_granule("b1", "g1")
    r = client.post(
        "/api/granules/g1/progress",
        json={"step": "read", "pct": 20, "detail": "loading hdf", "batch_id": "b1"},
    )
    assert r.status_code == 200

    r = client.get("/api/granules/g1/progress")
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["granule_id"] == "g1"
    assert rows[0]["batch_id"] == "b1"
    assert rows[0]["step"] == "read"
    assert rows[0]["pct"] == 20
    assert rows[0]["detail"] == "loading hdf"


async def test_ingress_without_batch_id_still_works(client):
    r = client.post("/api/granules/g1/progress", json={"step": "read"})
    assert r.status_code == 200
    rows = client.get("/api/granules/g1/progress").json()
    assert len(rows) == 1
    assert rows[0]["batch_id"] == ""


async def test_timeline_returns_rows_in_insertion_order(client):
    for step, pct in [("a", 10), ("b", 50), ("c", 90)]:
        client.post("/api/granules/g1/progress", json={"step": step, "pct": pct, "batch_id": "b1"})

    r = client.get("/api/granules/g1/progress")
    assert r.status_code == 200
    rows = r.json()
    assert [row["step"] for row in rows] == ["a", "b", "c"]
    assert [row["pct"] for row in rows] == [10, 50, 90]


async def test_batch_latest_returns_last_row_per_granule(client):
    client.post("/api/granules/g1/progress", json={"step": "a", "batch_id": "b1"})
    client.post("/api/granules/g1/progress", json={"step": "b", "batch_id": "b1"})
    client.post("/api/granules/g1/progress", json={"step": "c", "batch_id": "b1"})
    client.post("/api/granules/g2/progress", json={"step": "x", "batch_id": "b1"})

    r = client.get("/api/batches/b1/progress/latest")
    assert r.status_code == 200
    latest = r.json()
    assert set(latest.keys()) == {"g1", "g2"}
    assert latest["g1"]["step"] == "c"
    assert latest["g2"]["step"] == "x"


async def test_batch_latest_unknown_batch_returns_empty(client):
    r = client.get("/api/batches/nope/progress/latest")
    assert r.status_code == 200
    assert r.json() == {}


async def test_evict_clears_progress(client):
    client.post("/api/granules/g1/progress", json={"step": "a", "batch_id": "b1"})
    assert len(client.get("/api/granules/g1/progress").json()) == 1
    evict_granule("g1", "b1")
    assert len(client.get("/api/granules/g1/progress").json()) == 0
    assert client.get("/api/batches/b1/progress/latest").json() == {}
