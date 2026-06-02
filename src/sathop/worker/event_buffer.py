"""Worker-side transition-event buffer — a FlushBuffer of GranuleEvents.

Coalesces state events across all in-flight granules into batched POSTs so the
orchestrator pays its per-request cost once per flush, not once per event (that
framework/ORM tax is the measured single-core wall), and the handler never
awaits the orch mid-pipeline. Terminal events (objects / failure / delete) wake
the flusher at once so their loss window stays ~one in-flight POST. Reliability
and ordering are handled by FlushBuffer; this layer only maps events to the
batch POST and surfaces orch-side revocations.
"""

from __future__ import annotations

import logging

from sathop.shared.flush_buffer import FlushBuffer
from sathop.shared.protocol import WorkerEventBatch
from sathop.shared.state_machine import GranuleEvent

log = logging.getLogger("sathop.worker.events")

# Events whose loss would strand a granule (objects / failure / delete) — flush
# at once rather than waiting out the interval.
_TERMINAL_KINDS = frozenset({"upload_completed", "processing_failed", "delete_confirmed"})


def _is_terminal(event: GranuleEvent) -> bool:
    return event.kind in _TERMINAL_KINDS


class EventBuffer(FlushBuffer[GranuleEvent]):
    def __init__(self, client, **kw) -> None:
        super().__init__(self._send, wake_on=_is_terminal, **kw)
        self._client = client
        # granule_ids whose batch is mid-flight (sliced out of _q, POST not yet
        # confirmed). Tracked so pending_granule_ids() has no gap during the POST.
        self._inflight_gids: frozenset[str] = frozenset()

    async def _send(self, batch: list[GranuleEvent]) -> None:
        self._inflight_gids = frozenset(e.granule_id for e in batch)
        try:
            resp = await self._client.emit_events_batch(WorkerEventBatch(events=batch))
        finally:
            # On failure FlushBuffer re-queues the batch into _q (sync, no await
            # before the next loop turn), so clearing here leaves no uncovered window.
            self._inflight_gids = frozenset()
        if resp.revoked_granule_ids:
            log.info("orch revoked %d granule(s) on event flush", len(resp.revoked_granule_ids))

    def pending_granule_ids(self) -> set[str]:
        """granule_ids whose transition events the worker still owes the orchestrator
        (queued or mid-flush). The heartbeat unions these into active_granule_ids so
        reclaim_inactive_leases never reclaims a granule whose terminal event has been
        produced but not yet applied — reclaiming it would discard the finished
        download/process/upload and force a full end-to-end redo."""
        return {e.granule_id for e in self._q} | self._inflight_gids
