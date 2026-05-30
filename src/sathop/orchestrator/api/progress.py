"""Granule progress: ephemeral telemetry with SSE push.

Progress checkpoints are useful for ~5 seconds while a download/process step is
active, then superseded by stage-timing rows. Two backends behind one API:
  - **in-memory** dicts (single-process default), zero DB writes.
  - **Redis** (multi-process): per-granule LIST timeline + per-batch HASH of
    latest entries, both TTL'd, so progress reported to any uvicorn process is
    queryable from any other. Never persisted to SQLite either way; workers
    re-report within seconds after a restart.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from fastapi import APIRouter, Depends

from sathop.shared.protocol import ProgressEvent

from .. import redis_bus
from ..config import require_token
from ..db import utcnow
from ..pubsub import publish

_log = logging.getLogger("sathop.orch.progress")

router = APIRouter(tags=["progress"], dependencies=[Depends(require_token)])

_MAX_ENTRIES_PER_GRANULE = 200
_TTL = 300  # display-only; entries are stale after a few seconds anyway
_by_granule: dict[str, list[dict]] = {}
_latest_by_batch: dict[str, dict[str, dict]] = {}


def _r():
    return redis_bus.sync() if redis_bus.enabled() else None


def _tkey(granule_id: str) -> str:
    return f"sathop:pg:t:{granule_id}"


def _bkey(batch_id: str) -> str:
    return f"sathop:pg:b:{batch_id}"


def _make_entry(granule_id: str, batch_id: str, event: ProgressEvent) -> dict:
    return {
        "granule_id": granule_id,
        "batch_id": batch_id,
        "ts": (event.ts or utcnow()).isoformat(),
        "step": event.step,
        "pct": event.pct,
        "detail": event.detail,
    }


def evict_granule(granule_id: str) -> None:
    """Drop a granule's progress timeline and its batch-index entry.

    The batch_id is self-resolved from the stored timeline so callers need only
    the granule id. A granule with no timeline is a clean no-op."""
    r = _r()
    if r is not None:
        # Hot path (every UploadCompleted / lease reclaim) — best-effort so a
        # Redis hiccup never breaks the transition that triggered the evict.
        try:
            first = r.lindex(_tkey(granule_id), 0)
            batch_id = json.loads(first).get("batch_id") if first else None
            p = r.pipeline()
            p.delete(_tkey(granule_id))
            if batch_id:
                p.hdel(_bkey(batch_id), granule_id)
            p.execute()
        except Exception:
            _log.warning("progress.evict_granule: redis unavailable", exc_info=False)
        return
    entries = _by_granule.pop(granule_id, None)
    if not entries:
        return
    batch_id = entries[0].get("batch_id", "")
    batch_map = _latest_by_batch.get(batch_id)
    if batch_map is not None:
        batch_map.pop(granule_id, None)
        if not batch_map:
            del _latest_by_batch[batch_id]


def evict_granules(granule_ids: Iterable[str]) -> None:
    for gid in granule_ids:
        evict_granule(gid)


def _clear() -> None:
    _by_granule.clear()
    _latest_by_batch.clear()


@router.post("/granules/{granule_id}/progress")
async def ingress(granule_id: str, event: ProgressEvent) -> dict:
    batch_id = event.batch_id or ""
    entry = _make_entry(granule_id, batch_id, event)
    r = _r()
    if r is not None:
        raw = json.dumps(entry)
        try:
            p = r.pipeline()
            p.rpush(_tkey(granule_id), raw)
            p.ltrim(_tkey(granule_id), -_MAX_ENTRIES_PER_GRANULE, -1)
            p.expire(_tkey(granule_id), _TTL)
            if batch_id:
                p.hset(_bkey(batch_id), granule_id, raw)
                p.expire(_bkey(batch_id), _TTL)
            p.execute()
        except Exception:
            _log.warning("progress.ingress: redis unavailable", exc_info=False)
    else:
        timeline = _by_granule.setdefault(granule_id, [])
        if len(timeline) < _MAX_ENTRIES_PER_GRANULE:
            timeline.append(entry)
        else:
            timeline[-1] = entry
        if batch_id:
            _latest_by_batch.setdefault(batch_id, {})[granule_id] = entry
    publish({"scope": "progress", "granule_id": granule_id, "batch_id": batch_id})
    return {"ok": True}


@router.get("/granules/{granule_id}/progress")
async def granule_timeline(granule_id: str) -> list[dict]:
    r = _r()
    if r is not None:
        return [json.loads(x) for x in r.lrange(_tkey(granule_id), 0, -1)]
    return list(_by_granule.get(granule_id, []))


@router.get("/batches/{batch_id}/progress/latest")
async def batch_latest(batch_id: str) -> dict[str, dict]:
    r = _r()
    if r is not None:
        return {gid: json.loads(v) for gid, v in r.hgetall(_bkey(batch_id)).items()}
    batch_map = _latest_by_batch.get(batch_id)
    return dict(batch_map) if batch_map else {}
