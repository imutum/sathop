"""Admin / operational endpoints. Used by reconcile CLI and Web UI dashboards."""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop import __version__
from sathop.shared.protocol import format_bundle_ref

from ..config import require_token, settings
from ..db import Batch, Bundle, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from .admin_readmodels import (
    NON_TERMINAL,
    STUCK_AGE_HOURS,
    admin_overview,
    clamp_limit,
    in_flight_granule_rows,
    stuck_granule_rows,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_token)])


@router.get("/overview")
async def overview(s: AsyncSession = Depends(session)) -> dict:
    return await admin_overview(s, now=datetime.now(UTC))


@router.get("/in-flight")
async def list_in_flight(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    limit = clamp_limit(limit, max_value=200)
    return await in_flight_granule_rows(s, limit=limit)


@router.get("/stuck/{state}")
async def list_stuck(state: str, s: AsyncSession = Depends(session)) -> list[dict]:
    if state not in NON_TERMINAL:
        raise HTTPException(400, f"invalid state {state!r}; expected one of {sorted(NON_TERMINAL)}")
    return await stuck_granule_rows(s, now=datetime.now(UTC), state=state, limit=100)


@router.get("/stuck")
async def list_stuck_all(
    limit: int = 50,
    s: AsyncSession = Depends(session),
) -> list[dict]:
    limit = clamp_limit(limit, max_value=500)
    return await stuck_granule_rows(s, now=datetime.now(UTC), limit=limit)


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
        b
        for b in bundles
        if in_use.get(format_bundle_ref(b.name, b.version), 0) == 0 and b.uploaded_at < threshold
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

    # Actual delete: stage row deletes, decide which blobs are orphaned post-
    # delete (a sha shared by two rows where we delete one must keep the blob),
    # commit, then unlink. Order matters: unlinking before commit means a
    # rollback would leave dangling DB rows referencing missing blobs.
    deleted_meta: list[dict[str, Any]] = []
    freed = 0
    shas: set[str] = set()
    for b in candidates:
        deleted_meta.append({"name": b.name, "version": b.version, "size": b.size, "sha256": b.sha256})
        freed += b.size
        shas.add(b.sha256)
        await s.delete(b)
    await s.flush()

    orphan_shas: list[str] = []
    for sha in shas:
        others = await s.scalar(select(func.count()).select_from(Bundle).where(Bundle.sha256 == sha))
        if not others:
            orphan_shas.append(sha)

    if deleted_meta:
        await log(s, "bundles", f"GC deleted {len(deleted_meta)} bundle(s) ({freed} bytes)")
    await commit_and_publish(s, "bundles" if deleted_meta else None)

    unlinked: list[str] = []
    for sha in orphan_shas:
        blob = settings.bundle_storage / f"{sha}.zip"
        if blob.is_file():
            blob.unlink()
            unlinked.append(sha)

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
