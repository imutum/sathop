from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import Scope

from . import event_store
from .db import utcnow

log = logging.getLogger("sathop.pubsub")

_subscribers: set[asyncio.Queue[dict]] = set()
_QUEUE_MAX = 512


def publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("subscriber queue full, dropping event: %s", event)


@contextmanager
def subscribe() -> Iterator[asyncio.Queue[dict]]:
    """Yield a fresh subscriber queue. Caller awaits ``q.get()`` per event.

    Returning the queue (not an async iterator) is deliberate: SSE handlers
    race ``q.get()`` against a heartbeat via ``asyncio.wait_for``; cancelling
    a wrapped ``__anext__`` corrupts an async generator (subsequent calls
    raise ``StopAsyncIteration``), but cancelling a fresh ``q.get()`` each
    iteration is safe.
    """
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    try:
        yield q
    finally:
        _subscribers.discard(q)


def subscriber_count() -> int:
    return len(_subscribers)


_PENDING_EVENTS = "sathop_pending_events"


def publish_scopes(s: AsyncSession, *scopes: Scope | None) -> None:
    pending = s.info.pop(_PENDING_EVENTS, ())
    if pending:
        now = utcnow()
        for e in pending:
            event_store.append(ts=now, **e)
    extra: tuple[Scope, ...] = (Scope.EVENTS,) if pending else ()
    for scope in dict.fromkeys(filter(None, (*scopes, *extra))):
        publish({"scope": scope.value})


async def commit_and_publish(s: AsyncSession, *scopes: Scope | None) -> None:
    await s.commit()
    publish_scopes(s, *scopes)


async def log_event(
    s: AsyncSession,
    source: str,
    message: str,
    level: str = "info",
    granule_id: str | None = None,
    batch_id: str | None = None,
) -> None:
    """Stage an event for in-memory persistence after commit.

    Events are buffered on ``s.info`` and flushed by ``publish_scopes`` (called
    from ``commit_and_publish``) so a rolled-back transaction discards its
    events — no phantom entries in the event feed."""
    s.info.setdefault(_PENDING_EVENTS, []).append(
        dict(source=source, message=message, level=level,
             granule_id=granule_id, batch_id=batch_id)
    )
