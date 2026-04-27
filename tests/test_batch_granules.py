"""GET /api/batches/{bid}/granules: listing, state filter, pagination."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, utcnow
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


async def _seed(rows: list[tuple[str, str, int]]):
    """(granule_id, state, updated_minutes_ago)."""
    now = utcnow()
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="n", bundle_ref="local:x"))
        for gid, state, ago in rows:
            s.add(
                Granule(
                    granule_id=gid,
                    batch_id="b",
                    state=state,
                    inputs_json="[]",
                    updated_at=now - timedelta(minutes=ago),
                )
            )
        await s.commit()


async def test_list_returns_all_granules(client):
    await _seed(
        [
            ("g1", GranuleState.PENDING.value, 10),
            ("g2", GranuleState.FAILED.value, 5),
            ("g3", GranuleState.ACKED.value, 1),
        ]
    )
    r = client.get("/api/batches/b/granules")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    # Most recent first
    assert [g["granule_id"] for g in data] == ["g3", "g2", "g1"]
    # Fields present
    assert set(data[0].keys()) >= {
        "granule_id",
        "batch_id",
        "state",
        "retry_count",
        "leased_by",
        "error",
        "updated_at",
    }


async def test_list_filters_by_single_state(client):
    await _seed(
        [
            ("g1", GranuleState.PENDING.value, 5),
            ("g2", GranuleState.FAILED.value, 3),
            ("g3", GranuleState.BLACKLISTED.value, 1),
        ]
    )
    r = client.get("/api/batches/b/granules?state=failed")
    assert r.status_code == 200
    data = r.json()
    assert [g["granule_id"] for g in data] == ["g2"]


async def test_list_filters_by_multiple_states_csv(client):
    await _seed(
        [
            ("g1", GranuleState.PENDING.value, 5),
            ("g2", GranuleState.FAILED.value, 3),
            ("g3", GranuleState.BLACKLISTED.value, 1),
        ]
    )
    r = client.get("/api/batches/b/granules?state=failed,blacklisted")
    assert r.status_code == 200
    ids = {g["granule_id"] for g in r.json()}
    assert ids == {"g2", "g3"}


async def test_list_pagination(client):
    rows = [(f"g{i:03d}", GranuleState.PENDING.value, i) for i in range(50)]
    await _seed(rows)
    r1 = client.get("/api/batches/b/granules?limit=10")
    r2 = client.get("/api/batches/b/granules?limit=10&offset=10")
    assert len(r1.json()) == 10
    assert len(r2.json()) == 10
    ids1 = {g["granule_id"] for g in r1.json()}
    ids2 = {g["granule_id"] for g in r2.json()}
    assert ids1.isdisjoint(ids2)


async def test_list_missing_batch_404(client):
    r = client.get("/api/batches/nope/granules")
    assert r.status_code == 404


async def test_list_empty_batch_returns_empty_array(client):
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="n", bundle_ref="local:x"))
        await s.commit()
    r = client.get("/api/batches/b/granules")
    assert r.status_code == 200
    assert r.json() == []
