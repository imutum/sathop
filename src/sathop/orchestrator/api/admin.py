"""Admin / operational endpoints. Used by reconcile CLI and Web UI dashboards."""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop import __version__
from sathop.shared.bundle_ref import format_bundle_ref
from sathop.shared.release import normalize_version, write_pending_version
from sathop.shared.state_machine import GranuleState, RequeueGranule, Scope

from ..config import require_token, settings
from ..db import Batch, Bundle, Granule, GranuleObject, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from ._helpers import object_is_exhausted, object_is_pullable
from ._transition import apply_transition
from .admin_readmodels import (
    NON_TERMINAL,
    STUCK_AGE_HOURS,
    admin_overview,
    clamp_limit,
    in_flight_granule_rows,
    stuck_granule_rows,
)
from .progress import evict_granule

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_token)])

# 1s single-flight TTL cache for the overview aggregate: every open UI tab
# refetches it on each 'batches' SSE nudge, so bursts of concurrent calls within
# the window collapse onto one DB computation. Set TTL=0 to disable.
_OVERVIEW_TTL = 1.0
_overview_lock = asyncio.Lock()
_overview_cache: tuple[float, dict] | None = None


def reset_overview_cache() -> None:
    """Drop the cached overview — used by tests to avoid cross-test staleness."""
    global _overview_cache
    _overview_cache = None


async def _cached_overview(s: AsyncSession) -> dict:
    global _overview_cache
    if _OVERVIEW_TTL > 0 and _overview_cache is not None:
        ts, body = _overview_cache
        if time.monotonic() - ts < _OVERVIEW_TTL:
            return body
    async with _overview_lock:
        if _OVERVIEW_TTL > 0 and _overview_cache is not None:
            ts, body = _overview_cache
            if time.monotonic() - ts < _OVERVIEW_TTL:
                return body
        body = await admin_overview(s, now=datetime.now(UTC))
        _overview_cache = (time.monotonic(), body)
        return body


@router.get("/overview")
async def overview(s: AsyncSession = Depends(session)) -> dict:
    return await _cached_overview(s)


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
    stuck_age_hours: float
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
    now = utcnow()
    candidates = await _gc_candidates(s, threshold=now - timedelta(days=age_days))
    if dry_run:
        return {
            "dry_run": True,
            "age_days": age_days,
            "candidates": [_gc_candidate_dict(b, now=now) for b in candidates],
            "freed_bytes_estimate": sum(b.size for b in candidates),
        }
    summary = await _gc_apply(s, candidates)
    return {"dry_run": False, "age_days": age_days, **summary}


async def _gc_candidates(s: AsyncSession, *, threshold: datetime) -> list[Bundle]:
    """Bundles with no batch referencing them AND uploaded before `threshold`.
    Pure query — never mutates."""
    bundles = (await s.execute(select(Bundle))).scalars().all()
    counts_stmt = select(Batch.bundle_ref, func.count(Batch.batch_id)).group_by(Batch.bundle_ref)
    in_use = {ref: n for ref, n in (await s.execute(counts_stmt)).all()}
    return [
        b
        for b in bundles
        if in_use.get(format_bundle_ref(b.name, b.version), 0) == 0 and b.uploaded_at < threshold
    ]


def _gc_candidate_dict(b: Bundle, *, now: datetime) -> dict[str, Any]:
    return {
        "name": b.name,
        "version": b.version,
        "size": b.size,
        "sha256": b.sha256,
        "uploaded_at": b.uploaded_at.isoformat(),
        "age_days": (now - b.uploaded_at).days,
    }


async def _gc_apply(s: AsyncSession, candidates: list[Bundle]) -> dict[str, Any]:
    """Stage row deletes, find which blobs become orphaned post-delete, commit,
    then unlink. Order matters: unlinking before commit means a rollback would
    leave dangling DB rows referencing missing blobs.

    A sha shared by two rows where we delete one must keep the blob alive —
    that's why orphan detection runs AFTER `flush()` (so the post-delete row
    count reflects what'll exist after commit)."""
    deleted_meta: list[dict[str, Any]] = []
    freed = 0
    shas: set[str] = set()
    for b in candidates:
        deleted_meta.append({"name": b.name, "version": b.version, "size": b.size, "sha256": b.sha256})
        freed += b.size
        shas.add(b.sha256)
        await s.delete(b)
    await s.flush()

    orphan_shas = [
        sha
        for sha in shas
        if not await s.scalar(select(func.count()).select_from(Bundle).where(Bundle.sha256 == sha))
    ]

    if deleted_meta:
        await log(s, "bundles", f"GC deleted {len(deleted_meta)} bundle(s) ({freed} bytes)")
    await commit_and_publish(s, Scope.BUNDLES if deleted_meta else None)

    unlinked: list[str] = []
    for sha in orphan_shas:
        blob = settings.bundle_storage / f"{sha}.zip"
        if blob.is_file():
            blob.unlink()
            unlinked.append(sha)

    return {"deleted": deleted_meta, "freed_bytes": freed, "unlinked_blobs": len(unlinked)}


