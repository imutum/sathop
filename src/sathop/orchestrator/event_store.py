"""Ephemeral event log — display-only audit data, no business logic reads it.

Two backends, selected by ``db.is_postgres()``:
  - **SQLite (single-process default)**: an in-memory capped deque behind the
    sync API below (``append``/``query``/…). Lost on restart; workers/receivers
    re-populate context within one heartbeat cycle.
  - **Postgres (multi-process)**: the ``Event`` table (see ``db.py``). Rows are
    written transactionally with the transition that emits them (via
    ``pubsub.log_event`` → ``append_event_row``) and read back through the
    async ``*_db`` helpers on the request/sweeper session, so nothing here
    blocks the event loop and the feed is shared across uvicorn processes.

The two paths never mix: the sync deque is used iff ``is_postgres()`` is False,
the async table iff it's True. Callers branch at the call site (the established
dual-backend pattern), so this module needs no runtime toggle of its own.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_EVENTS = 20_000


@dataclass(slots=True)
class MemEvent:
    id: int
    ts: datetime
    level: str
    source: str
    granule_id: str | None
    batch_id: str | None
    message: str


_store: deque[MemEvent] = deque(maxlen=_MAX_EVENTS)
_next_id: int = 1
_lock = threading.Lock()


def _event_dict(e: MemEvent) -> dict:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
        "level": e.level,
        "source": e.source,
        "granule_id": e.granule_id,
        "batch_id": e.batch_id,
        "message": e.message,
    }


# ── SQLite in-memory backend (single-process) ────────────────────────────────


def append(
    *,
    ts: datetime,
    level: str,
    source: str,
    message: str,
    granule_id: str | None = None,
    batch_id: str | None = None,
) -> int:
    global _next_id
    with _lock:
        eid = _next_id
        _next_id += 1
        _store.append(
            MemEvent(
                id=eid,
                ts=ts,
                level=level,
                source=source,
                granule_id=granule_id,
                batch_id=batch_id,
                message=message,
            )
        )
    return eid


def query(
    *,
    limit: int = 100,
    since_id: int = 0,
    before_id: int | None = None,
    batch_id: str | None = None,
    granule_id: str | None = None,
    source: str | None = None,
    level: str | None = None,
) -> list[dict]:
    results: list[dict] = []
    with _lock:
        for e in reversed(_store):  # newest-first
            if e.id <= since_id:
                break
            if before_id is not None and e.id >= before_id:
                continue
            if batch_id is not None and e.batch_id != batch_id:
                continue
            if granule_id is not None and e.granule_id != granule_id:
                continue
            if source is not None and e.source != source:
                continue
            if level is not None and e.level != level:
                continue
            results.append(_event_dict(e))
            if len(results) >= limit:
                break
    return results


def last_n(n: int) -> list[dict]:
    with _lock:
        out: list[dict] = []
        for e in reversed(_store):
            out.append(_event_dict(e))
            if len(out) >= n:
                break
        return out


def count_by_level_since(since: datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    with _lock:
        for e in reversed(_store):
            if e.ts < since:
                break  # deque is chronological → all older entries are too
            counts[e.level] = counts.get(e.level, 0) + 1
    return counts


def evict_by_granule_ids(gids: set[str]) -> int:
    with _lock:
        before = len(_store)
        keep = [e for e in _store if e.granule_id not in gids]
        _store.clear()
        _store.extend(keep)
        return before - len(_store)


def prune_before(cutoff: datetime) -> int:
    with _lock:
        n = 0
        while _store and _store[0].ts < cutoff:
            _store.popleft()
            n += 1
        return n


def _clear() -> None:
    global _next_id
    with _lock:
        _store.clear()
        _next_id = 1


# ── Postgres backend (multi-process): the Event table ────────────────────────


def _row_dict(e) -> dict:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
        "level": e.level,
        "source": e.source,
        "granule_id": e.granule_id,
        "batch_id": e.batch_id,
        "message": e.message,
    }


def append_event_row(
    s: AsyncSession,
    *,
    ts: datetime,
    level: str,
    source: str,
    message: str,
    granule_id: str | None = None,
    batch_id: str | None = None,
) -> None:
    """Stage one Event row on the live session. Sync (s.add does not flush): it
    commits atomically with the transition's transaction and rolls back with it.
    Called from pubsub.log_event in Postgres mode."""
    from .db import Event

    s.add(
        Event(
            ts=ts,
            level=level,
            source=source,
            message=message,
            granule_id=granule_id,
            batch_id=batch_id,
        )
    )


async def query_db(
    s: AsyncSession,
    *,
    limit: int = 100,
    since_id: int = 0,
    before_id: int | None = None,
    batch_id: str | None = None,
    granule_id: str | None = None,
    source: str | None = None,
    level: str | None = None,
) -> list[dict]:
    from .db import Event

    stmt = select(Event)
    if since_id:
        stmt = stmt.where(Event.id > since_id)
    if before_id is not None:
        stmt = stmt.where(Event.id < before_id)
    if batch_id is not None:
        stmt = stmt.where(Event.batch_id == batch_id)
    if granule_id is not None:
        stmt = stmt.where(Event.granule_id == granule_id)
    if source is not None:
        stmt = stmt.where(Event.source == source)
    if level is not None:
        stmt = stmt.where(Event.level == level)
    stmt = stmt.order_by(Event.id.desc()).limit(limit)
    rows = (await s.execute(stmt)).scalars().all()
    return [_row_dict(e) for e in rows]


async def last_n_db(s: AsyncSession, n: int) -> list[dict]:
    return await query_db(s, limit=n)


async def count_by_level_since_db(s: AsyncSession, since: datetime) -> dict[str, int]:
    from .db import Event

    rows = (
        await s.execute(select(Event.level, func.count()).where(Event.ts >= since).group_by(Event.level))
    ).all()
    return {level: n for level, n in rows}


async def evict_by_granule_ids_db(s: AsyncSession, gids: set[str]) -> int:
    if not gids:
        return 0
    from .db import Event

    r = await s.execute(delete(Event).where(Event.granule_id.in_(gids)))
    return getattr(r, "rowcount", 0) or 0


async def prune_before_db(s: AsyncSession, cutoff: datetime) -> int:
    from .db import Event

    r = await s.execute(delete(Event).where(Event.ts < cutoff))
    return getattr(r, "rowcount", 0) or 0
