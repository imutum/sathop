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
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop import __version__
from sathop.shared.bundle_ref import format_bundle_ref
from sathop.shared.release import normalize_version, write_pending_version
from sathop.shared.state_machine import GranuleState, RequeueGranule, Scope

from ..config import require_token, settings
from ..db import Batch, Bundle, Granule, GranuleObject, is_postgres, session, utcnow
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


async def head_release_asset(version: str) -> None:
    """HEAD the release bundle so a bad version fails fast (502) here instead of
    crash-looping a container after the restart/upgrade. Shared by the orchestrator
    self-upgrade and the staged-rollout start."""
    url = _bundle_asset_url(version)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
            (await c.head(url)).raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"release v{version} not downloadable: {e}") from e


def _github_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("SATHOP_GIT_TOKEN", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _normalize_channel(channel: str) -> str:
    """Two release channels only: edge (newest, incl. prereleases) and stable
    (newest promoted release). Anything else collapses to stable."""
    return "edge" if channel == "edge" else "stable"


async def _fetch_latest_release(channel: str = "stable") -> dict[str, str]:
    """Resolve a release channel to its newest tag via the GitHub API, server-side
    so the browser never hits api.github.com (anonymous 60/h-per-IP limit; an
    optional SATHOP_GIT_TOKEN lifts it to 5000/h).

    stable → GitHub's newest *non-prerelease* release (/releases/latest), falling
    back to the newest tag when nothing is published. edge → the newest release
    *including* prereleases (the /releases list is newest-first), so an edge build
    is visible before it is promoted to stable."""
    base = _git_repo_base()
    repo_path = base.split("github.com/", 1)[-1]  # owner/repo
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
        if channel == "edge":
            r = await c.get(
                f"https://api.github.com/repos/{repo_path}/releases?per_page=1", headers=_github_headers()
            )
            r.raise_for_status()
            rels = r.json()
            j = rels[0] if isinstance(rels, list) and rels else {}
            return {"tag": j.get("tag_name") or "", "html_url": j.get("html_url") or f"{base}/releases"}
        r = await c.get(
            f"https://api.github.com/repos/{repo_path}/releases/latest", headers=_github_headers()
        )
        if r.status_code == 200:
            j = r.json()
            return {"tag": j.get("tag_name") or "", "html_url": j.get("html_url") or f"{base}/releases"}
        if r.status_code != 404:
            r.raise_for_status()
        # No published stable release — fall back to the newest tag.
        rt = await c.get(
            f"https://api.github.com/repos/{repo_path}/tags?per_page=1", headers=_github_headers()
        )
        rt.raise_for_status()
        tags = rt.json()
        name = tags[0].get("name", "") if isinstance(tags, list) and tags else ""
        return {"tag": name, "html_url": f"{base}/releases/tag/{name}" if name else f"{base}/releases"}


# Latest-release cache: at most ONE GitHub fetch per channel per clock-hour.
# Releases change rarely, so an hour-aligned bucket (not a rolling TTL) caps GitHub
# volume hard — ≤1 attempt/channel/hour even under constant UI traffic — which is
# what keeps us under api.github.com's anonymous 60/h-per-IP limit (the 403 storms).
_latest_cache: dict[str, dict] = {}  # channel -> {"bucket": int, "result": dict}
_latest_good: dict[str, dict] = {}  # channel -> last successful {tag, html_url}, kept indefinitely
_latest_lock = asyncio.Lock()


def _hour_bucket() -> int:
    """Index of the current clock-hour (UTC). Flips at HH:00:00, so the first request
    after the top of the hour refreshes and the rest of the hour is served cached."""
    return int(time.time() // 3600)


def reset_latest_cache() -> None:
    """Drop cached latest-release data — used by tests to avoid cross-test staleness."""
    _latest_cache.clear()
    _latest_good.clear()


def _cached_latest(channel: str, bucket: int) -> dict | None:
    entry = _latest_cache.get(channel)
    return entry["result"] if entry is not None and entry["bucket"] == bucket else None


@router.get("/latest-version")
async def latest_version(
    channel: str = Query(default=""),
    force: bool = Query(default=False),
) -> dict:
    """Newest SatHop release on a channel. Proxied server-side (one IP, optional
    SATHOP_GIT_TOKEN) so the browser never hits the rate-limited api.github.com
    directly (anonymous: 60/h-per-IP). `channel` defaults to SATHOP_CHANNEL (stable
    unless set to edge). Returns {tag, html_url, current, channel, [stale, error]}.

    Automatic (non-forced) requests query GitHub at most once per channel per
    clock-hour: the result lands in the current hour bucket and is served for the
    rest of the hour, so constant UI traffic — many tabs, frequent reloads, N worker
    processes — can't drive repeated fetches. A failed fetch is bucketed too: it
    serves the last-known-good value (stale=true) when one exists, else tag="" +
    error, and does NOT re-hit GitHub again that hour, so an outage can't trigger a
    retry storm. THIS hourly cap is the contract for automatic traffic only.

    `force=true` (the manual "检查更新" button) is the deliberate operator override:
    it always skips the bucket and re-hits GitHub immediately, then resets the cache
    to the fresh result — the escape hatch when they need an answer before the next
    hour boundary. Throttled by the UI (the button disables while a fetch is in
    flight), so it can't be spammed into a storm.

    Double-checked locking (like _cached_overview): the cache-hit fast path never
    touches the lock, so a burst of UI tabs sharing one query key never queues
    behind it — and a slow/hanging GitHub stalls only true cache-miss callers."""
    ch = _normalize_channel(channel or settings.channel)
    bucket = _hour_bucket()
    if not force:
        cached = _cached_latest(ch, bucket)
        if cached is not None:
            return {**cached, "current": __version__, "channel": ch}
    async with _latest_lock:
        if not force:
            cached = _cached_latest(ch, bucket)
            if cached is not None:
                return {**cached, "current": __version__, "channel": ch}
        good = _latest_good.get(ch)
        try:
            data = await _fetch_latest_release(ch)
        except Exception as e:
            # Bucket the failure so we don't re-hit GitHub until the next hour: serve
            # last-known-good (stale) if we have it, else a bare error.
            result = (
                {**good, "stale": True, "error": str(e)}
                if good is not None
                else {"tag": "", "html_url": f"{_git_repo_base()}/releases", "error": str(e)}
            )
            _latest_cache[ch] = {"bucket": bucket, "result": result}
            return {**result, "current": __version__, "channel": ch}
        _latest_good[ch] = data
        _latest_cache[ch] = {"bucket": bucket, "result": data}
        return {**data, "current": __version__, "channel": ch}


class UpgradeRequest(BaseModel):
    version: str


def _shutdown_target_pid() -> int:
    """PID to SIGTERM so the entrypoint supervisor relaunches the container.

    Single-process: the uvicorn server IS the bash supervisor's `$CHILD`, so signal
    self → it exits 0 → supervisor loops and consumes any `.pending-version`.

    Multi-process (uvicorn workers=N, active only when orch_workers>1 AND Postgres —
    mirroring main.run()'s own guard): the request runs inside a *worker*, whose
    parent is the uvicorn master (the process bash waits on). SIGTERM-ing self would
    only kill the worker — the master respawns it and the container never restarts.
    Signal the master (our parent) instead, so it stops all workers and exits 0.
    Guard: if the parent is already PID 1 (master gone, reparented to tini), fall
    back to self — never SIGTERM the bash supervisor, which would STOP not restart."""
    if not (settings.orch_workers > 1 and is_postgres()):
        return os.getpid()
    ppid = os.getppid()
    return ppid if ppid > 1 else os.getpid()


def _trigger_shutdown() -> None:
    """Close SSE streams, then SIGTERM the right process after a beat so the HTTP
    response flushes first. The entrypoint supervisor catches the clean exit (0)."""
    from ..pubsub import request_shutdown

    request_shutdown()
    target = _shutdown_target_pid()  # capture eagerly: getppid() may shift after the delay

    def _kill() -> None:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            pass  # already exiting (e.g. another worker signalled the master) — fine

    asyncio.get_running_loop().call_later(0.5, _kill)


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

    await head_release_asset(version)

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
