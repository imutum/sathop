"""ProgressBuffer: worker-side coalescing of display-only progress checkpoints
into batched POSTs.

The reliability core (batch slicing, requeue-on-failure, bounded backlog,
drain-on-cancel) lives in the shared FlushBuffer base and is covered by
test_event_buffer; here we only assert the progress-specific layer — that
`enqueue_event` tags a checkpoint with its granule and that a flush sends one
ProgressBatch — plus that progress is never treated as urgent (no early wake).
"""

from __future__ import annotations

from sathop.shared.protocol import ProgressBatch, ProgressEvent
from sathop.worker.progress_buffer import ProgressBuffer


class _FakeClient:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str]]] = []

    async def report_progress_batch(self, batch: ProgressBatch) -> None:
        self.batches.append([(i.granule_id, i.event.step) for i in batch.items])


async def test_enqueue_event_coalesces_into_one_batch():
    c = _FakeClient()
    buf = ProgressBuffer(c)
    buf.enqueue_event("g1", ProgressEvent(step="read", pct=10))
    buf.enqueue_event("g2", ProgressEvent(step="write", pct=90))
    await buf._flush()
    assert c.batches == [[("g1", "read"), ("g2", "write")]]


async def test_flush_noop_when_empty():
    c = _FakeClient()
    await ProgressBuffer(c)._flush()
    assert c.batches == []


async def test_progress_never_wakes_early():
    """Progress is display-only and never urgent: a single enqueue must not set
    the wake event (no `wake_on`), so checkpoints ride the interval tick."""
    c = _FakeClient()
    buf = ProgressBuffer(c)
    buf.enqueue_event("g1", ProgressEvent(step="read"))
    assert not buf._wake.is_set()
