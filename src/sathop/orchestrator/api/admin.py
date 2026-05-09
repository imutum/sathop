"""Admin / operational endpoints. Used by reconcile CLI and Web UI dashboards."""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop import __version__
from sathop.shared.protocol import NON_TERMINAL_STATES, GranuleState

from ..config import require_token, settings
from ..db import Batch, Bundle, Event, Granule, session, utcnow
from ..pubsub import log_event as log
from ..pubsub import publish

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_token)])

NON_TERMINAL = set(NON_TERMINAL_STATES)

# States where the worker is actively doing work (excluding pending — queued but
# nothing is happening yet — and acked — receiver-side state). Powers the
# Dashboard "currently running" list.
ACTIVE = {
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
    GranuleState.UPLOADED.value,
}

STUCK_AGE_HOURS = 6


def _clamp_limit(limit: int, *, min_value: int = 1, max_value: int = 200) -> int:
    return max(min_value, min(max_value, limit))


def _stuck_threshold(now: datetime) -> datetime:
    return now - timedelta(hours=STUCK_AGE_HOURS)


def _event_summary(e: Event) -> dict[str, Any]:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
        "level": e.level,
        "source": e.source,
        "message": e.message,
    }


def _granule_activity_row(g: Granule) -> dict[str, Any]:
    return {
        "granule_id": g.granule_id,
        "batch_id": g.batch_id,
        "state": g.state,
        "leased_by": g.leased_by,
        "retry_count": g.retry_count,
        "updated_at": g.updated_at.isoformat(),
    }


def _stuck_granule_row(g: Granule, *, now: datetime) -> dict[str, Any]:
    return {
        **_granule_activity_row(g),
        "error": g.error,
        "age_hours": (now - g.updated_at).total_seconds() / 3600,
    }


async def _old_stuck_granules(
    s: AsyncSession,
    *,
    now: datetime,
    state: str | None = None,
    limit: int,
) -> list[Granule]:
    stmt = (
        select(Granule)
        .where(Granule.updated_at < _stuck_threshold(now))
        .order_by(Granule.updated_at.asc())
        .limit(limit)
    )
    if state is None:
        stmt = stmt.where(Granule.state.in_(list(NON_TERMINAL)))
    else:
        stmt = stmt.where(Granule.state == state)
    return (await s.execute(stmt)).scalars().all()


@router.get("/overview")
async def overview(s: AsyncSession = Depends(session)) -> dict:
    state_counts = dict(
        (await s.execute(select(Granule.state, func.count(Granule.granule_id)).group_by(Granule.state))).all()
    )

    now = datetime.now(UTC)
    threshold = now - timedelta(hours=STUCK_AGE_HOURS)
    stuck_stmt = (
        select(Granule.state, func.count(Granule.granule_id))
        .where(Granule.state.in_(list(NON_TERMINAL)))
        .where(Granule.updated_at < threshold)
        .group_by(Granule.state)
    )
    stuck = dict((await s.execute(stuck_stmt)).all())

    last_events = (await s.execute(select(Event).order_by(Event.id.desc()).limit(10))).scalars().all()

    return {
        "state_counts": state_counts,
        "stuck_over_hours": STUCK_AGE_HOURS,
        "stuck_by_state": stuck,
        "last_events": [_event_summary(e) for e in last_events],
    }


@router.get("/in-flight")
async def list_in_flight(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    """Granules the fleet is actively working on right now. Most-recently-updated
    first, which tracks the pipeline's pulse better than by-id or by-created.
    pending is excluded — queued, not running."""
    limit = _clamp_limit(limit, max_value=200)
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.state.in_(list(ACTIVE)))
                .order_by(Granule.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_granule_activity_row(g) for g in rows]


@router.get("/stuck/{state}")
async def list_stuck(state: str, s: AsyncSession = Depends(session)) -> list[dict]:
    if state not in NON_TERMINAL:
        return []
    now = datetime.now(UTC)
    rows = await _old_stuck_granules(s, now=now, state=state, limit=100)
    return [_stuck_granule_row(g, now=now) for g in rows]


