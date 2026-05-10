"""Worker-facing endpoints: register, heartbeat, lease, upload, delete-confirm."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    LEASED_STATES,
    Credential,
    DeletableGranule,
    GranuleState,
    LeaseItem,
    LeaseRequest,
    LeaseResponse,
    ProcessFailure,
    StateUpdate,
    UploadReport,
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegister,
    WorkerRegisterResponse,
)

from ..config import require_token, settings
from ..db import Batch, Granule, GranuleObject, GranuleStageTiming, Worker, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log

router = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_token)])

LEASE_DURATION = timedelta(minutes=30)


async def _worker_or_404(s: AsyncSession, worker_id: str, detail: str = "worker not found") -> Worker:
    worker = await s.get(Worker, worker_id)
    if worker is None:
        raise HTTPException(404, detail)
    return worker


async def _enabled_worker_or_403(s: AsyncSession, worker_id: str) -> Worker:
    worker = await s.get(Worker, worker_id)
    if worker is None or not worker.enabled:
        raise HTTPException(403, "worker not registered or disabled")
    return worker


async def _leased_granule_or_409(s: AsyncSession, granule_id: str, worker_id: str) -> Granule:
    granule = await s.get(Granule, granule_id)
    if granule is None:
        raise HTTPException(404, "granule not found")
    if granule.leased_by != worker_id:
        raise HTTPException(409, "granule not leased by this worker")
    return granule


# Serialize lease claims process-wide so two concurrent /lease calls can't
# both observe the same PENDING rows and overwrite each other's UPDATE. The
# SELECT-then-UPDATE pattern in lease() is racy without this — SQLAlchemy's
# attribute-based UPDATE issues a primary-key-only WHERE clause, so the
# second writer wins blindly and the first worker ends up with a phantom
# lease (its later report_state 409s, downloaded bytes wasted). SQLite
# already serializes writers at commit time, so the perf cost is negligible.
_LEASE_LOCK = asyncio.Lock()


async def _count_inflight(s: AsyncSession, worker_id: str) -> int:
    """How many granules is this worker currently holding storage for?
    Pre-upload: input files staged under work_root. Post-upload: output
    objects in LocalStorage/MinIO, until the receiver acks + delete-confirmed."""
    pre = await s.scalar(
        select(func.count())
        .select_from(Granule)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
    )
    post = await s.scalar(
        select(func.count(distinct(GranuleObject.granule_id)))
        .where(GranuleObject.worker_id == worker_id)
        .where(GranuleObject.deleted_at.is_(None))
    )
    return int(pre or 0) + int(post or 0)


async def _lease_limit(s: AsyncSession, worker: Worker, req: LeaseRequest) -> int:
    """Effective lease size after orchestrator backpressure and runtime override."""
    limit = req.capacity
    if settings.max_inflight_per_worker > 0:
        holding = await _count_inflight(s, req.worker_id)
        limit = min(limit, max(0, settings.max_inflight_per_worker - holding))
    if worker.desired_capacity is not None:
        limit = min(limit, max(0, worker.desired_capacity))
    return limit


def _json_dict_or_empty(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _credential_map(raw: str | None) -> dict[str, Credential]:
    try:
        return {k: Credential.model_validate(v) for k, v in _json_dict_or_empty(raw).items()}
    except ValueError:
        return {}


def _lease_item(granule: Granule, batch: Batch | None) -> LeaseItem:
    return LeaseItem(
        granule_id=granule.granule_id,
        batch_id=granule.batch_id,
        bundle_ref=batch.bundle_ref if batch else "",
        inputs=json.loads(granule.inputs_json),
        meta=json.loads(granule.meta_json or "{}"),
        execution_env=_json_dict_or_empty(batch.execution_env_json if batch else None),
        credentials=_credential_map(batch.credentials_json if batch else None),
    )


async def _held_granule_sample(s: AsyncSession, worker_id: str, limit: int = 5) -> list[str]:
    leased = (
        (
            await s.execute(
                select(Granule.granule_id)
                .where(Granule.leased_by == worker_id)
                .where(Granule.state.in_(LEASED_STATES))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    uploaded = (
        (
            await s.execute(
                select(distinct(GranuleObject.granule_id))
                .where(GranuleObject.worker_id == worker_id)
                .where(GranuleObject.deleted_at.is_(None))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list({*leased, *uploaded})[:limit]


async def _record_worker_version(s: AsyncSession, worker: Worker, req: WorkerHeartbeat) -> None:
    """Update the heartbeat version and log only when a real value changes."""
    if not req.version or req.version == worker.version:
        return
    await log(
        s,
        req.worker_id,
        f"worker version changed {worker.version!r} → {req.version!r} "
        "(if this keeps flipping, two containers likely share the worker_id)",
        level="warn",
    )
    worker.version = req.version


def _apply_worker_heartbeat(worker: Worker, req: WorkerHeartbeat, now) -> None:
    worker.last_seen = now
    worker.disk_used_gb = req.disk_used_gb
    worker.disk_total_gb = req.disk_total_gb
    worker.cpu_percent = req.cpu_percent
    worker.mem_percent = req.mem_percent
    worker.monthly_egress_gb = req.monthly_egress_gb
    worker.queue_pending_download = req.queue_pending_download
    worker.queue_downloading = req.queue_downloading
    worker.queue_pending_processing = req.queue_pending_processing
    worker.queue_processing = req.queue_processing
    worker.queue_pending_upload = req.queue_pending_upload
    worker.queue_uploading = req.queue_uploading
    worker.paused = req.paused


async def _renew_worker_leases(s: AsyncSession, worker_id: str, now) -> None:
    await s.execute(
        update(Granule)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
        .where(Granule.lease_expires_at < now + LEASE_DURATION / 2)
        .values(lease_expires_at=now + LEASE_DURATION)
    )


async def _revoked_active_granules(s: AsyncSession, req: WorkerHeartbeat) -> list[str]:
    if not req.active_granule_ids:
        return []
    still_owned = (
        (
            await s.execute(
                select(Granule.granule_id)
                .where(Granule.granule_id.in_(req.active_granule_ids))
                .where(Granule.leased_by == req.worker_id)
                .where(Granule.state.in_(LEASED_STATES))
            )
        )
        .scalars()
        .all()
    )
    owned_set = set(still_owned)
    return [gid for gid in req.active_granule_ids if gid not in owned_set]


async def _consume_restart_signal(s: AsyncSession, worker: Worker) -> bool:
    requested = worker.restart_requested_at is not None
    if requested:
        worker.restart_requested_at = None
        await log(s, worker.worker_id, "restart signal delivered to worker")
    return requested


async def _consume_gc_signal(s: AsyncSession, worker: Worker) -> bool:
    requested = worker.gc_requested_at is not None
    if requested:
        worker.gc_requested_at = None
        await log(s, worker.worker_id, "cache GC signal delivered to worker")
    return requested


@router.post("/register", response_model=WorkerRegisterResponse)
async def register(req: WorkerRegister, s: AsyncSession = Depends(session)) -> WorkerRegisterResponse:
    w = await s.get(Worker, req.worker_id)
    if w is None:
        w = Worker(
            worker_id=req.worker_id,
            version=req.version,
            capacity=req.capacity,
            public_url=req.public_url,
            ca_pem=req.ca_pem,
        )
        s.add(w)
        await log(s, req.worker_id, f"worker registered (cap={req.capacity})")
    else:
        w.version = req.version
        w.capacity = req.capacity
        w.public_url = req.public_url
        # Update CA only when the worker provides one — preserves a previously
        # registered CA across restarts without it (e.g. user temporarily ran
        # the worker without the caddy_data mount).
        if req.ca_pem is not None:
            w.ca_pem = req.ca_pem
        w.last_seen = utcnow()
    await commit_and_publish(s, "workers")
    return WorkerRegisterResponse()


@router.post("/heartbeat", response_model=WorkerHeartbeatResponse)
async def heartbeat(req: WorkerHeartbeat, s: AsyncSession = Depends(session)) -> WorkerHeartbeatResponse:
    w = await _worker_or_404(s, req.worker_id, "worker not registered")
    now = utcnow()
    await _record_worker_version(s, w, req)
    _apply_worker_heartbeat(w, req, now)
    await _renew_worker_leases(s, req.worker_id, now)

    # Diff worker's active set vs. DB; any mismatch becomes a cancellation
    # instruction in this heartbeat response.
    revoked = await _revoked_active_granules(s, req)

    restart_requested = await _consume_restart_signal(s, w)
    gc_requested = await _consume_gc_signal(s, w)

    await commit_and_publish(s, "workers")
    return WorkerHeartbeatResponse(
        desired_capacity=w.desired_capacity,
        revoked_granule_ids=revoked,
        restart_requested=restart_requested,
        pause_requested=bool(w.pause_requested),
        gc_requested=gc_requested,
    )


@router.post("/lease", response_model=LeaseResponse)
async def lease(req: LeaseRequest, s: AsyncSession = Depends(session)) -> LeaseResponse:
    async with _LEASE_LOCK:
        return await _lease_locked(req, s)


async def _lease_locked(req: LeaseRequest, s: AsyncSession) -> LeaseResponse:
    worker = await _enabled_worker_or_403(s, req.worker_id)
    now = utcnow()
    expires = now + LEASE_DURATION

    # Two clamps below req.capacity: queue-based backpressure (0 disables) and
    # per-worker runtime override (belt-and-braces against an old worker that
    # doesn't self-clamp).
    limit = await _lease_limit(s, worker, req)
    if limit <= 0:
        return LeaseResponse(items=[], lease_expires_at=expires)

    items = await _claim_pending_granules(s, req.worker_id, limit, now, expires)
    if items:
        await log(s, req.worker_id, f"leased {len(items)} granules")
        await commit_and_publish(s, "batches")
    else:
        await commit_and_publish(s)
    return LeaseResponse(items=items, lease_expires_at=expires)


async def _claim_pending_granules(
    s: AsyncSession,
    worker_id: str,
    limit: int,
    now,
    expires,
) -> list[LeaseItem]:
    stmt = (
        select(Granule)
        .where(Granule.state == GranuleState.PENDING.value)
        .where((Granule.leased_by.is_(None)) | (Granule.lease_expires_at < now))
        .limit(limit)
    )
    rows = (await s.execute(stmt)).scalars().all()

    items: list[LeaseItem] = []
    for granule in rows:
        granule.state = GranuleState.QUEUED.value
        granule.leased_by = worker_id
        granule.lease_expires_at = expires
        granule.updated_at = now
        batch = await s.get(Batch, granule.batch_id)
        items.append(_lease_item(granule, batch))
    return items


# Forward-only transitions reported by a leased worker. lease() writes QUEUED
# and upload() writes UPLOADED, so neither appears here.
_STATE_PREDECESSOR = {
    GranuleState.DOWNLOADING.value: GranuleState.QUEUED.value,
    GranuleState.DOWNLOADED.value: GranuleState.DOWNLOADING.value,
    GranuleState.PROCESSING.value: GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSED.value: GranuleState.PROCESSING.value,
}

# Map "transition that closes the stage" → stage name. Each phase is recorded
# separately so the operator can tell sem-queue waits from real work:
#   QUEUED   → DOWNLOADING   download_wait  (pending_download sem queue)
#   DOWNLOADING → DOWNLOADED download       (actual byte transfer)
#   DOWNLOADED  → PROCESSING process_wait   (process_sem queue + bundle.ensure)
#   PROCESSING  → PROCESSED  process        (bundle subprocess wall time)
#   PROCESSED   → UPLOADED   upload         (split into upload_wait + upload by
#                                            the upload handler if the worker
#                                            sent upload_started_at)
_STAGE_BY_CLOSER = {
    GranuleState.DOWNLOADING.value: "download_wait",
    GranuleState.DOWNLOADED.value: "download",
    GranuleState.PROCESSING.value: "process_wait",
    GranuleState.PROCESSED.value: "process",
}


def _record_stage(s: AsyncSession, g: Granule, stage: str, started_at, finished_at) -> None:
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    s.add(
        GranuleStageTiming(
            granule_id=g.granule_id,
            batch_id=g.batch_id,
            stage=stage,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
    )


@router.post("/state")
async def report_state(req: StateUpdate, s: AsyncSession = Depends(session)) -> dict:
    expected = _STATE_PREDECESSOR.get(req.state.value)
    if expected is None:
        raise HTTPException(422, f"state {req.state.value!r} is not worker-reportable")
    g = await _leased_granule_or_409(s, req.granule_id, req.worker_id)
    if g.state != expected:
        raise HTTPException(409, f"cannot transition {g.state!r} → {req.state.value!r}")
    prev_at = g.updated_at
    now = utcnow()
    g.state = req.state.value
    g.updated_at = now
    stage = _STAGE_BY_CLOSER.get(req.state.value)
    if stage is not None:
        _record_stage(s, g, stage, prev_at, now)
    await commit_and_publish(s, "batches")
    return {"ok": True, "state": g.state}


@router.post("/upload")
async def upload(req: UploadReport, s: AsyncSession = Depends(session)) -> dict:
    g = await _leased_granule_or_409(s, req.granule_id, req.worker_id)
    # Worker must have already reported PROCESSED before uploading. A worker
    # that skipped PROCESSED would muddle the upload-stage timing (it would
    # absorb the entire process phase) and is a sign the worker code is out
    # of sync with the protocol. 409 surfaces the contract clearly.
    if g.state != GranuleState.PROCESSED.value:
        raise HTTPException(409, f"upload requires state=processed; granule is in state {g.state!r}")

    _mark_uploaded(s, g, req)
    await log(s, req.worker_id, f"uploaded {len(req.objects)} objects", granule_id=g.granule_id)
    await commit_and_publish(s, "batches")
    return {"ok": True}


def _mark_uploaded(s: AsyncSession, granule: Granule, req: UploadReport) -> None:
    for obj in req.objects:
        s.add(
            GranuleObject(
                granule_id=granule.granule_id,
                worker_id=req.worker_id,
                object_key=obj.object_key,
                presigned_url=obj.presigned_url,
                sha256=obj.sha256,
                size=obj.size,
            )
        )
    prev_at = granule.updated_at
    now = utcnow()
    granule.state = GranuleState.UPLOADED.value
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.error = None
    granule.stdout_tail = None
    granule.stderr_tail = None
    granule.updated_at = now
    started = req.upload_started_at
    if started is not None and prev_at <= started <= now:
        _record_stage(s, granule, "upload_wait", prev_at, started)
        _record_stage(s, granule, "upload", started, now)
    else:
        _record_stage(s, granule, "upload", prev_at, now)


@router.post("/failure")
async def failure(req: ProcessFailure, s: AsyncSession = Depends(session)) -> dict:
    g = await _leased_granule_or_409(s, req.granule_id, req.worker_id)
    # The failure path can only fire while the worker still genuinely owns
    # the granule. Anything outside the leased states means cancel/sweeper
    # got there first; the worker should swallow the 409 and stop reporting.
    if g.state not in LEASED_STATES:
        raise HTTPException(409, f"failure not accepted in state {g.state!r} (lease was revoked)")

    _mark_failed(g, req)
    await log(
        s,
        req.worker_id,
        f"processing failed (exit={req.exit_code}) retry={g.retry_count}",
        level="error" if g.state == GranuleState.BLACKLISTED.value else "warn",
        granule_id=g.granule_id,
    )
    await commit_and_publish(s, "batches")
    return {"ok": True, "state": g.state}


def _mark_failed(granule: Granule, req: ProcessFailure) -> None:
    granule.retry_count += 1
    granule.error = req.error[:2000]
    if req.stdout_tail is not None:
        granule.stdout_tail = req.stdout_tail[:16000]
    if req.stderr_tail is not None:
        granule.stderr_tail = req.stderr_tail[:16000]
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.state = (
        GranuleState.BLACKLISTED.value
        if granule.retry_count >= settings.max_retries
        else GranuleState.PENDING.value
    )
    granule.updated_at = utcnow()


@router.get("/deletable/{worker_id}")
async def deletable(worker_id: str, s: AsyncSession = Depends(session)) -> list[DeletableGranule]:
    """Worker polls for granules whose all objects are acked — safe to delete source."""
    stmt = (
        select(GranuleObject)
        .where(GranuleObject.worker_id == worker_id)
        .where(GranuleObject.acked_at.is_not(None))
        .where(GranuleObject.deleted_at.is_(None))
    )
    rows = (await s.execute(stmt)).scalars().all()

    by_granule: dict[str, list[str]] = {}
    for o in rows:
        by_granule.setdefault(o.granule_id, []).append(o.object_key)

    out: list[DeletableGranule] = []
    for gid, keys in by_granule.items():
        total = (
            (await s.execute(select(GranuleObject).where(GranuleObject.granule_id == gid))).scalars().all()
        )
        if all(o.acked_at is not None for o in total):
            out.append(DeletableGranule(granule_id=gid, object_keys=keys))
    return out


@router.put("/{worker_id}/capacity")
async def set_capacity(
    worker_id: str,
    desired_capacity: int | None = Body(default=None, embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    """Runtime concurrency override. None clears it (back to env capacity).
    Positive int clamps lease size + propagates to worker via heartbeat reply."""
    if desired_capacity is not None and desired_capacity < 1:
        raise HTTPException(422, "desired_capacity must be a positive int or null")
    w = await _worker_or_404(s, worker_id)
    w.desired_capacity = desired_capacity
    await log(s, worker_id, f"capacity override → {desired_capacity} (env cap {w.capacity})")
    await commit_and_publish(s, "workers")
    return {"ok": True, "desired_capacity": desired_capacity}


@router.post("/{worker_id}/restart")
async def request_restart(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Operator-triggered restart. Sets a one-shot flag the worker picks up on
    its next heartbeat and exits 0 on. Idempotent — re-clicks while a previous
    request hasn't been consumed just refresh the timestamp."""
    w = await _worker_or_404(s, worker_id)
    w.restart_requested_at = utcnow()
    await log(s, worker_id, "restart requested via UI")
    await commit_and_publish(s, "workers")
    return {"ok": True}