@router.post("/requeue-undeliverable")
async def requeue_undeliverable(
    batch_id: str | None = None,
    s: AsyncSession = Depends(session),
) -> dict:
    """Re-queue UPLOADED granules the receiver can no longer make progress on — i.e.
    with NO pullable object left: every object is exhausted (failed_pulls hit the cap)
    OR already acked/deleted while the granule never advanced past UPLOADED. Typically
    the hosting worker lost the output files on restart (presigned URLs 404). Each
    resets to PENDING for a full re-download/process/upload and its dead object rows
    are dropped. Scope with ?batch_id=, else sweeps every batch.

    A normally-delivering granule still has a pullable object, so it is never touched."""
    now = utcnow()
    stmt = (
        select(Granule)
        .where(Granule.state == GranuleState.UPLOADED.value)
        .where(
            ~select(GranuleObject.id)
            .where(GranuleObject.granule_id == Granule.granule_id)
            .where(object_is_pullable())
            .exists()
        )
    )
    if batch_id:
        stmt = stmt.where(Granule.batch_id == batch_id)
    granules = (await s.execute(stmt)).scalars().all()
    for g in granules:
        # Query pre-filters state==UPLOADED, so apply()'s guard is unreachable here.
        await apply_transition(s, g, RequeueGranule(granule_id=g.granule_id), now=now)
        await s.execute(delete(GranuleObject).where(GranuleObject.granule_id == g.granule_id))
        evict_granule(g.granule_id)
    if granules:
        await log(s, "admin", f"re-queued {len(granules)} undeliverable granule(s)")
    await commit_and_publish(s, Scope.BATCHES if granules else None)
    return {"requeued": len(granules)}


@router.post("/reset-pull-failures")
async def reset_pull_failures(
    batch_id: str | None = None,
    s: AsyncSession = Depends(session),
) -> dict:
    """Re-offer objects abandoned by pull-failure exhaustion WITHOUT redownloading.
    Zeroes failed_pulls on every still-pending object that hit the cap, so the
    receiver picks them up on the next pull. Use this — not requeue-undeliverable —
    when the worker still holds the bytes (presigned URL works) and the failures
    were collateral of a transient receiver-side fault, not a dead object. Scope
    with ?batch_id=, else sweeps every batch."""
    stmt = update(GranuleObject).where(object_is_exhausted()).values(failed_pulls=0)
    if batch_id:
        stmt = stmt.where(
            GranuleObject.granule_id.in_(select(Granule.granule_id).where(Granule.batch_id == batch_id))
        )
    n = getattr(await s.execute(stmt), "rowcount", 0) or 0
    if n:
        await log(s, "admin", f"reset pull-failure counter on {n} exhausted object(s)")
    await commit_and_publish(s, Scope.BATCHES if n else None)
    return {"reset": n}


def _git_repo_base() -> str:
    """The repo's web base, e.g. https://github.com/imutum/sathop (no .git)."""
    return os.environ.get("SATHOP_GIT_REPO", "https://github.com/imutum/sathop.git").removesuffix(".git")


def _bundle_asset_url(version: str) -> str:
    return f"{_git_repo_base()}/releases/download/v{version}/sathop-bundle.tar.gz"


