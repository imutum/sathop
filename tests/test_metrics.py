"""Dashboard cache integration and Prometheus contracts on both DB backends."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from prometheus_client.parser import text_string_to_metric_families

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store, telemetry
from sathop.orchestrator.api import admin, batches, metrics
from sathop.orchestrator.db import Batch, Event, Granule, Receiver, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.orchestrator.read_cache import AsyncTTLCache
from sathop.shared.protocol import GranuleState


@pytest.fixture(params=["sqlite", "postgres"])
async def client(tmp_path, patch_settings, request):
    url = os.getenv("SATHOP_TEST_PG_URL", "") if request.param == "postgres" else ""
    if request.param == "postgres" and not url:
        pytest.skip("SATHOP_TEST_PG_URL required")
    # Empty token disables auth so the test can hit /api/metrics directly.
    patch_settings(db_path=tmp_path / "test.db", database_url=url, token="")
    await orch_db.init_db()
    if url:
        async with orch_db._engine.begin() as conn:
            await conn.run_sync(orch_db.Base.metadata.drop_all)
            await conn.run_sync(orch_db.Base.metadata.create_all)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
            yield test_client
    finally:
        await orch_db.shutdown_db()


async def test_metrics_exposes_expected_series(client):
    now = utcnow()
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="n", bundle_ref="local:x", status="running"))
        await s.flush()
        s.add(Granule(granule_id="g1", batch_id="b1", state=GranuleState.PENDING.value, inputs=[]))
        s.add(Granule(granule_id="g2", batch_id="b1", state=GranuleState.PROCESSING.value, inputs=[]))
        s.add(
            Granule(
                granule_id="g_stuck",
                batch_id="b1",
                state=GranuleState.PROCESSING.value,
                inputs=[],
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
        await s.commit()
    # Oldest first — event_store.count_by_level_since assumes chronological order.
    events = [
        dict(ts=now - timedelta(days=2), source="t", level="info", message="old"),
        dict(ts=now - timedelta(minutes=5), source="t", level="warn", message="recent"),
    ]
    if orch_db.is_postgres():
        async with orch_db.get_session_maker()() as s:
            s.add_all(Event(**event) for event in events)
            await s.commit()
    else:
        for event in events:
            event_store.append(**event)

    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    families = list(text_string_to_metric_families(body))
    assert {family.name for family in families} == {
        "sathop_granules",
        "sathop_batches",
        "sathop_granules_stuck",
        "sathop_workers",
        "sathop_worker_heartbeat_age_seconds",
        "sathop_worker_disk_used_bytes",
        "sathop_worker_disk_total_bytes",
        "sathop_worker_disk_used_ratio",
        "sathop_worker_queue",
        "sathop_worker_egress_bytes_monthly",
        "sathop_receivers",
        "sathop_receiver_heartbeat_age_seconds",
        "sathop_receiver_disk_free_bytes",
        "sathop_receiver_queue_pulling",
        "sathop_receiver_throughput_bytes_per_second",
        "sathop_events_24h",
    }
    assert all(family.type == "gauge" for family in families)

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


async def test_metrics_requires_token_when_enabled(client, patch_settings):
    patch_settings(token="secret123")
    r1 = await client.get("/api/metrics")
    assert r1.status_code == 401
    r2 = await client.get("/api/metrics", headers={"Authorization": "Bearer secret123"})
    assert r2.status_code == 200
    r3 = await client.get("/api/metrics?token=secret123")
    assert r3.status_code == 200


async def test_metrics_preserve_retention_pause_and_removed_worker_rules(client):
    now = utcnow()
    async with orch_db.get_session_maker()() as s:
        s.add(
            Batch(
                batch_id="paused", name="paused", bundle_ref="orch:x@1", status="paused", delivered_count=42
            )
        )
        await s.flush()
        s.add(
            Granule(
                granule_id="paused:g",
                batch_id="paused",
                state="processing",
                inputs=[],
                updated_at=now - timedelta(days=1),
            )
        )
        s.add_all(
            [
                Worker(worker_id="active", disk_total_gb=0),
                Worker(worker_id="paused", operator_paused=True),
                Worker(worker_id="removed", removed_at=now),
                Receiver(receiver_id="disabled", enabled=False),
            ]
        )
        await s.commit()
    body = (await client.get("/api/metrics")).text
    assert 'sathop_granules{state="deleted"} 42.0' in body
    assert 'sathop_granules_stuck{state="processing"} 0.0' in body
    assert 'sathop_batches{status="paused"} 1.0' in body
    assert 'sathop_workers{enabled="true"} 1.0' in body
    assert 'sathop_workers{enabled="false"} 1.0' in body
    assert 'worker_id="removed"' not in body
    assert 'sathop_worker_disk_used_ratio{worker_id="active"} 0.0' in body
    assert 'sathop_receivers{enabled="false"} 1.0' in body


async def test_metrics_read_the_live_telemetry_source(client):
    now = utcnow()
    async with orch_db.get_session_maker()() as s:
        worker = Worker(worker_id="w", queue_processing=1)
        receiver = Receiver(receiver_id="r", queue_pulling=1)
        s.add_all([worker, receiver])
        await s.commit()
        if orch_db.is_postgres():
            worker.queue_processing = 7
            worker.queue_pending_download = 3
            receiver.queue_pulling = 5
            await s.commit()
        else:
            telemetry.update_worker(
                "w", telemetry.WorkerTelemetry(last_seen=now, queue_processing=7, queue_pending_download=3)
            )
            telemetry.update_receiver("r", telemetry.ReceiverTelemetry(last_seen=now, queue_pulling=5))
    body = (await client.get("/api/metrics")).text
    assert 'sathop_worker_queue{stage="processing",worker_id="w"} 7.0' in body
    assert 'sathop_worker_queue{stage="pending_download",worker_id="w"} 3.0' in body
    assert 'sathop_receiver_queue_pulling{receiver_id="r"} 5.0' in body


@pytest.mark.parametrize(
    ("module", "path", "loader_name", "cache_name", "reset_name", "body"),
    [
        (admin, "/api/admin/overview", "admin_overview", "_overview_cache", "reset_overview_cache", {}),
        (batches, "/api/batches", "summaries", "_list_cache", "reset_batches_cache", []),
        (metrics, "/api/metrics", "_collect", "_metrics_cache", "reset_metrics_cache", b""),
    ],
)
async def test_dashboard_requests_coalesce_and_auth_still_runs(
    client,
    monkeypatch,
    patch_settings,
    module,
    path,
    loader_name,
    cache_name,
    reset_name,
    body,
):
    async def load(*args, **kwargs):
        await asyncio.sleep(0)
        return body

    loader = AsyncMock(side_effect=load)
    monkeypatch.setattr(module, loader_name, loader)
    monkeypatch.setattr(module, cache_name, AsyncTTLCache(ttl_seconds=5))
    responses = await asyncio.gather(*(client.get(path) for _ in range(10)))
    assert all(response.status_code == 200 for response in responses)
    loader.assert_awaited_once()

    patch_settings(token="dashboard-test-token")
    assert (await client.get(path)).status_code == 401
    authorized = {"Authorization": "Bearer dashboard-test-token"}
    assert (await client.get(path, headers=authorized)).status_code == 200
    loader.assert_awaited_once()
    getattr(module, reset_name)()
    assert (await client.get(path, headers=authorized)).status_code == 200
    assert loader.await_count == 2
