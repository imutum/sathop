"""EventBuffer: worker-side coalescing of transition events into batched POSTs.

Covers the reliability core — batch slicing, requeue-on-failure with a bounded
backlog, terminal/full-batch wake, and the final flush on cancellation — since
this is what guarantees a terminal event isn't dropped on a transient orch blip.
"""

from __future__ import annotations

import asyncio

import pytest

from sathop.shared.protocol import WorkerEventBatch, WorkerEventBatchResponse
from sathop.shared.state_machine import DeleteConfirmed, DownloadStarted
from sathop.worker.event_buffer import EventBuffer


class _FakeClient:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.batches: list[list[str]] = []
        self._fail = fail_times

    async def emit_events_batch(self, batch: WorkerEventBatch) -> WorkerEventBatchResponse:
        if self._fail > 0:
            self._fail -= 1
            raise RuntimeError("orch down")
        self.batches.append([e.granule_id for e in batch.events])
        return WorkerEventBatchResponse()


def _dl(gid: str) -> DownloadStarted:
    return DownloadStarted(granule_id=gid, worker_id="w1")


def _delete(gid: str) -> DeleteConfirmed:
    return DeleteConfirmed(granule_id=gid, worker_id="w1", object_keys=[])


async def test_flush_coalesces_into_one_batch():
    c = _FakeClient()
    buf = EventBuffer(c)
    buf.enqueue(_dl("g1"))
    buf.enqueue(_dl("g2"))
    await buf._flush()
    assert c.batches == [["g1", "g2"]]


async def test_flush_noop_when_empty():
    c = _FakeClient()
    await EventBuffer(c)._flush()
    assert c.batches == []


async def test_flush_respects_max_batch():
    c = _FakeClient()
    buf = EventBuffer(c, max_batch=2)
    for i in range(5):
        buf.enqueue(_dl(f"g{i}"))
    await buf._flush()
    await buf._flush()
    await buf._flush()
    assert c.batches == [["g0", "g1"], ["g2", "g3"], ["g4"]]


async def test_failed_flush_requeues_for_retry():
    """A transient orch failure must not drop the batch — it's re-queued and
    the next flush retries it (the terminal-event reliability guarantee)."""
    c = _FakeClient(fail_times=1)
    buf = EventBuffer(c)
    buf.enqueue(_dl("g1"))
    await buf._flush()  # fails → re-queue
    assert c.batches == []
    await buf._flush()  # succeeds
    assert c.batches == [["g1"]]


async def test_failed_flush_bounds_backlog_dropping_oldest():
    """A prolonged outage can't grow memory without limit: the requeued batch
    plus the tail is clipped to max_buffer, shedding the oldest events."""
    c = _FakeClient(fail_times=1)
    buf = EventBuffer(c, max_batch=2, max_buffer=3)
    for i in range(2):
        buf.enqueue(_dl(f"a{i}"))
    for i in range(3):
        buf.enqueue(_dl(f"b{i}"))
    await buf._flush()  # fails: requeue [a0,a1]+[b0,b1,b2]=5 > 3 → drop a0,a1
    assert c.batches == []
    await buf._flush()  # backlog is now [b0,b1,b2]
    assert c.batches == [["b0", "b1"]]


async def test_loop_flushes_on_terminal_wake():
    c = _FakeClient()
    buf = EventBuffer(c, interval=100.0)  # long interval → only the wake fires
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    buf.enqueue(_delete("g1"))  # terminal kind → immediate wake
    await asyncio.sleep(0.02)
    assert c.batches == [["g1"]]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_loop_flushes_on_full_batch_wake():
    c = _FakeClient()
    buf = EventBuffer(c, interval=100.0, max_batch=2)
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    buf.enqueue(_dl("g1"))  # 1 < max_batch → no wake
    buf.enqueue(_dl("g2"))  # hits max_batch → wake
    await asyncio.sleep(0.02)
    assert c.batches == [["g1", "g2"]]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_loop_final_flush_on_cancel():
    """Cancellation (worker drain) runs one last flush so a just-finished
    handler's terminal event still lands."""
    c = _FakeClient()
    buf = EventBuffer(c, interval=100.0)
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    buf.enqueue(_dl("g1"))  # non-terminal → no wake; only cancel will flush it
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.batches == [["g1"]]


async def test_loop_drains_whole_backlog_on_cancel():
    """The final drain isn't capped at one batch — a backlog larger than
    max_batch is fully flushed so no terminal event is stranded."""
    c = _FakeClient()
    buf = EventBuffer(c, interval=100.0, max_batch=2)
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    for i in range(5):
        buf.enqueue(_dl(f"g{i}"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.batches == [["g0", "g1"], ["g2", "g3"], ["g4"]]


# ─── pending_granule_ids: lease-reclaim protection ──────────────────────────


async def test_pending_granule_ids_includes_queued():
    """Enqueued-but-not-yet-flushed transition events keep their granule_ids in the
    pending set so the heartbeat can shield them from lease reclaim."""
    buf = EventBuffer(_FakeClient())
    buf.enqueue(_dl("g1"))
    buf.enqueue(_delete("g2"))
    assert buf.pending_granule_ids() == {"g1", "g2"}


async def test_pending_granule_ids_empty_after_successful_flush():
    c = _FakeClient()
    buf = EventBuffer(c)
    buf.enqueue(_dl("g1"))
    await buf._flush()
    assert c.batches == [["g1"]]
    assert buf.pending_granule_ids() == set()


async def test_pending_granule_ids_covers_inflight_batch():
    """During the flush POST the batch is sliced out of _q; _inflight_gids must keep
    those granule_ids pending so there is no reclaim-exposure window mid-flush."""
    gate = asyncio.Event()

    class _BlockingClient(_FakeClient):
        async def emit_events_batch(self, batch):
            await gate.wait()
            return await super().emit_events_batch(batch)

    buf = EventBuffer(_BlockingClient())
    buf.enqueue(_dl("g1"))
    flush = asyncio.create_task(buf._flush())
    await asyncio.sleep(0.02)  # let _flush slice _q and enter the blocked POST
    assert buf._q == []  # sliced out of the queue
    assert buf.pending_granule_ids() == {"g1"}  # still covered, via _inflight_gids
    gate.set()
    await flush
    assert buf.pending_granule_ids() == set()
