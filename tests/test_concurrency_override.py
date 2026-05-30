"""Operator-managed worker concurrency: the orchestrator REST surface that
stores per-worker overrides + plumbs them through heartbeat, and the worker-side
`_reconcile_concurrency` convergence (grow = instant release, equal = no-op,
shrink = reconfig drain + handler rebuild that must NOT exit the process).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Worker
from sathop.orchestrator.main import app
from sathop.worker.config import Settings
from sathop.worker.runtime import Worker as RuntimeWorker

# ─── orchestrator side ─────────────────────────────────────────────────────


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_worker(worker_id: str = "w1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=10, public_url=None))
        await s.commit()


async def _overrides(worker_id: str) -> tuple[int | None, int | None]:
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, worker_id)
        assert w is not None
        return w.download_concurrency, w.process_concurrency


async def test_set_concurrency_endpoint(client):
    await _seed_worker()
    r = client.put("/api/workers/w1/concurrency", json={"download_concurrency": 4, "process_concurrency": 2})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "download_concurrency": 4, "process_concurrency": 2}
    assert await _overrides("w1") == (4, 2)
    # Clear via null
    r = client.put(
        "/api/workers/w1/concurrency", json={"download_concurrency": None, "process_concurrency": None}
    )
    assert r.status_code == 200
    assert await _overrides("w1") == (None, None)
    # Reject 0 / negative on either field
    assert client.put("/api/workers/w1/concurrency", json={"download_concurrency": 0}).status_code == 422
    assert client.put("/api/workers/w1/concurrency", json={"process_concurrency": -1}).status_code == 422
    # 404 for unknown worker
    assert client.put("/api/workers/ghost/concurrency", json={"download_concurrency": 1}).status_code == 404


async def test_set_concurrency_bulk(client):
    await _seed_worker("w1")
    await _seed_worker("w2")
    r = client.put(
        "/api/workers/concurrency",
        json={"worker_ids": ["w1", "w2", "ghost"], "download_concurrency": 4, "process_concurrency": 1},
    )
    assert r.status_code == 200
    assert sorted(r.json()["applied"]) == ["w1", "w2"]  # unknown id skipped
    assert await _overrides("w1") == (4, 1)
    assert await _overrides("w2") == (4, 1)
    # Validation rejects non-positive before any write
    assert (
        client.put(
            "/api/workers/concurrency",
            json={"worker_ids": ["w1"], "download_concurrency": 0},
        ).status_code
        == 422
    )


async def test_heartbeat_response_carries_override(client):
    await _seed_worker()
    client.put("/api/workers/w1/concurrency", json={"download_concurrency": 4, "process_concurrency": 2})
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["download_concurrency"] == 4
    assert body["process_concurrency"] == 2


async def test_heartbeat_response_null_when_no_override(client):
    await _seed_worker()
    body = client.post("/api/workers/heartbeat", json={"worker_id": "w1"}).json()
    assert body["download_concurrency"] is None
    assert body["process_concurrency"] is None


async def test_heartbeat_persists_live_concurrency(client):
    await _seed_worker()
    client.post(
        "/api/workers/heartbeat",
        json={"worker_id": "w1", "download_concurrency": 6, "process_concurrency": 3},
    )
    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w is not None
        assert w.live_download_concurrency == 6
        assert w.live_process_concurrency == 3


# ─── worker side: _reconcile_concurrency convergence ───────────────────────


def _settings(tmp_path: Path, *, download: int = 2, process: int = 2) -> Settings:
    return Settings(
        worker_id="test-w",
        orchestrator_url="http://127.0.0.1:0",
        token="",
        capacity=4,
        public_url="http://127.0.0.1:0",
        work_root=tmp_path / "work",
        bundle_cache=tmp_path / "bundles",
        venv_cache=tmp_path / "venvs",
        shared_cache=tmp_path / "shared",
        storage_root=tmp_path / "storage",
        storage_port=0,
        progress_port=0,
        heartbeat_interval=10,
        lease_poll_interval=1,
        download_concurrency=download,
        process_concurrency=process,
        upload_concurrency=1,
        aria2_rpc="",
        aria2_secret="",
        minio_access_key="",
        minio_secret_key="",
        minio_bucket="sathop",
        disk_pause_pct=0.85,
        disk_resume_pct=0.70,
        backpressure_interval=10,
        venv_cache_limit_gb=10.0,
        gc_interval_sec=0,
        tls_cert_path=tmp_path / "cert.pem",
        tls_key_path=tmp_path / "key.pem",
    )


async def test_reconcile_grow_releases_permits_instantly(tmp_path):
    """target > live on both dims → release delta permits on each stage
    semaphore, bump live, never enter a reconfig (no _reconfiguring, no task)."""
    w = RuntimeWorker(_settings(tmp_path, download=2, process=2))
    try:
        dl0 = w._handler._download_sem._value
        pr0 = w._handler._process_sem._value
        handler = w._handler

        w._reconcile_concurrency(5, 4)  # +3 download, +2 process

        assert w._live_download == 5
        assert w._live_process == 4
        assert w._handler is handler  # same instance — grow does not rebuild
        assert w._handler._download_sem._value == dl0 + 3
        assert w._handler._process_sem._value == pr0 + 2
        assert w._reconfiguring is False
    finally:
        await w.client.aclose()


async def test_reconcile_equal_is_noop(tmp_path):
    w = RuntimeWorker(_settings(tmp_path, download=2, process=2))
    try:
        handler = w._handler
        dl0, pr0 = w._handler._download_sem._value, w._handler._process_sem._value

        w._reconcile_concurrency(2, 2)

        assert w._live_download == 2
        assert w._live_process == 2
        assert w._handler is handler
        assert (w._handler._download_sem._value, w._handler._process_sem._value) == (dl0, pr0)
        assert w._reconfiguring is False
    finally:
        await w.client.aclose()


async def test_reconcile_override_none_falls_back_to_env(tmp_path):
    """None override → target is the frozen env default; here that equals live,
    so it's a no-op (proves the fallback, not a spurious reconfig)."""
    w = RuntimeWorker(_settings(tmp_path, download=3, process=2))
    try:
        handler = w._handler
        w._reconcile_concurrency(None, None)
        assert (w._live_download, w._live_process) == (3, 2)
        assert w._handler is handler
        assert w._reconfiguring is False
    finally:
        await w.client.aclose()


