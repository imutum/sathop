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

    async def _send(self, batch: list[GranuleEvent]) -> None:
        resp = await self._client.emit_events_batch(WorkerEventBatch(events=batch))
        if resp.revoked_granule_ids:
            log.info("orch revoked %d granule(s) on event flush", len(resp.revoked_granule_ids))
