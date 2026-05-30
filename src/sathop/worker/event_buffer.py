"""Worker-side transition-event buffer.

Coalesces state events across all in-flight granules into batched POSTs, so the
orchestrator pays its per-request cost (routing, one session, one commit, one SSE
nudge) once per flush instead of once per event — that framework/ORM tax is the
measured single-core wall. It also decouples the handler from orchestrator
latency: ``enqueue`` is non-blocking, so a handler never awaits the orch mid-
pipeline (removing the in-semaphore round-trips that lengthened slot occupancy).

Reliability mirrors the old best-effort emits:
  - A failed flush re-queues its events (front), so a transient orch blip doesn't
    drop a terminal ``UploadCompleted`` / ``ProcessingFailed``. The backlog is
    bounded; a prolonged outage sheds the oldest events (the granule's lease
    expires and it is re-done — the existing strand-and-reclaim path).
  - A worker crash loses only un-flushed events. Terminal events wake the flusher
    immediately, so that window is ~the in-flight POST, as before.
Per-granule order is preserved: a single FIFO queue, drained by one serial flush.
"""

from __future__ import annotations

import asyncio
import logging

from sathop.shared.protocol import WorkerEventBatch
from sathop.shared.state_machine import GranuleEvent

log = logging.getLogger("sathop.worker.events")

# Events whose loss would strand a granule (objects / failure / delete) — flush at
# once rather than waiting out the interval.
_TERMINAL_KINDS = frozenset({"upload_completed", "processing_failed", "delete_confirmed"})


class EventBuffer:
    def __init__(
        self,
        client,
        *,
        interval: float = 0.15,
        max_batch: int = 256,
        max_buffer: int = 8192,
    ) -> None:
        self._client = client
        self._interval = interval
        self._max_batch = max_batch
        self._max_buffer = max_buffer
        self._q: list[GranuleEvent] = []
        self._wake = asyncio.Event()
        self._stopped = False

    def enqueue(self, event: GranuleEvent) -> None:
        """Non-blocking append. Terminal events wake the flusher immediately;
        intermediate events ride the next interval tick (or a full batch)."""
        self._q.append(event)
        if event.kind in _TERMINAL_KINDS or len(self._q) >= self._max_batch:
            self._wake.set()

    async def loop(self) -> None:
        """Flush on the interval tick or an early wake, until cancelled. On
        cancellation (worker drain — handlers have already stopped, so no new
        events arrive) drain the whole backlog so just-finished handlers'
        terminal events still land."""
        try:
            while not self._stopped:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
                self._wake.clear()
                await self._flush()
        except asyncio.CancelledError:
            while self._q:
                before = len(self._q)
                await self._flush()
                if len(self._q) >= before:  # flush failed (re-queued) → orch down, stop
                    break
            raise

    async def _flush(self) -> None:
        if not self._q:
            return
        batch = self._q[: self._max_batch]
        self._q = self._q[self._max_batch :]
        try:
            resp = await self._client.emit_events_batch(WorkerEventBatch(events=batch))
            if resp.revoked_granule_ids:
                log.info("orch revoked %d granule(s) on event flush", len(resp.revoked_granule_ids))
        except Exception as e:
            # Re-queue (front) so terminal events get another shot; bound the backlog
            # so a long orch outage can't grow memory without limit.
            self._q = batch + self._q
            over = len(self._q) - self._max_buffer
            if over > 0:
                self._q = self._q[over:]
                log.warning("event buffer over %d — dropped %d oldest", self._max_buffer, over)
            log.warning("event batch flush failed (%d events held): %s", len(batch), e)
