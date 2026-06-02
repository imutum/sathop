"""The pipeline loop must wake the instant a handler frees a slot, instead of
sleeping out a full lease_poll_interval with work still pending — this is what
keeps a busy worker leasing freed slots continuously rather than in fixed
poll-sized bursts.

The decisive test uses a deliberately huge lease_poll_interval (30s): if the
second lease arrives a fraction of a second after the first handler completes,
it can only be the slot-free wakeup, never the poll timeout."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sathop.shared.protocol import LeaseItem, LeaseResponse
from sathop.worker.config import Settings
from sathop.worker.runtime import Worker


def _settings(tmp_path: Path, lease_poll_interval: int = 30) -> Settings:
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
        lease_poll_interval=lease_poll_interval,
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


async def test_on_handler_done_pops_and_signals(tmp_path):
    """_on_handler_done removes the handler from the registry and sets the
    slot-free event — and pops before it signals, so the loop sees the freed
    slot when it observes the wakeup."""
    w = Worker(_settings(tmp_path))
    try:
        finished = asyncio.create_task(asyncio.sleep(0))
        await finished
        w._handlers["g"] = finished
        w._slot_free.clear()

        w._on_handler_done("g")

        assert "g" not in w._handlers
        assert w._slot_free.is_set()
    finally:
        await w.client.aclose()


async def test_loop_wakes_on_handler_completion(tmp_path):
    """ceiling=1 + a 30s poll interval: the loop fills its single slot, parks on
    the slot-free event, and must re-lease within a fraction of a second of the
    handler completing. A timeout-driven loop could not lease again for 30s."""
    w = Worker(_settings(tmp_path, lease_poll_interval=30))
    try:
        # Force exactly one in-flight slot for a crisp full → free → full cycle.
        w._live_download, w._live_process = 1, 0

        gates: list[asyncio.Event] = []

        async def fake_handle(item: LeaseItem) -> None:
            ev = asyncio.Event()
            gates.append(ev)
            await ev.wait()

        w._handler.handle = fake_handle  # type: ignore[method-assign]

        lease_calls: list[int] = []
        seq = 0

        async def fake_lease(req):
            nonlocal seq
            lease_calls.append(req.capacity)
            item = LeaseItem(granule_id=f"g{seq}", batch_id="b", bundle_ref="local:x", inputs=[], meta={})
            seq += 1
            return LeaseResponse(items=[item], lease_expires_at=datetime.now(UTC) + timedelta(minutes=30))

        w.client.lease = fake_lease  # type: ignore[method-assign]

        loop = asyncio.create_task(w._pipeline_loop())
        try:
            # First lease fills the only slot; the loop then parks on _slot_free.
            await asyncio.sleep(0.2)
            assert lease_calls == [1], f"expected exactly one lease, got {lease_calls}"
            assert len(w._handlers) == 1
            assert len(gates) == 1

            # Release the first handler. The loop must wake on its completion and
            # re-lease far inside the 30s poll interval.
            gates[0].set()
            await asyncio.sleep(0.2)
            assert len(lease_calls) == 2, (
                f"loop did not wake on completion (would have needed the 30s timeout): {lease_calls}"
            )
        finally:
            loop.cancel()
            try:
                await loop
            except asyncio.CancelledError:
                pass
    finally:
        await w.client.aclose()
