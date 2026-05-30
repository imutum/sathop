"""Ephemeral event log — display-only audit data, no business logic reads it.

Two interchangeable backends behind one sync API (callers are unchanged):
  - **in-memory** capped deque (single-process default).
  - **Redis LIST** (multi-process): ``LPUSH`` + ``LTRIM`` keeps the newest
    ``_MAX_EVENTS`` newest-first; ids come from an ``INCR`` counter so the int
    ``since_id`` pagination contract is preserved. Append is O(1); the
    infrequent query/prune/evict paths read the whole (≤20k) list and filter in
    Python. Both backends lose history on a full restart; workers/receivers
    re-populate context within one heartbeat cycle.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from . import redis_bus

_log = logging.getLogger("sathop.orch.event_store")

_MAX_EVENTS = 20_000
_K = "sathop:events"
_SEQ = "sathop:events:seq"
# Cap how deep a single read scans the Redis list. The list holds up to
# _MAX_EVENTS; pulling all of them over the wire + json.loads on the event loop
# (the read paths run sync) is what saturated Redis and stalled the loop. The
# feed is newest-first, so this window covers the live view and recent
# pagination; older/filtered matches beyond it are dropped (display-only data).
_SCAN_CAP = 2_000


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


def _r():
    return redis_bus.sync() if redis_bus.enabled() else None


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


def append(
    *,
    ts: datetime,
    level: str,
    source: str,
    message: str,
    granule_id: str | None = None,
    batch_id: str | None = None,
) -> int:
    r = _r()
    if r is not None:
        # Best-effort: events are display-only, so a Redis hiccup must never 500
        # the hot transition/heartbeat path that logs them.
        try:
            eid = int(r.incr(_SEQ))
            e = {
                "id": eid,
                "ts": ts.isoformat(),
                "level": level,
                "source": source,
                "granule_id": granule_id,
                "batch_id": batch_id,
                "message": message,
            }
            p = r.pipeline()
            p.lpush(_K, json.dumps(e))
            p.ltrim(_K, 0, _MAX_EVENTS - 1)
            p.execute()
            return eid
        except Exception:
            _log.warning("event_store.append: redis unavailable, dropping event", exc_info=False)
            return -1
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


def _redis_newest_first(r) -> list[dict]:
    """All events as dicts, newest-first (head = highest id)."""
    return [json.loads(x) for x in r.lrange(_K, 0, -1)]


def _redis_rewrite(r, kept_newest_first: list[dict]) -> None:
    p = r.pipeline()
    p.delete(_K)
    if kept_newest_first:
        p.rpush(_K, *[json.dumps(e) for e in kept_newest_first])
    p.execute()


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
    def emit(it):
        results: list[dict] = []
        for e in it:
            if e["id"] <= since_id:
                break
            if before_id is not None and e["id"] >= before_id:
                continue
            if batch_id is not None and e["batch_id"] != batch_id:
                continue
            if granule_id is not None and e["granule_id"] != granule_id:
                continue
            if source is not None and e["source"] != source:
                continue
            if level is not None and e["level"] != level:
                continue
            results.append(e)
            if len(results) >= limit:
                break
        return results

    r = _r()
    if r is not None:
        return emit(json.loads(x) for x in r.lrange(_K, 0, _SCAN_CAP - 1))
    with _lock:
        return emit(_event_dict(e) for e in reversed(_store))


def last_n(n: int) -> list[dict]:
    r = _r()
    if r is not None:
        # Bounded LRANGE — this is the overview's per-second call; pulling the
        # whole list here was the primary Redis-saturation / loop-stall source.
        return [json.loads(x) for x in r.lrange(_K, 0, n - 1)]
    with _lock:
        out: list[dict] = []
        for e in reversed(_store):
            out.append(_event_dict(e))
            if len(out) >= n:
                break
        return out


def count_by_level_since(since: datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    r = _r()
    if r is not None:
        # Bounded scan: counts the most recent _SCAN_CAP events within the
        # window. Undercounts only if more than that many landed in the window
        # — acceptable for a coarse dashboard gauge, and never a full-list pull.
        for x in r.lrange(_K, 0, _SCAN_CAP - 1):
            e = json.loads(x)
            if datetime.fromisoformat(e["ts"]) < since:
                break
            counts[e["level"]] = counts.get(e["level"], 0) + 1
        return counts
    with _lock:
        for e in reversed(_store):
            if e.ts < since:
                break
            counts[e.level] = counts.get(e.level, 0) + 1
    return counts


def evict_by_granule_ids(gids: set[str]) -> int:
    r = _r()
    if r is not None:
        allev = _redis_newest_first(r)
        kept = [e for e in allev if e["granule_id"] not in gids]
        if len(kept) != len(allev):
            _redis_rewrite(r, kept)
        return len(allev) - len(kept)
    with _lock:
        before = len(_store)
        keep = [e for e in _store if e.granule_id not in gids]
        _store.clear()
        _store.extend(keep)
        return before - len(_store)


def prune_before(cutoff: datetime) -> int:
    r = _r()
    if r is not None:
        allev = _redis_newest_first(r)
        kept = [e for e in allev if datetime.fromisoformat(e["ts"]) >= cutoff]
        if len(kept) != len(allev):
            _redis_rewrite(r, kept)
        return len(allev) - len(kept)
    with _lock:
        n = 0
        while _store and _store[0].ts < cutoff:
            _store.popleft()
            n += 1
        return n


def _clear() -> None:
    r = _r()
    if r is not None:
        r.delete(_K, _SEQ)
        return
    global _next_id
    with _lock:
        _store.clear()
        _next_id = 1
