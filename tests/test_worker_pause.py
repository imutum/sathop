"""End-to-end coverage of the operator-set pause flag — verifies the worker's
pipeline_loop actually skips /lease while _remote_pause is True (instead of
just trusting that the orchestrator delivered the flag)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sathop.shared.protocol import LeaseResponse
from sathop.worker.config import Settings
from sathop.worker.runtime import Worker


def _settings(tmp_path: Path) -> Settings:
    """Minimal Settings instance — values not exercised by pipeline_loop are
    still required by the dataclass, so we set them to harmless defaults."""
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


async def _drive_loop(w: Worker, ticks: int) -> None:
    """Run pipeline_loop just long enough to exercise `ticks` poll cycles,
    then cancel cleanly."""
    task = asyncio.create_task(w._pipeline_loop())
    try:
        # Each iteration sleeps `lease_poll_interval` seconds (1s here).
        # Wait a hair longer than the cycles we want to observe.
        await asyncio.sleep(w.s.lease_poll_interval * ticks + 0.2)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_remote_pause_blocks_new_leases(tmp_path):
    """Worker.pipeline_loop must skip /lease entirely while _remote_pause is
    True, then resume calling it once the flag clears."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:
        empty_resp = LeaseResponse(items=[], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))
        lease_calls: list[int] = []

        async def fake_lease(req):
            lease_calls.append(req.capacity)
            return empty_resp

        w.client.lease = fake_lease  # type: ignore[method-assign]

        # Phase 1: not paused — lease should fire on each poll cycle.
        await _drive_loop(w, ticks=2)
        assert len(lease_calls) >= 1, f"expected lease calls when running, got {lease_calls}"

        # Phase 2: engage remote pause; lease must stop.
        w._remote_pause = True
        lease_calls.clear()
        await _drive_loop(w, ticks=3)
        assert lease_calls == [], f"expected no lease calls under pause, got {lease_calls}"

        # Phase 3: release pause; lease resumes.
        w._remote_pause = False
        await _drive_loop(w, ticks=2)
        assert len(lease_calls) >= 1, f"expected lease calls after resume, got {lease_calls}"
    finally:
        await w.client.aclose()


async def test_backpressure_pause_also_blocks_leases(tmp_path):
    """Sanity check that the existing disk-backpressure pause path is
    independent of _remote_pause — the OR-gate must accept either."""
    s = _settings(tmp_path)
    w = Worker(s)
    try:

        async def fake_lease(req):  # pragma: no cover - shouldn't fire
            raise AssertionError("lease() called while paused")

        w.client.lease = fake_lease  # type: ignore[method-assign]

        w._pause_lease = True
        # Should not raise — the gate prevents lease() from being called.
        await _drive_loop(w, ticks=2)
    finally:
        await w.client.aclose()
