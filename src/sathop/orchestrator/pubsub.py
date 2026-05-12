from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import Scope

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


def publish_scopes(s: AsyncSession, *scopes: Scope | None) -> None:
    """Emit deduplicated SSE nudges, folding in any ``Scope.EVENTS`` that prior
    ``log_event()`` calls on this session deferred. ``commit_and_publish()``
    wraps ``s.commit()`` + this; reach for this directly only when something
    must run between commit and publish (e.g. shared-file delete: commit →
    unlink blob → publish)."""
    extra: tuple[Scope, ...] = (Scope.EVENTS,) if s.info.pop(_LOG_EVENT_PENDING, False) else ()
    for scope in dict.fromkeys(filter(None, (*scopes, *extra))):
        publish({"scope": scope.value})


async def commit_and_publish(s: AsyncSession, *scopes: Scope | None) -> None:
    await s.commit()
    publish_scopes(s, *scopes)


_LOG_EVENT_PENDING = "sathop_log_event_pending"


async def log_event(
    s: AsyncSession,
    source: str,
    message: str,
    level: str = "info",
    granule_id: str | None = None,
) -> None:
    """Stage an Event row and mark this session for an 'events' SSE nudge —
    the nudge fires only after the caller commits via ``commit_and_publish``
    (or ``publish_scopes``), so SSE consumers never see a phantom event that
    later rolls back."""
    s.add(Event(source=source, message=message, level=level, granule_id=granule_id))
    s.info[_LOG_EVENT_PENDING] = True