def _github_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("SATHOP_GIT_TOKEN", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _fetch_latest_release() -> dict[str, str]:
    """Resolve the newest release tag from the GitHub API, falling back to the
    newest tag when no release is published. Server-side so the browser never
    hits api.github.com (anonymous 60/h-per-IP limit); an optional
    SATHOP_GIT_TOKEN lifts the rate limit to 5000/h."""
    base = _git_repo_base()
    repo_path = base.split("github.com/", 1)[-1]  # owner/repo
    releases_url = f"https://api.github.com/repos/{repo_path}/releases/latest"
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
        r = await c.get(releases_url, headers=_github_headers())
        if r.status_code == 200:
            j = r.json()
            return {"tag": j.get("tag_name") or "", "html_url": j.get("html_url") or f"{base}/releases"}
        if r.status_code != 404:
            r.raise_for_status()
        # No published release — fall back to the newest tag.
        rt = await c.get(
            f"https://api.github.com/repos/{repo_path}/tags?per_page=1", headers=_github_headers()
        )
        rt.raise_for_status()
        tags = rt.json()
        name = tags[0].get("name", "") if isinstance(tags, list) and tags else ""
        return {"tag": name, "html_url": f"{base}/releases/tag/{name}" if name else f"{base}/releases"}


_LATEST_TTL = 300.0
_latest_cache: dict[str, Any] = {"at": 0.0, "data": None}
_latest_lock = asyncio.Lock()


def reset_latest_cache() -> None:
    """Drop the cached latest-release — used by tests to avoid cross-test staleness."""
    _latest_cache["data"] = None


def _cached_latest() -> dict | None:
    data = _latest_cache["data"]
    if data is not None and time.time() - _latest_cache["at"] < _LATEST_TTL:
        return data
    return None


@router.get("/latest-version")
async def latest_version() -> dict:
    """What's the newest SatHop release? Proxied server-side (one IP, optional
    token, 5-min single-flight cache) so the browser never hits the rate-limited
    api.github.com directly. Returns {tag, html_url, current}; tag="" + error on
    failure (not cached, so a later success still populates).

    Double-checked locking (like _cached_overview): the cache-hit fast path never
    touches the lock, so a burst of UI tabs sharing one query key never queues
    behind it — and a slow/hanging GitHub stalls only true cache-miss callers."""
    cached = _cached_latest()
    if cached is not None:
        return {**cached, "current": __version__}
    async with _latest_lock:
        cached = _cached_latest()
        if cached is not None:
            return {**cached, "current": __version__}
        try:
            data = await _fetch_latest_release()
        except Exception as e:
            return {
                "tag": "",
                "html_url": f"{_git_repo_base()}/releases",
                "current": __version__,
                "error": str(e),
            }
        _latest_cache["data"] = data
        _latest_cache["at"] = time.time()
        return {**data, "current": __version__}


class UpgradeRequest(BaseModel):
    version: str


def _trigger_shutdown() -> None:
    """Close SSE streams, then SIGTERM self after a beat so the HTTP response
    flushes first. The entrypoint supervisor catches the clean exit (code 0)."""
    from ..pubsub import request_shutdown

    request_shutdown()
    asyncio.get_running_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))


@router.post("/upgrade")
async def upgrade_orchestrator(req: UpgradeRequest, s: AsyncSession = Depends(session)) -> dict:
    """Install a specific release on the next boot, then self-restart.

    Writes the target to `.pending-version`; the entrypoint consumes it once —
    downloading that version's self-contained bundle (backend + the matching
    prebuilt frontend, one package so they can't drift), extracting it, and
    relaunching. We HEAD the release asset first so a bad version fails here with
    a clear error instead of crash-looping the container after the restart."""
    try:
        version = normalize_version(req.version)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    url = _bundle_asset_url(version)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
            (await c.head(url)).raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"release v{version} not downloadable: {e}")

    write_pending_version(version)
    await log(s, "orchestrator", f"upgrade to v{version} requested via UI")
    await commit_and_publish(s, Scope.EVENTS)
    _trigger_shutdown()
    return {"ok": True, "version": version}


@router.post("/restart")
async def restart_orchestrator(s: AsyncSession = Depends(session)) -> dict:
    """Self-restart at the same version: signal SSE streams to close, log,
    respond, then SIGTERM self. The entrypoint supervisor catches the clean exit
    (code 0) and relaunches the installed version unchanged (no `.pending-version`,
    so it sticks). Closing streams first lets uvicorn's graceful shutdown finish
    in milliseconds instead of hanging on the long-lived /api/stream connection."""
    await log(s, "orchestrator", "restart requested via UI")
    await commit_and_publish(s, Scope.EVENTS)
    _trigger_shutdown()
    return {"ok": True}


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
