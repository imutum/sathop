"""Coalescing flush buffer shared by the worker (transition events) and receiver
(ack reports).

Both face the same problem: a high-frequency stream of small POSTs, each paying
the orchestrator's per-request cost (routing, one session, one commit, one SSE
nudge). Buffering them and flushing in batches amortizes that fixed cost across
the batch, and `enqueue` is non-blocking so the producer never awaits the orch
mid-pipeline.

Reliability:
  - A failed flush re-queues its items (front) so a transient orch blip doesn't
    drop them; the backlog is bounded and sheds the oldest under a prolonged
    outage (the dropped work is re-driven by the upstream re-offer/re-lease path).
  - On cancellation (graceful drain — producers have already stopped) the whole
    backlog is flushed, so a just-finished producer's last items still land.
FIFO order is preserved: one queue, one serial flush.

Subclass and provide a `_send(batch)` coroutine; optionally pass `wake_on` to
flush immediately when an item that can't wait arrives (e.g. a terminal event).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

log = logging.getLogger("sathop.flush_buffer")

T = TypeVar("T")


class FlushBuffer(Generic[T]):
    def __init__(
        self,
        flush: Callable[[list[T]], Awaitable[None]],
        *,
        interval: float = 0.15,
        max_batch: int = 256,
        max_buffer: int = 8192,
        wake_on: Callable[[T], bool] | None = None,
    ) -> None:
        self._flush_one = flush
        self._wake_on = wake_on
        self._interval = interval
        self._max_batch = max_batch
        self._max_buffer = max_buffer
        self._q: list[T] = []
        self._wake = asyncio.Event()

    def enqueue(self, item: T) -> None:
        """Non-blocking append. A `wake_on` item or a full batch wakes the
        flusher immediately; otherwise it rides the next interval tick."""
        self._q.append(item)
        if (self._wake_on is not None and self._wake_on(item)) or len(self._q) >= self._max_batch:
            self._wake.set()

    async def loop(self) -> None:
        """Flush on the interval tick or an early wake, until cancelled. On
        cancellation (drain — producers have stopped, no new items arrive) drain
        the whole backlog so just-finished producers' last items still land."""
        try:
            while True:
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
            await self._flush_one(batch)
        except Exception as e:
            # Re-queue (front) for another shot; bound the backlog so a long orch
            # outage can't grow memory without limit.
            self._q = batch + self._q
            over = len(self._q) - self._max_buffer
            if over > 0:
                self._q = self._q[over:]
                log.warning("flush buffer over %d — dropped %d oldest", self._max_buffer, over)
            log.warning("flush failed (%d items held): %s", len(batch), e)
