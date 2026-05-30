"""AckBuffer: receiver-side coalescing of ack reports into batched POSTs.

The shared FlushBuffer mechanics (batching, requeue, drain) are exercised via
EventBuffer in test_event_buffer; here we pin the ack-specific wiring: acks flush
through ack_batch, and — unlike worker events — no ack is "terminal", so a lone
ack rides the interval rather than waking the flusher early.
"""

from __future__ import annotations

import asyncio

import pytest

from sathop.receiver.ack_buffer import AckBuffer
from sathop.shared.protocol import AckBatch, AckReport


class _FakeClient:
    def __init__(self) -> None:
        self.batches: list[list[int]] = []

    async def ack_batch(self, batch: AckBatch):
        self.batches.append([a.object_id for a in batch.acks])
        return None


def _ack(oid: int, *, success: bool = True) -> AckReport:
    return AckReport(receiver_id="r1", object_id=oid, sha256="abc", success=success)


async def test_flush_coalesces_acks_into_one_batch():
    c = _FakeClient()
    buf = AckBuffer(c)
    buf.enqueue(_ack(1))
    buf.enqueue(_ack(2, success=False))
    await buf._flush()
    assert c.batches == [[1, 2]]


async def test_lone_ack_does_not_wake_flusher_early():
    """No ack is terminal: a single enqueue waits out the interval (contrast
    with EventBuffer, where a terminal event flushes at once)."""
    c = _FakeClient()
    buf = AckBuffer(c, interval=100.0)  # long — only a full batch or cancel flushes
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    buf.enqueue(_ack(1))
    await asyncio.sleep(0.05)
    assert c.batches == []  # still buffered — no early wake
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.batches == [[1]]  # final drain on cancel lands it


async def test_full_batch_wakes_flusher():
    c = _FakeClient()
    buf = AckBuffer(c, interval=100.0, max_batch=2)
    task = asyncio.create_task(buf.loop())
    await asyncio.sleep(0.02)
    buf.enqueue(_ack(1))
    buf.enqueue(_ack(2))  # hits max_batch → wake
    await asyncio.sleep(0.02)
    assert c.batches == [[1, 2]]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
