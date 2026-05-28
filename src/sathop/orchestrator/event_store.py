"""In-memory event log — replaces the ``events`` DB table.

Events are display-only audit data; no business logic reads them. Keeping them
in SQLite added ~2 WAL pages per state-transition commit for no functional
benefit. This module stores events in a capped deque; they survive the process
lifetime but not an orchestrator restart (workers/receivers re-populate context
within one heartbeat cycle).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

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
                id=eid, ts=ts, level=level, source=source,
                granule_id=granule_id, batch_id=batch_id, message=message,
            )
        )
    return eid


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
    with _lock:
        results: list[dict] = []
        for e in reversed(_store):
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
                break
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
