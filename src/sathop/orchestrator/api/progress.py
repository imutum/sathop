"""Granule progress: in-memory store with SSE push.

Progress checkpoints are ephemeral telemetry — useful for ~5 seconds while a
download or processing step is active, then superseded by stage-timing rows.
Storing them in SQLite was the original design; this revision keeps them purely
in RAM to eliminate ~50% of all orchestrator DB writes under load.

Trade-off: progress history does not survive orchestrator restart. Workers
re-report on their next callback, so the UI recovers within seconds.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends

from sathop.shared.protocol import ProgressEvent

from ..config import require_token
from ..db import utcnow
from ..pubsub import publish

router = APIRouter(tags=["progress"], dependencies=[Depends(require_token)])

_MAX_ENTRIES_PER_GRANULE = 200
_by_granule: dict[str, list[dict]] = {}
_latest_by_batch: dict[str, dict[str, dict]] = {}


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

    The batch index (`_latest_by_batch`) is private to this module: callers
    pass only the granule id and the batch_id is self-resolved from the stored
    entry, so no caller has to know progress keeps a secondary index. A granule
    with no timeline is a clean no-op."""
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
    return list(_by_granule.get(granule_id, []))


@router.get("/batches/{batch_id}/progress/latest")
async def batch_latest(batch_id: str) -> dict[str, dict]:
    batch_map = _latest_by_batch.get(batch_id)
    return dict(batch_map) if batch_map else {}
