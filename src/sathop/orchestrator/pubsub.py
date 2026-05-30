from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import Scope

from . import db, event_store
from .config import settings
from .db import utcnow

log = logging.getLogger("sathop.pubsub")

# Cross-process pub/sub channel (Postgres mode). Every nudge except __shutdown__
# is sent via NOTIFY and each process's run_listener() (a dedicated asyncpg
# LISTEN connection) re-emits it to its own local SSE subscribers — so a state
# change handled by one uvicorn worker reaches browsers connected to any worker.
# asyncpg LISTEN/NOTIFY is fully async, so nothing here blocks the event loop.
_CHANNEL = "sathop_pubsub"

# Outbound NOTIFY queue: publish() (sometimes called from sync code on the loop
# thread) enqueues without blocking; run_notify_sender() drains it on a dedicated
# connection. Bounded so a stalled sender sheds load instead of growing unbounded.
_notify_q: asyncio.Queue[str] = asyncio.Queue(maxsize=4096)


def _dsn() -> str:
    """Plain libpq DSN for a raw asyncpg connection (LISTEN/NOTIFY needs the
    driver directly, not the SQLAlchemy '+asyncpg' URL). Strip '+asyncpg' from
    the scheme component only, so a password that happens to contain that literal
    is never corrupted."""
    from urllib.parse import urlparse, urlunparse

    p = urlparse(settings.database_url)
    return urlunparse((p.scheme.replace("+asyncpg", ""), p.netloc, p.path, p.params, p.query, p.fragment))


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

    In Postgres mode every event except ``__shutdown__`` is enqueued for a NOTIFY
    and re-emitted in each process by its LISTEN connection (this process included,
    so local subscribers get it that way); coalescing happens per-process on
    receive. ``__shutdown__`` stays local — it only needs to wake *this* process's
    streams before it exits; uvicorn's SIGTERM-to-all-workers +
    ``timeout_graceful_shutdown`` covers the rest. Single-process (SQLite) goes
    straight to the local fan-out."""
    if db.is_postgres() and event.get("scope") != "__shutdown__":
        try:
            _notify_q.put_nowait(json.dumps(event))
            return
        except asyncio.QueueFull:
            # Sender is stalled: shed the cross-process fan-out but still deliver
            # to THIS process's subscribers (in PG mode local delivery normally
            # rides the NOTIFY round-trip, so a bare drop would blind the local
            # tab too). Falls through to the local fan-out below.
            log.warning("notify queue full, delivering nudge locally only: %s", event)
    _local_publish(event)


async def run_notify_sender() -> None:
    """Drain the outbound queue, emitting one NOTIFY per nudge on a dedicated
    asyncpg connection. Spawned in lifespan in Postgres mode."""
    import asyncpg

    conn = None
    delay = 1.0
    while not _shutdown_requested:
        payload: str | None = None
        try:
            if conn is None:
                conn = await asyncpg.connect(_dsn())
                delay = 1.0  # reconnected — reset backoff
            payload = await asyncio.wait_for(_notify_q.get(), timeout=1.0)
            await conn.execute("SELECT pg_notify($1, $2)", _CHANNEL, payload)
            payload = None  # sent — don't requeue on a later error
        except TimeoutError:
            continue  # idle tick — re-check shutdown flag
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("notify sender error; reconnecting in %.0fs", delay)
            if conn is not None:
                await conn.close()
            conn = None
            # Don't lose a nudge already pulled off the queue — best-effort requeue.
            if payload is not None:
                try:
                    _notify_q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)  # capped backoff so an outage isn't a connect storm
    if conn is not None:
        await conn.close()


async def run_listener() -> None:
    """Per-process LISTEN loop: re-emit cross-process nudges to local SSE
    subscribers. asyncpg delivers notifications via a sync callback, which feeds
    the same coalescing/fan-out as a local publish. Reconnects on error."""
    import asyncpg

    def _on_notify(_conn, _pid, _chan, payload: str) -> None:
        try:
            _local_publish(json.loads(payload))
        except Exception:
            log.exception("dropping malformed pubsub notification")

    conn = None
    delay = 1.0
    while not _shutdown_requested:
        try:
            if conn is None:
                conn = await asyncpg.connect(_dsn())
                await conn.add_listener(_CHANNEL, _on_notify)
                delay = 1.0  # reconnected — reset backoff
            await asyncio.sleep(1.0)  # asyncpg dispatches notifications in the background
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("pubsub listener error; reconnecting in %.0fs", delay)
            if conn is not None:
                await conn.close()
            conn = None
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)  # capped backoff so an outage isn't a connect storm
    if conn is not None:
        await conn.close()


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


_PENDING_EVENTS = "sathop_pending_events"  # SQLite: buffer flushed post-commit
_HAD_EVENTS = "sathop_had_events"  # Postgres: gate for the EVENTS scope nudge


def publish_scopes(s: AsyncSession, *scopes: Scope | None) -> None:
    # SQLite: flush the buffered events into the in-memory store now (after the
    # commit), so a rolled-back txn — which never reaches here — discards them.
    pending = s.info.pop(_PENDING_EVENTS, ())
    if pending:
        now = utcnow()
        for e in pending:
            event_store.append(ts=now, **e)
    # Postgres: rows were already staged on the session by log_event and committed
    # with the txn; this flag (decoupled from persistence) just gates the nudge.
    had_pg = s.info.pop(_HAD_EVENTS, False)
    extra: tuple[Scope, ...] = (Scope.EVENTS,) if (pending or had_pg) else ()
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
    """Record an event, atomic with the current transaction.

    Postgres: stage an ``Event`` row on the session (committed with the txn,
    discarded on rollback) and flag the session so ``publish_scopes`` fires the
    EVENTS nudge. SQLite: buffer on ``s.info`` for ``publish_scopes`` to flush
    into the in-memory store after commit. Either way a rolled-back transaction
    leaves no phantom event. Stays ``async`` (s.add is sync) only to spare its
    ~40 call sites a signature change. Any path that calls this MUST reach
    ``publish_scopes``/``commit_and_publish`` for the row to persist (PG) or the
    nudge to fire."""
    if db.is_postgres():
        event_store.append_event_row(
            s,
            ts=utcnow(),
            source=source,
            message=message,
            level=level,
            granule_id=granule_id,
            batch_id=batch_id,
        )
        s.info[_HAD_EVENTS] = True
        return
    s.info.setdefault(_PENDING_EVENTS, []).append(
        dict(source=source, message=message, level=level, granule_id=granule_id, batch_id=batch_id)
    )
