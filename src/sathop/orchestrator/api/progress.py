"""Granule progress: ephemeral telemetry with SSE push.

Progress checkpoints are useful for ~5 seconds while a download/process step is
active, then superseded by stage-timing rows. Kept in per-process in-memory
dicts, never persisted — workers re-report within seconds after a restart.

Multi-process (Postgres) note: progress is deliberately NOT shared across uvicorn
processes. It was once a DB table (`granule_progress`, now in db._OBSOLETE_TABLES
and auto-dropped) and was moved fully in-memory for throughput; re-introducing a
write on every progress POST (~hundreds/sec under load) would tax the very hot
path this mode exists to relieve. So a granule's timeline lives on whichever
process received its POST: a GET served by another process may see it empty.
The SSE `progress` nudge still fans out cross-process via LISTEN/NOTIFY, so the
UI is told to refetch; this is acceptable degradation for display-only data that
is stale within seconds. Authoritative state is untouched.
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

    The batch_id is self-resolved from the stored timeline so callers need only
    the granule id. A granule with no timeline is a clean no-op."""
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
    # Bare {scope} so the nudge rides pubsub's 1s per-scope coalesce window — a
    # burst of progress POSTs collapses to ~1 fan-out/sec instead of one
    # NOTIFY + UI refetch per POST. The UI invalidates the progress queries by
    # scope (it never reads the ids off the nudge), so dropping them is free.
    publish({"scope": "progress"})
    return {"ok": True}


@router.get("/granules/{granule_id}/progress")
async def granule_timeline(granule_id: str) -> list[dict]:
    return list(_by_granule.get(granule_id, []))


@router.get("/batches/{batch_id}/progress/latest")
async def batch_latest(batch_id: str) -> dict[str, dict]:
    batch_map = _latest_by_batch.get(batch_id)
    return dict(batch_map) if batch_map else {}
