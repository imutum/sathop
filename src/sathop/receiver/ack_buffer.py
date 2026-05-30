"""Receiver-side ack buffer — a FlushBuffer of AckReports.

The delivery-path twin of the worker's EventBuffer: coalesces per-object ack
reports into batched POSTs so the orchestrator pays its per-request cost once
per flush instead of once per delivered object. Acks are best-effort (a dropped
one just re-offers the object on the next pull), and there is no "terminal" ack
to rush — every ack rides the interval (or a full batch). Reliability/ordering
come from FlushBuffer; this layer only maps acks to the batch POST.
"""

from __future__ import annotations

from sathop.shared.flush_buffer import FlushBuffer
from sathop.shared.protocol import AckBatch, AckReport


class AckBuffer(FlushBuffer[AckReport]):
    def __init__(self, client, **kw) -> None:
        super().__init__(self._send, **kw)
        self._client = client

    async def _send(self, batch: list[AckReport]) -> None:
        await self._client.ack_batch(AckBatch(acks=batch))
