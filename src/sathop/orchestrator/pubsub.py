"""In-process pub/sub + event logging."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from .db import Event

log = logging.getLogger("sathop.pubsub")

_subscribers: set[asyncio.Queue[dict]] = set()
_QUEUE_MAX = 512


def publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("subscriber queue full, dropping event: %s", event)


async def subscribe() -> AsyncIterator[dict]:
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    try:
        while True:
            yield await q.get()
    finally:
        _subscribers.discard(q)


def subscriber_count() -> int:
    return len(_subscribers)


async def log_event(
    s: AsyncSession,
    source: str,
    message: str,
    level: str = "info",
    granule_id: str | None = None,
) -> None:
    s.add(Event(source=source, message=message, level=level, granule_id=granule_id))
    publish({"scope": "events"})
