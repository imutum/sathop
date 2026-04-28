"""Per-stage timing recording + query endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleStageTiming, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "max_inflight_per_worker", 0)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_worker_batch_granule(gid: str = "g1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="t", capacity=10, public_url=None))
        s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=gid,
                batch_id="b",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        await s.commit()


def _state(client, gid: str, state: str):
    return client.post(
        "/api/workers/state",
        json={"granule_id": gid, "worker_id": "w1", "state": state},
    )


def _full_lifecycle(client, gid: str = "g1") -> None:
    """Drive PENDING → UPLOADED through the public API."""
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.status_code == 200
    assert any(it["granule_id"] == gid for it in r.json()["items"])
    assert _state(client, gid, GranuleState.DOWNLOADED.value).status_code == 200
    assert _state(client, gid, GranuleState.PROCESSING.value).status_code == 200
    assert _state(client, gid, GranuleState.PROCESSED.value).status_code == 200
    r = client.post(
        "/api/workers/upload",
        json={"granule_id": gid, "worker_id": "w1", "objects": []},
    )
    assert r.status_code == 200, r.text


# ─── recording on the happy path ───────────────────────────────────────────


async def test_full_lifecycle_records_three_stages(client):
    await _seed_worker_batch_granule()
    _full_lifecycle(client)

    async with orch_db._session_maker() as s:
        rows = (await s.execute(select(GranuleStageTiming).order_by(GranuleStageTiming.id))).scalars().all()
    assert [r.stage for r in rows] == ["download", "process", "upload"]
    for r in rows:
        assert r.granule_id == "g1"
        assert r.batch_id == "b"
        assert r.duration_ms >= 0
        assert r.finished_at >= r.started_at


async def test_failure_records_only_completed_stages(client):
    """Worker downloads, reports DOWNLOADED, then fails before PROCESSING — only
    the download row should exist."""
    await _seed_worker_batch_granule()
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.status_code == 200
    assert _state(client, "g1", GranuleState.DOWNLOADED.value).status_code == 200
    r = client.post(
        "/api/workers/failure",
        json={"granule_id": "g1", "worker_id": "w1", "error": "boom", "exit_code": 1},
    )
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        rows = (await s.execute(select(GranuleStageTiming))).scalars().all()
    assert [r.stage for r in rows] == ["download"]


async def test_retry_records_each_attempt(client):
    """Two leases (after a failure) → two `download` rows."""
    await _seed_worker_batch_granule()

    # Attempt 1: fail before DOWNLOADED so no rows recorded.
    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.status_code == 200
    r = client.post(
        "/api/workers/failure",
        json={"granule_id": "g1", "worker_id": "w1", "error": "x", "exit_code": 1},
    )
    assert r.status_code == 200

    # Attempt 2: full lifecycle.
    _full_lifecycle(client)

    async with orch_db._session_maker() as s:
        rows = (await s.execute(select(GranuleStageTiming).order_by(GranuleStageTiming.id))).scalars().all()
    assert [r.stage for r in rows] == ["download", "process", "upload"]


# ─── /api/granules/{id}/timing ─────────────────────────────────────────────


async def test_granule_timing_endpoint_returns_rows(client):
    await _seed_worker_batch_granule()
    _full_lifecycle(client)

    r = client.get("/api/granules/g1/timing")
    assert r.status_code == 200
    rows = r.json()
    assert [x["stage"] for x in rows] == ["download", "process", "upload"]
    for x in rows:
        assert x["duration_ms"] >= 0
        assert "started_at" in x and "finished_at" in x


async def test_granule_timing_404_for_unknown(client):
    r = client.get("/api/granules/ghost/timing")
    assert r.status_code == 404


# ─── /api/batches/{id}/timing aggregate math ───────────────────────────────


async def _seed_timing_rows(rows: list[tuple[str, int]]) -> None:
    """(stage, duration_ms). Inserts under batch_id="b" / granule_id="g1"."""
    now = utcnow()
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(Granule(granule_id="g1", batch_id="b", state="acked", inputs_json="[]"))
        for stage, ms in rows:
            s.add(
                GranuleStageTiming(
                    granule_id="g1",
                    batch_id="b",
                    stage=stage,
                    started_at=now,
                    finished_at=now + timedelta(milliseconds=ms),
                    duration_ms=ms,
                )
            )
        await s.commit()


async def test_batch_timing_aggregates(client):
    """Hand-computed expected values on a small fixed dataset."""
    # download durations: 100, 200, 300, 400, 500 (avg=300, p50=300, p95=500, max=500)
    # process durations:  50, 150 (avg=100, p50=150 [nearest-rank], p95=150, max=150)
    # upload: empty
    await _seed_timing_rows(
        [("download", 100), ("download", 200), ("download", 300), ("download", 400), ("download", 500)]
        + [("process", 50), ("process", 150)]
    )
    r = client.get("/api/batches/b/timing")
    assert r.status_code == 200
    data = r.json()

    assert data["download"] == {"count": 5, "avg_ms": 300, "p50_ms": 300, "p95_ms": 500, "max_ms": 500}
    # nearest-rank percentiles on [50,150]: index = n*p/100 → p50=index 1 →150, p95=index 1 →150
    assert data["process"] == {"count": 2, "avg_ms": 100, "p50_ms": 150, "p95_ms": 150, "max_ms": 150}
    assert data["upload"] == {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}


async def test_batch_timing_404_for_unknown(client):
    r = client.get("/api/batches/ghost/timing")
    assert r.status_code == 404


async def test_batch_timing_empty_batch(client):
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        await s.commit()
    r = client.get("/api/batches/b/timing")
    assert r.status_code == 200
    for st in ("download", "process", "upload"):
        assert r.json()[st]["count"] == 0