@router.get("/stuck")
async def list_stuck_all(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    """Top-N oldest stuck granules across every non-terminal state. Powers the
    Dashboard's drill-down — operator sees count → clicks → sees the actual
    rows to investigate without paging through every state separately."""
    limit = _clamp_limit(limit, max_value=500)
    now = datetime.now(UTC)
    rows = await _old_stuck_granules(s, now=now, limit=limit)
    return [_stuck_granule_row(g, now=now) for g in rows]


class OrchestratorInfo(BaseModel):
    version: str
    python_version: str
    platform: str
    db_path: str
    retain_events_days: int
    retain_deleted_days: int
    retention_sweep_sec: int
    max_inflight_per_worker: int
    max_retries: int
    max_pull_failures: int
    stuck_age_hours: int
    dev_mode: bool
    auth_open: bool


@router.post("/gc/bundles")
async def gc_bundles(
    dry_run: bool = True,
    age_days: int = 30,
    s: AsyncSession = Depends(session),
) -> dict:
    """Garbage-collect orphaned bundle versions: rows with `in_use_count == 0`
    AND `uploaded_at < now - age_days`. Sweeps the registry of stale `bump
    version → upload → discard` cycles that otherwise pile up indefinitely.
    Default `dry_run=True` returns the candidate list only; pass `dry_run=
    false` to actually delete (rows + their orphaned blob files).

    `age_days` lower bound exists to avoid racing with batch-create flows
    that just uploaded a bundle but haven't created the batch yet — 30 days
    is a generous default; operators can pass a smaller value if they know
    they don't have such flows in flight."""
    if age_days < 0:
        return {"error": "age_days must be ≥ 0"}
    threshold = utcnow() - timedelta(days=age_days)
    bundles = (await s.execute(select(Bundle))).scalars().all()
    counts_stmt = select(Batch.bundle_ref, func.count(Batch.batch_id)).group_by(Batch.bundle_ref)
    in_use = {ref: n for ref, n in (await s.execute(counts_stmt)).all()}

    candidates: list[Bundle] = [
        b for b in bundles if in_use.get(f"orch:{b.name}@{b.version}", 0) == 0 and b.uploaded_at < threshold
    ]

    if dry_run:
        return {
            "dry_run": True,
            "age_days": age_days,
            "candidates": [
                {
                    "name": b.name,
                    "version": b.version,
                    "size": b.size,
                    "sha256": b.sha256,
                    "uploaded_at": b.uploaded_at.isoformat(),
                    "age_days": (utcnow() - b.uploaded_at).days,
                }
                for b in candidates
            ],
            "freed_bytes_estimate": sum(b.size for b in candidates),
        }

    # Actual delete: drop rows then resolve blob orphans. Two-phase so the
    # blob unlink decision sees post-delete row counts (a sha shared by two
    # rows where we delete one must keep the blob).
    deleted_meta: list[dict[str, Any]] = []
    freed = 0
    shas: set[str] = set()
    for b in candidates:
        deleted_meta.append({"name": b.name, "version": b.version, "size": b.size, "sha256": b.sha256})
        freed += b.size
        shas.add(b.sha256)
        await s.delete(b)
    await s.flush()

    unlinked: list[str] = []
    for sha in shas:
        others = await s.scalar(select(func.count()).select_from(Bundle).where(Bundle.sha256 == sha))
        if not others:
            blob = settings.bundle_storage / f"{sha}.zip"
            if blob.is_file():
                blob.unlink()
                unlinked.append(sha)

    if deleted_meta:
        await log(s, "bundles", f"GC deleted {len(deleted_meta)} bundle(s) ({freed} bytes)")
    await s.commit()
    if deleted_meta:
        publish({"scope": "bundles"})
    return {
        "dry_run": False,
        "age_days": age_days,
        "deleted": deleted_meta,
        "freed_bytes": freed,
        "unlinked_blobs": len(unlinked),
    }


@router.get("/settings/info", response_model=OrchestratorInfo)
async def orchestrator_info() -> OrchestratorInfo:
    return OrchestratorInfo(
        version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        db_path=str(settings.db_path),
        retain_events_days=settings.retain_events_days,
        retain_deleted_days=settings.retain_deleted_days,
        retention_sweep_sec=settings.retention_sweep_sec,
        max_inflight_per_worker=settings.max_inflight_per_worker,
        max_retries=settings.max_retries,
        max_pull_failures=settings.max_pull_failures,
        stuck_age_hours=STUCK_AGE_HOURS,
        dev_mode=settings.dev,
        auth_open=not settings.token,
    )