async def test_reconcile_shrink_rebuilds_without_process_exit(tmp_path):
    """target < live on either dim → schedule reconfig drain. With no in-flight
    handlers it rebuilds immediately: a NEW GranuleHandler with smaller
    semaphores, live updated, _reconfiguring back to false — and crucially the
    drain path must NOT set _draining / raise GracefulAgentExit (process stays
    up)."""
    w = RuntimeWorker(_settings(tmp_path, download=4, process=3))
    try:
        old_handler = w._handler
        assert not w._handlers  # empty → drain loop exits at once

        w._reconcile_concurrency(1, 1)  # shrink both → deferred reconfig task
        # empty handlers ⇒ drain loop exits at once and the task rebuilds;
        # yield until it completes (it never blocks since nothing is in-flight)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if not w._reconfiguring and w._handler is not old_handler:
                break

        assert w._reconfiguring is False
        assert w._draining is False  # NEVER touched by reconfig
        assert w._handler is not old_handler  # rebuilt
        assert w._handler._download_sem._value == 1
        assert w._handler._process_sem._value == 1
        assert (w._live_download, w._live_process) == (1, 1)
        assert w._handler._upload_sem._value == w.s.upload_concurrency  # upload stays env-derived
    finally:
        await w.client.aclose()


async def test_reconcile_shrink_one_dim_triggers_reconfig(tmp_path):
    """Shrink on EITHER dimension takes the reconfig path even if the other
    grows — can't safely reclaim in-use permits, so rebuild covers both."""
    w = RuntimeWorker(_settings(tmp_path, download=4, process=2))
    try:
        old_handler = w._handler
        w._reconcile_concurrency(2, 5)  # download shrinks, process grows
        await asyncio.sleep(0)
        for _ in range(50):
            if not w._reconfiguring:
                break
            await asyncio.sleep(0.05)
        assert w._handler is not old_handler
        assert w._handler._download_sem._value == 2
        assert w._handler._process_sem._value == 5
        assert (w._live_download, w._live_process) == (2, 5)
        assert w._draining is False
    finally:
        await w.client.aclose()
