"""Server-Sent Events feed for Web UI.

Emits one line-delimited JSON event per `pubsub.publish()`. Clients open
`/api/stream?token=...` (EventSource can't set Authorization headers) and
receive `{"scope": "batches"|"workers"|"receivers"|"events"}` nudges to
re-query the matching resource.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import require_token_or_query
from ..pubsub import subscribe

router = APIRouter(tags=["stream"], dependencies=[Depends(require_token_or_query)])

_HEARTBEAT_SEC = 20


@router.get("/stream")
async def stream() -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        yield b"event: ready\ndata: {}\n\n"
        with subscribe() as q:
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                    yield f"data: {json.dumps(evt)}\n\n".encode()
                except TimeoutError:
                    yield b": keepalive\n\n"  # SSE comment line

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
