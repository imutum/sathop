"""Pipeline pull loop: 1 producer + N permanent workers + bounded queue.

Replaces the old `pull → gather(N) → loop` model where one slow object
stalled siblings until the whole batch finished. These tests pin down
the three invariants that justify the redesign:

  1. All offered items get fetched and acked (pipeline drains, no leak).
  2. A slow item doesn't block sibling workers (the whole point).
  3. Re-offers of an in-flight id are deduped (orch keeps re-offering until
     ack lands, and we mustn't double-download)."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sathop.receiver.ack_buffer import AckBuffer
from sathop.receiver.config import Settings
from sathop.receiver.runtime import Receiver
from sathop.shared.protocol import AckBatch, AckReport, PullItem, PullRequest, PullResponse


async def _pump(r: Receiver) -> None:
    """Run the pull pipeline and the ack flusher together, the way run() does —
    so buffered acks actually reach the stub's /ack/batch."""
    await asyncio.gather(r._pull_loop(), r._acks.loop())


def _serve_static(payload: bytes, *, slow_path: str | None = None, slow_delay: float = 0.0):
    """HTTP server. If slow_path matches the request path, sleep slow_delay
    before responding — used to inject a straggler that the pipeline must
    route around."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw) -> None:
            pass

        def do_GET(self) -> None:
            if slow_path and self.path == slow_path:
                time.sleep(slow_delay)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


class _StubOrchClient:
    """Drives the producer with a scripted sequence of pull responses.
    `pull_responses` is a list — each call to .pull() returns the next
    entry, then sticks on the last (typically empty) so the producer
    parks on poll_interval."""

    def __init__(self, pull_responses: list[list[PullItem]]) -> None:
        self._responses = pull_responses
        self._idx = 0
        self.acks: list[AckReport] = []

    async def pull(self, _req: PullRequest) -> PullResponse:
        items = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return PullResponse(items=items)

    async def ack_batch(self, batch: AckBatch):
        self.acks.extend(batch.acks)
        return None

    async def aclose(self) -> None:
        pass


def _make_receiver(
    tmp_path: Path,
    *,
    concurrent_pulls: int = 4,
    pull_responses: list[list[PullItem]] | None = None,
) -> tuple[Receiver, _StubOrchClient]:
    s = Settings(
        receiver_id="r1",
        orchestrator_url="http://orch.test",
        token="t",
        storage_dir=tmp_path / "archive",
        poll_interval=1,  # short — empty-pull idle window for tests
        concurrent_pulls=concurrent_pulls,
        platform="linux",
        pull_segments=1,  # disable segmenting; we test pipeline orchestration here
        pull_segment_min_bytes=10**12,
    )
    r = Receiver(s)
    stub = _StubOrchClient(pull_responses or [])
    r.client = stub  # type: ignore[assignment]
    r._acks = AckBuffer(stub)  # buffer must flush to the stub, not the real client
    return r, stub


def _item(object_id: int, payload: bytes, port: int, path: str = "/x") -> PullItem:
    return PullItem(
        granule_id=f"g{object_id}",
        batch_id="b1",
        object_id=object_id,
        object_key=f"b1/g{object_id}/{path.lstrip('/')}",
        presigned_url=f"http://127.0.0.1:{port}{path}",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


async def _drain_until(stub: _StubOrchClient, count: int, timeout: float = 5.0) -> None:
    """Spin until `count` acks land or we time out (safety net)."""
    deadline = time.monotonic() + timeout
    while len(stub.acks) < count:
        if time.monotonic() > deadline:
            raise TimeoutError(f"only {len(stub.acks)}/{count} acked in {timeout}s")
        await asyncio.sleep(0.01)


# ─── invariant 1: pipeline drains everything offered ──────────────────────


async def test_pipeline_drains_all_offered_items(tmp_path):
    payload = b"hello-world"
    srv, port = _serve_static(payload)
    try:
        # Two RPCs: first 5 items, then [] forever.
        items = [_item(i, payload, port) for i in range(5)]
        r, stub = _make_receiver(tmp_path, concurrent_pulls=2, pull_responses=[items, []])
        task = asyncio.create_task(_pump(r))
        try:
            await _drain_until(stub, 5)
            assert {a.object_id for a in stub.acks} == {0, 1, 2, 3, 4}
            assert all(a.success for a in stub.acks)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseExceptionGroup):
                pass
            await r.aclose()
    finally:
        srv.shutdown()


# ─── invariant 2: a slow item doesn't stall siblings ──────────────────────


async def test_pipeline_does_not_stall_siblings_on_straggler(tmp_path):
    """Set up: 4 items, one of them takes 0.6s (slow), three take ~0ms (fast).
    With 2 workers, the old gather-batched model would finish in ≥ slow_delay
    + (sum of others / N). Pipeline finishes in ~slow_delay because the
    second worker chews through the three fasts while the first worker
    holds on the slow one."""
    payload = b"x"
    srv, port = _serve_static(payload, slow_path="/slow", slow_delay=0.6)
    try:
        items = [
            _item(0, payload, port, "/slow"),
            _item(1, payload, port, "/fast1"),
            _item(2, payload, port, "/fast2"),
            _item(3, payload, port, "/fast3"),
        ]
        r, stub = _make_receiver(tmp_path, concurrent_pulls=2, pull_responses=[items, []])
        t0 = time.monotonic()
        task = asyncio.create_task(_pump(r))
        try:
            await _drain_until(stub, 4, timeout=3.0)
            elapsed = time.monotonic() - t0
            # Slow item alone is 0.6s. The three fasts take essentially no
            # time. Pipeline overlap means total ≤ slow + ε. Allow 0.8s of
            # CI/scheduler slop on top of the 0.6 slow — the assertion still
            # catches the regression where siblings serialize behind slow
            # (which would be 4 × 0.6s = 2.4s).
            assert elapsed < 1.4, (
                f"pipeline stalled on straggler: {elapsed:.2f}s > 1.4s "
                f"(would be ≥2.4s if siblings waited for slow item)"
            )
            assert {a.object_id for a in stub.acks} == {0, 1, 2, 3}
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseExceptionGroup):
                pass
            await r.aclose()
    finally:
        srv.shutdown()


# ─── invariant 3: dedup against in-flight ids ─────────────────────────────


async def test_pipeline_dedups_inflight_object_ids(tmp_path):
    """Orch's /pull keeps re-offering not-yet-acked objects. Producer must
    skip ids already in `_inflight` so we don't queue and double-download
    the same bytes. We script the orch to return the SAME 3 items twice
    in a row, then nothing — the pipeline should still ack each id exactly
    once."""
    payload = b"once-only"
    srv, port = _serve_static(payload)
    try:
        items = [_item(i, payload, port) for i in range(3)]
        # Two consecutive pulls yield the same 3 items — second is the
        # re-offer. Without dedup we'd ack 6 times (3 fetched + 3 redundant);
        # with dedup, exactly 3.
        r, stub = _make_receiver(tmp_path, concurrent_pulls=2, pull_responses=[items, items, []])
        task = asyncio.create_task(_pump(r))
        try:
            await _drain_until(stub, 3)
            # Wait a tick to make sure the second-RPC re-offer doesn't sneak
            # an extra ack in via a worker that was just freed.
            await asyncio.sleep(0.2)
            ids_acked = [a.object_id for a in stub.acks]
            assert sorted(ids_acked) == [0, 1, 2], f"each id should ack exactly once, got {ids_acked}"
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseExceptionGroup):
                pass
            await r.aclose()
    finally:
        srv.shutdown()


# ─── invariant 4: workers don't die on one bad object ─────────────────────


async def test_pipeline_worker_survives_bad_object(tmp_path):
    """One item URL is unreachable (port 1, refused) — its worker should
    ack failure and pick up the next item, not crash the pipeline."""
    payload = b"good"
    srv, port = _serve_static(payload)
    try:
        bad = PullItem(
            granule_id="bad",
            batch_id="b1",
            object_id=999,
            object_key="b1/bad/x",
            presigned_url="http://127.0.0.1:1/",  # connection refused
            sha256="0" * 64,
            size=4,
        )
        items = [bad, _item(1, payload, port), _item(2, payload, port)]
        r, stub = _make_receiver(tmp_path, concurrent_pulls=2, pull_responses=[items, []])
        task = asyncio.create_task(_pump(r))
        try:
            await _drain_until(stub, 3)
            by_id = {a.object_id: a for a in stub.acks}
            assert by_id[999].success is False, "bad object should ack failure"
            assert by_id[1].success is True, "good objects should still go through"
            assert by_id[2].success is True
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseExceptionGroup):
                pass
            await r.aclose()
    finally:
        srv.shutdown()
