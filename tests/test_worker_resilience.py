"""Worker resiliency paths: heartbeat 404 re-register, 401 fatal exit,
lease 4xx/5xx exponential backoff, work_dir orphan GC."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from sathop.shared.protocol import (
    LeaseItem,
    LeaseRequest,
    LeaseResponse,
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegister,
)
from sathop.worker.agent import OrchestratorClient
from sathop.worker.cleanup import prune_work_dir_orphans
from sathop.worker.config import Settings
from sathop.worker.runtime import LEASE_MAX_BACKOFF_FACTOR, Worker


def _settings(tmp_path: Path) -> Settings:
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
        heartbeat_interval=1,
        lease_poll_interval=1,
        download_concurrency=1,
        process_concurrency=1,
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


def _http_error(status: int, path: str = "http://orch/api/x") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", path)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=httpx.Response(status, request=req))


# ─── work_dir orphan GC (pure function — fastest) ──────────────────────────


def test_prune_work_dir_orphans_removes_stale(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    fresh = work_root / f"g-fresh-{int(time.time())}"  # ts = now → keep
    stale = work_root / f"g-stale-{int(time.time()) - 7200}"  # 2h old → drop
    active = work_root / f"g-busy-{int(time.time()) - 7200}"  # 2h old but active → keep
    for d in (fresh, stale, active):
        d.mkdir()
        (d / "tmp.bin").write_bytes(b"x" * 1024)
    # also a malformed dir name (no ts suffix) and a non-dir file — both ignored
    (work_root / "g-malformed").mkdir()
    (work_root / "loose-file").write_bytes(b"y")

    r = prune_work_dir_orphans(work_root, active_segments={"busy"})
    assert r["removed"] == 1
    assert r["freed_bytes"] >= 1024
    assert fresh.exists()
    assert active.exists()
    assert not stale.exists()
    assert (work_root / "g-malformed").exists()


def test_prune_work_dir_orphans_missing_root(tmp_path):
    """Worker may run before its work_root is created. Don't crash on it."""
    r = prune_work_dir_orphans(tmp_path / "does-not-exist", active_segments=set())
    assert r == {"removed": 0, "freed_bytes": 0}


# ─── heartbeat 404 → re-register ───────────────────────────────────────────


async def test_heartbeat_404_triggers_re_register(tmp_path):
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        register_calls = 0

        async def fake_register(req=None):
            nonlocal register_calls
            register_calls += 1

        # First two heartbeats 404 (operator deleted the row, then it's still
        # missing for a beat); third succeeds. Re-register fires after the
        # first 404 — we don't expect duplicate calls per 404.
        heartbeat_replies = [
            _http_error(404),
            WorkerHeartbeatResponse(),
        ]

        async def fake_heartbeat(req):
            r = heartbeat_replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        w.client.register = fake_register  # type: ignore[method-assign]
        w.client.heartbeat = fake_heartbeat  # type: ignore[method-assign]

        task = asyncio.create_task(w._heartbeat_loop())

        # Wait until both heartbeat replies have been consumed AND we re-registered
        # — deterministic regardless of CI scheduler jitter. 5s ceiling guards
        # against the loop never firing (regression).
        async def _both_consumed() -> None:
            while heartbeat_replies or register_calls < 1:
                await asyncio.sleep(0.02)

        try:
            await asyncio.wait_for(_both_consumed(), timeout=5.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert register_calls >= 1, "expected re-register after heartbeat 404"
        assert heartbeat_replies == [], "expected both heartbeat replies consumed"
    finally:
        await w.client.aclose()


# ─── agent-level 401 → fatal exit (single policy applies to every method) ──


def _client_with_401(endpoint_filter: str | None = None) -> OrchestratorClient:
    """OrchestratorClient whose mocked transport returns 401 for every (or
    only matching) request — exercises shared OrchClient._check across all
    worker methods without a live server."""

    def handler(request: httpx.Request) -> httpx.Response:
        if endpoint_filter is None or endpoint_filter in request.url.path:
            return httpx.Response(401, json={"detail": "invalid token"})
        return httpx.Response(200, json={})

    c = OrchestratorClient("http://orch", "wrong-token")
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://orch",
        headers={"Authorization": "Bearer wrong-token"},
    )
    return c


@pytest.mark.parametrize(
    "name,call",
    [
        ("heartbeat", lambda c: c.heartbeat(WorkerHeartbeat(worker_id="t"))),
        ("lease", lambda c: c.lease(LeaseRequest(worker_id="t", capacity=1))),
        ("register", lambda c: c.register(WorkerRegister(worker_id="t"))),
        ("get_deletable", lambda c: c.get_deletable("t")),
    ],
)
async def test_agent_401_raises_auth_token_invalid(name, call):
    """Every orch endpoint shares one auth policy: 401 ⇒ AuthTokenInvalid.
    The runtime's top-level `except* AuthTokenInvalid` turns this into a
    clean SystemExit(1) so aclose runs and docker restart makes the
    misconfig visible."""
    from sathop.shared.orch_client import AuthTokenInvalid

    c = _client_with_401()
    try:
        with pytest.raises(AuthTokenInvalid):
            await call(c)
    finally:
        await c.aclose()


