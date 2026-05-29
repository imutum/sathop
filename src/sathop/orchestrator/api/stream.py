"""Server-Sent Events feed for Web UI.

Emits one line-delimited JSON event per `pubsub.publish()`. Clients open
`/api/stream?token=...` (EventSource can't set Authorization headers) and
receive `{"scope": "batches"|"workers"|"receivers"|"events"}` nudges to
re-query the matching resource.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import require_token_or_query
from ..pubsub import is_shutting_down, subscribe

router = APIRouter(tags=["stream"], dependencies=[Depends(require_token_or_query)])

_HEARTBEAT_SEC = 20
_log = logging.getLogger("sathop.orchestrator.stream")


@router.get("/stream")
async def stream() -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        yield b"event: ready\ndata: {}\n\n"
        with subscribe() as q:
            while True:
                # Checked at the loop top so a stream that connects mid-shutdown,
                # or one woken by request_shutdown()'s nudge, exits at once instead
                # of hanging until uvicorn's graceful-shutdown timeout fires.
                if is_shutting_down():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                except TimeoutError:
                    yield b": keepalive\n\n"  # SSE comment line
                    continue
                except asyncio.CancelledError:
                    # Client disconnected — let the framework unwind cleanly.
                    raise
                except Exception:  # pragma: no cover — defensive
                    _log.exception("SSE queue read failed; keeping connection alive")
                    yield b": error\n\n"
                    continue
                if is_shutting_down():  # the wake nudge, or an event racing shutdown
                    break
                try:
                    yield f"data: {json.dumps(evt)}\n\n".encode()
                except (TypeError, ValueError):
                    # A non-serializable event must not tear down every subscriber.
                    _log.warning("SSE event not JSON-serializable, dropping: %r", evt)
                    continue
        yield b"event: shutdown\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