@router.put("/{worker_id}/enabled")
async def set_enabled(
    worker_id: str,
    enabled: bool = Body(embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    """Runtime kill-switch. Disabled workers receive 403 on next lease call,
    so in-flight work drains naturally before the worker goes idle."""
    w = await _worker_or_404(s, worker_id)
    w.enabled = enabled
    await log(s, worker_id, f"worker {'enabled' if enabled else 'disabled'}")
    await commit_and_publish(s, "workers")
    return {"ok": True, "enabled": enabled}


@router.put("/{worker_id}/pause")
async def set_paused(
    worker_id: str,
    paused: bool = Body(embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    """Operator-set persistent pause. Distinct from `enabled=false`:
      - paused: keep the worker registered + drain in-flight; resume any time
      - disabled: prelude to forgetting the row entirely
    Heartbeat reply propagates the flag; worker stops new leases until cleared."""
    w = await _worker_or_404(s, worker_id)
    w.pause_requested = paused
    await log(s, worker_id, f"worker {'paused' if paused else 'resumed'} via UI")
    await commit_and_publish(s, "workers")
    return {"ok": True, "pause_requested": paused}


@router.post("/{worker_id}/revoke-all")
async def revoke_all_leases(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Force-release every granule this worker holds back to PENDING — no
    waiting for the 30-min lease expiry. The next heartbeat returns these IDs
    via `revoked_granule_ids` so the worker cancels its asyncio handlers, but
    other workers can already lease them on the very next /lease call. Use
    when a worker is wedged but still heartbeating (otherwise the sweeper
    would already have caught it).

    In-flight progress on these granules is discarded; retry_count bumps so
    the orchestrator's max_retries cap still applies."""
    await _worker_or_404(s, worker_id)
    revoked = await _revoke_worker_leases(s, worker_id, utcnow())
    if revoked:
        await log(s, worker_id, f"force-revoked {revoked} lease(s) via UI")
        await commit_and_publish(s, "batches", "workers")
    else:
        await commit_and_publish(s, "workers")
    return {"ok": True, "revoked": revoked}


async def _revoke_worker_leases(s: AsyncSession, worker_id: str, now) -> int:
    rows = (
        (
            await s.execute(
                select(Granule).where(Granule.leased_by == worker_id).where(Granule.state.in_(LEASED_STATES))
            )
        )
        .scalars()
        .all()
    )
    for granule in rows:
        granule.state = GranuleState.PENDING.value
        granule.leased_by = None
        granule.lease_expires_at = None
        granule.retry_count = (granule.retry_count or 0) + 1
        granule.updated_at = now
    return len(rows)


@router.post("/{worker_id}/gc")
async def request_gc(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Operator-triggered remote GC. Same one-shot pattern as restart: orch
    sets a timestamp, next heartbeat reply forwards it, worker runs prune_caches
    out-of-band of its periodic loop."""
    w = await _worker_or_404(s, worker_id)
    w.gc_requested_at = utcnow()
    await log(s, worker_id, "cache GC requested via UI")
    await commit_and_publish(s, "workers")
    return {"ok": True}


@router.delete("/{worker_id}")
async def forget_worker(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Permanently remove a decommissioned worker row. Refuses if the worker is
    still enabled or still holding any granule storage — operator must disable
    and let it drain first."""
    w = await _worker_or_404(s, worker_id)
    if w.enabled:
        raise HTTPException(409, "worker is still enabled — disable it first")
    inflight = await _count_inflight(s, worker_id)
    if inflight > 0:
        sample = await _held_granule_sample(s, worker_id)
        more = f" (+{inflight - len(sample)} more)" if inflight > len(sample) else ""
        raise HTTPException(
            409,
            f"worker still holds {inflight} granule(s): {', '.join(sample)}{more}; wait for drain",
        )
    await s.delete(w)
    await log(s, worker_id, "worker forgotten (row deleted)")
    await commit_and_publish(s, "workers")
    return {"ok": True}


@router.post("/delete-confirmed")
async def delete_confirmed(req: DeletableGranule, s: AsyncSession = Depends(session)) -> dict:
    now = utcnow()
    await s.execute(
        update(GranuleObject).where(GranuleObject.granule_id == req.granule_id).values(deleted_at=now)
    )
    g = await s.get(Granule, req.granule_id)
    if g is not None:
        g.state = GranuleState.DELETED.value
        g.updated_at = now
    await commit_and_publish(s, "batches")
    return {"ok": True}
