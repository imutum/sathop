from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import Scope

from . import event_store, redis_bus
from .db import utcnow

log = logging.getLogger("sathop.pubsub")

# Cross-process pub/sub channel. When redis_bus is enabled, every nudge is
# PUBLISHed here and each process's run_listener() re-emits it to its own local
# SSE subscribers — so a state change handled by one uvicorn worker reaches
# browsers connected to any worker.
_CHANNEL = "sathop:pubsub"

_subscribers: set[asyncio.Queue[dict]] = set()
_QUEUE_MAX = 512

# Per-scope nudge coalescing. During high-throughput delivery every receiver ack
# publishes a `batches` (and `events`) nudge; without coalescing each one is a
# socket write + client refetch per open Web UI tab. Each scope gets its own 1s
# window: the first nudge of an idle scope fans out at once (leading edge — a
# sparse change stays instant), and repeat nudges of that *same* scope within the
# window collapse into a single trailing flush, so sustained load stays at ~1
# flush/scope/sec. Windows are per-scope, so a `workers` nudge is never delayed by
# an in-flight `batches` window.
_COALESCE_SEC = 1.0
_open_windows: dict[str, asyncio.TimerHandle] = {}  # scope -> active window timer
_repeat: set[str] = set()  # scopes nudged again during their open window
_loop: asyncio.AbstractEventLoop | None = None


def _fan_out(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("subscriber queue full, dropping event: %s", event)


def _close_window(scope: str) -> None:
    # Trailing edge: if the scope was nudged again during the window, flush one
    # coalesced nudge and keep the window open another cycle; otherwise close it
    # so the next nudge leads again immediately.
    if scope in _repeat:
        _repeat.discard(scope)
        _fan_out({"scope": scope})
        if _loop is not None:
            _open_windows[scope] = _loop.call_later(_COALESCE_SEC, _close_window, scope)
    else:
        _open_windows.pop(scope, None)


def _coalesce(scope: str) -> None:
    global _loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _fan_out({"scope": scope})  # no running loop (sync context) — emit now, can't schedule
        return
    if loop is not _loop:  # new event loop (per-test or restart) — drop stale window state
        _loop = loop
        _open_windows.clear()
        _repeat.clear()
    if scope in _open_windows:
        _repeat.add(scope)  # within the window: coalesce; delivered on the trailing flush
    else:
        _fan_out({"scope": scope})  # leading edge: deliver at once, open the window
        _open_windows[scope] = loop.call_later(_COALESCE_SEC, _close_window, scope)


def _local_publish(event: dict) -> None:
    """Fan an event out to this process's SSE subscribers.

    Plain scope nudges (``{"scope": <str>}``) are coalesced per scope into a 1s
    window so a burst collapses to ~1 nudge/scope/sec. ``__shutdown__`` and
    data-carrying events (e.g. progress, which also carries granule/batch ids)
    pass through immediately."""
    scope = event.get("scope")
    if event.keys() == {"scope"} and isinstance(scope, str) and scope != "__shutdown__":
        _coalesce(scope)
    else:
        _fan_out(event)


def publish(event: dict) -> None:
    """Publish a nudge/event to all SSE subscribers across all processes.

    With redis_bus enabled, every event except ``__shutdown__`` is PUBLISHed to
    the shared channel and re-emitted locally by each process's listener;
    coalescing happens per-process on receive. ``__shutdown__`` stays local — it
    only needs to wake *this* process's streams before it exits, and uvicorn's
    SIGTERM-to-all-workers + ``timeout_graceful_shutdown`` backstop covers the
    rest. Single-process (no redis) goes straight to the local fan-out."""
    c = redis_bus.sync() if redis_bus.enabled() else None
    if c is not None and event.get("scope") != "__shutdown__":
        try:
            c.publish(_CHANNEL, json.dumps(event))
            return
        except Exception:
            log.exception("redis publish failed; falling back to local fan-out")
    _local_publish(event)


async def run_listener() -> None:
    """Per-process loop: re-emit cross-process nudges to local SSE subscribers.

    Spawned in lifespan only when redis_bus is enabled. Reconnects on error;
    exits when shutdown is requested."""
    c = redis_bus.aclient()
    if c is None:
        return
    while not _shutdown_requested:
        try:
            ps = c.pubsub()
            await ps.subscribe(_CHANNEL)
            async for msg in ps.listen():
                if _shutdown_requested:
                    break
                if msg.get("type") != "message":
                    continue
                try:
                    _local_publish(json.loads(msg["data"]))
                except Exception:
                    log.exception("dropping malformed pubsub message")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pubsub listener error; reconnecting")
            await asyncio.sleep(1)


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


_shutdown_requested = False


def request_shutdown() -> None:
    """Signal active SSE streams to close so uvicorn's graceful shutdown isn't
    blocked by idle long-lived connections. Publishes a wake event so a stream
    parked in ``q.get()`` returns at once and observes the flag; new streams see
    it at the top of their loop. ``timeout_graceful_shutdown`` is the backstop."""
    global _shutdown_requested
    _shutdown_requested = True
    publish({"scope": "__shutdown__"})


def is_shutting_down() -> bool:
    return _shutdown_requested


def reset_shutdown() -> None:
    """Test helper — clear the flag between in-process test cases."""
    global _shutdown_requested
    _shutdown_requested = False


def reset_coalesce() -> None:
    """Test helper — drop coalescing window state between in-process test cases.

    Cancels any pending window timers so a trailing flush scheduled by one test
    can't fan out into the next (anyio reuses one event loop across the suite)."""
    global _loop
    for handle in _open_windows.values():
        handle.cancel()
    _open_windows.clear()
    _repeat.clear()
    _loop = None


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
        dict(source=source, message=message, level=level, granule_id=granule_id, batch_id=batch_id)
    )
