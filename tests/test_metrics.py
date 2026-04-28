"""Prometheus /api/metrics endpoint: seeds DB with a few rows, hits the endpoint
via FastAPI TestClient, asserts expected metric names and values appear."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Event, Granule, Receiver, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")  # disable auth for test
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def test_metrics_exposes_expected_series(client):
    now = utcnow()
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="n", bundle_ref="local:x", status="running"))
        s.add(Granule(granule_id="g1", batch_id="b1", state=GranuleState.PENDING.value, inputs_json="[]"))
        s.add(Granule(granule_id="g2", batch_id="b1", state=GranuleState.PROCESSING.value, inputs_json="[]"))
        s.add(
            Granule(
                granule_id="g_stuck",
                batch_id="b1",
                state=GranuleState.PROCESSING.value,
                inputs_json="[]",
                updated_at=now - timedelta(hours=12),
            )
        )
        s.add(
            Worker(
                worker_id="w1",
                last_seen=now - timedelta(seconds=30),
                disk_used_gb=10.0,
                disk_total_gb=100.0,
                queue_processing=2,
            )
        )
        s.add(
            Receiver(
                receiver_id="r1",
                last_seen=now - timedelta(seconds=5),
                disk_free_gb=500.0,
                queue_pulling=4,
                recent_pull_bps=4096,
            )
        )
        s.add(Event(ts=now - timedelta(minutes=5), source="t", level="warn", message="recent"))
        s.add(Event(ts=now - timedelta(days=2), source="t", level="info", message="old"))  # outside 24h
        await s.commit()

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text

    # Granule state gauge emits a line per state (including zeros)
    assert 'sathop_granules{state="pending"} 1.0' in body
    assert 'sathop_granules{state="processing"} 2.0' in body
    assert 'sathop_granules{state="failed"} 0.0' in body

    # Stuck only processing >6h — g_stuck is 12h old
    assert 'sathop_granules_stuck{state="processing"} 1.0' in body
    assert 'sathop_granules_stuck{state="pending"} 0.0' in body

    # Worker heartbeat + disk ratio
    assert 'sathop_worker_heartbeat_age_seconds{worker_id="w1"}' in body
    assert 'sathop_worker_disk_used_ratio{worker_id="w1"} 0.1' in body
    assert 'sathop_worker_queue{stage="processing",worker_id="w1"} 2.0' in body

    # Receivers
    assert 'sathop_receivers{enabled="true"} 1.0' in body
    assert 'sathop_receiver_heartbeat_age_seconds{receiver_id="r1"}' in body
    assert 'sathop_receiver_queue_pulling{receiver_id="r1"} 4.0' in body
    assert 'sathop_receiver_throughput_bytes_per_second{receiver_id="r1"} 4096.0' in body

    # Events last 24h: warn=1, info=0 (the old one is outside window)
    assert 'sathop_events_24h{level="warn"} 1.0' in body
    assert 'sathop_events_24h{level="info"} 0.0' in body

    # Batch status
    assert 'sathop_batches{status="running"} 1.0' in body


async def test_metrics_requires_token_when_enabled(client):
    object.__setattr__(settings, "token", "secret123")
    try:
        r1 = client.get("/api/metrics")
        assert r1.status_code == 401
        r2 = client.get("/api/metrics", headers={"Authorization": "Bearer secret123"})
        assert r2.status_code == 200
        r3 = client.get("/api/metrics?token=secret123")
        assert r3.status_code == 200
    finally:
        object.__setattr__(settings, "token", "")