# ─── lease 403 / 5xx → exponential backoff ─────────────────────────────────


async def test_lease_403_grows_backoff(tmp_path):
    """Each consecutive 403 doubles _lease_backoff_factor up to the cap."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:

        async def fake_lease(req):
            raise _http_error(403)

        w.client.lease = fake_lease  # type: ignore[method-assign]
        assert w._lease_backoff_factor == 1

        # Drive 3 lease attempts. With backoff doubling each failure, we'd
        # hit factor 8 nominal — but the cap is 6, so we land at 4 after
        # ~3 attempts (1 → 2 → 4 → 8 capped to 6 on the next).
        task = asyncio.create_task(w._pipeline_loop())
        await asyncio.sleep(2.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert w._lease_backoff_factor >= 2
        assert w._lease_backoff_factor <= 6
    finally:
        await w.client.aclose()


async def test_lease_success_resets_backoff(tmp_path):
    """A 200 lease after a 403 must zero the backoff counter so a worker
    that's just been re-enabled picks back up at the original poll rate."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        empty = LeaseResponse(items=[], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))

        # Simulate a 403 then a 200.
        sequence = [_http_error(403), empty, empty]

        async def fake_lease(req):
            r = sequence.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        w.client.lease = fake_lease  # type: ignore[method-assign]

        task = asyncio.create_task(w._pipeline_loop())
        await asyncio.sleep(3.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # backoff bumped during the 403 attempt; reset on the next success
        assert w._lease_backoff_factor == 1
    finally:
        await w.client.aclose()


# ─── empty-result lease → adaptive poll backoff ────────────────────────────


async def test_lease_empty_grows_then_resets_backoff(tmp_path):
    """An empty lease (200 with no items) decays the poll rate so an idle fleet
    stops hammering /lease; a lease that returns work snaps it back to base."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        empty = LeaseResponse(items=[], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))
        item = LeaseItem(granule_id="g1", batch_id="b1", bundle_ref="orch:x@1", inputs=[], meta={})
        with_work = LeaseResponse(items=[item], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))
        started: list[str] = []
        w._start_handler = lambda it: started.append(it.granule_id)  # type: ignore[method-assign]

        async def all_empty(req):
            return empty

        w.client.lease = all_empty  # type: ignore[method-assign]
        assert w._empty_backoff_factor == 1

        task = asyncio.create_task(w._pipeline_loop())
        await asyncio.sleep(2.5)  # polls at t=0 (×1), t=1 (×2), t=3 (×4)…
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # decayed across empty polls, but never past the cap (cap-agnostic so the
        # assertion survives tuning LEASE_MAX_BACKOFF_FACTOR)
        assert 2 <= w._empty_backoff_factor <= LEASE_MAX_BACKOFF_FACTOR

        # A lease that returns work resets the factor to base. The second call
        # parks forever so no follow-up empty poll bumps it back up.
        blocked = asyncio.Event()
        calls = 0

        async def work_then_park(req):
            nonlocal calls
            calls += 1
            if calls == 1:
                return with_work
            await blocked.wait()
            return empty

        w.client.lease = work_then_park  # type: ignore[method-assign]
        task = asyncio.create_task(w._pipeline_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert started == ["g1"]
        assert w._empty_backoff_factor == 1
    finally:
        await w.client.aclose()


async def test_reconcile_detail_flips_verbose_handler_and_progress(tmp_path):
    """The heartbeat-pushed detail mode flips the worker's verbose flag, the
    handler's emit gate, and the progress server's enable flag together — in
    place, no handler rebuild. Only an explicit "fast" flips; None (older orch
    without the field) and "verbose" stay verbose."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        assert w._verbose and w._handler._verbose and w.progress._enabled
        w._reconcile_detail("fast")
        assert not w._verbose and not w._handler._verbose and not w.progress._enabled
        w._reconcile_detail("verbose")
        assert w._verbose and w._handler._verbose and w.progress._enabled
        w._reconcile_detail(None)  # missing field (older orchestrator) → stay verbose
        assert w._verbose
    finally:
        await w.client.aclose()


async def test_pipeline_capacity_counts_handlers_not_stage_queue(tmp_path):
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        w._handlers["g1"] = asyncio.create_task(asyncio.sleep(60))
        w._handlers["g2"] = asyncio.create_task(asyncio.sleep(60))
        lease_calls: list[int] = []

        async def fake_lease(req):
            lease_calls.append(req.capacity)
            return LeaseResponse(items=[], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))

        w.client.lease = fake_lease  # type: ignore[method-assign]
        task = asyncio.create_task(w._pipeline_loop())
        await asyncio.sleep(1.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert lease_calls == []
    finally:
        for t in w._handlers.values():
            t.cancel()
        await w.client.aclose()
