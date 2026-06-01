"""Worker-side progress buffer — a FlushBuffer of progress checkpoints.

Progress is display-only telemetry (a UI progress bar). Both sources — the
bundle's per-step self-reports (via the local nonce HTTP endpoint) and the
download callback's per-granule ticks across every in-flight granule — funnel
through this one buffer and land on the orchestrator as a single batched POST per
interval rather than one request each. That amortizes the orchestrator's
per-request tax (routing, one in-memory append, one SSE nudge) across the whole
batch, the same way `EventBuffer` does for transition events.

Unlike transition events, nothing here is urgent: every item rides the interval,
none wakes the flusher early (`wake_on=None`). Loss is harmless — checkpoints are
never persisted and are re-reported within seconds — so the FlushBuffer's
bounded shed-oldest backlog needs no special handling here.
"""

from __future__ import annotations

from sathop.shared.flush_buffer import FlushBuffer
from sathop.shared.protocol import ProgressBatch, ProgressBatchItem, ProgressEvent

# Display-only, tolerant of seconds of staleness: a relaxed interval batches
# harder (fewer requests), and a large max_batch keeps a chatty bundle from
# spilling into many small flushes.
_PROGRESS_FLUSH_INTERVAL = 1.0
_PROGRESS_MAX_BATCH = 512


class ProgressBuffer(FlushBuffer[ProgressBatchItem]):
    def __init__(self, client, **kw) -> None:
        kw.setdefault("interval", _PROGRESS_FLUSH_INTERVAL)
        kw.setdefault("max_batch", _PROGRESS_MAX_BATCH)
        super().__init__(self._send, **kw)  # no wake_on — nothing is urgent
        self._client = client

    def enqueue_event(self, granule_id: str, event: ProgressEvent) -> None:
        """Non-blocking: tag the checkpoint with its granule and buffer it."""
        self.enqueue(ProgressBatchItem(granule_id=granule_id, event=event))

    async def _send(self, batch: list[ProgressBatchItem]) -> None:
        await self._client.report_progress_batch(ProgressBatch(items=batch))
