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
from ..pubsub import log_event as log
from ..pubsub import publish

router = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_token)])

LEASE_DURATION = timedelta(minutes=30)

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


@router.post("/register", response_model=WorkerRegisterResponse)
async def register(req: WorkerRegister, s: AsyncSession = Depends(session)) -> WorkerRegisterResponse:
    w = await s.get(Worker, req.worker_id)
    if w is None:
        w = Worker(
            worker_id=req.worker_id, version=req.version, capacity=req.capacity, public_url=req.public_url
        )
        s.add(w)
        await log(s, req.worker_id, f"worker registered (cap={req.capacity})")
    else:
        w.version = req.version
        w.capacity = req.capacity
        w.public_url = req.public_url
        w.last_seen = utcnow()
    await s.commit()
    publish({"scope": "workers"})
    return WorkerRegisterResponse()


@router.post("/heartbeat", response_model=WorkerHeartbeatResponse)
async def heartbeat(req: WorkerHeartbeat, s: AsyncSession = Depends(session)) -> WorkerHeartbeatResponse:
    w = await s.get(Worker, req.worker_id)
    if w is None:
        raise HTTPException(404, "worker not registered")
    w.last_seen = utcnow()
    w.disk_used_gb = req.disk_used_gb
    w.disk_total_gb = req.disk_total_gb
    w.cpu_percent = req.cpu_percent
    w.mem_percent = req.mem_percent
    w.monthly_egress_gb = req.monthly_egress_gb
    w.queue_queued = req.queue_queued
    w.queue_downloading = req.queue_downloading
    w.queue_processing = req.queue_processing
    w.queue_uploading = req.queue_uploading
    w.paused = req.paused
    await s.commit()
    publish({"scope": "workers"})
    return WorkerHeartbeatResponse(desired_capacity=w.desired_capacity)


@router.post("/lease", response_model=LeaseResponse)
async def lease(req: LeaseRequest, s: AsyncSession = Depends(session)) -> LeaseResponse:
    async with _LEASE_LOCK:
        return await _lease_locked(req, s)


async def _lease_locked(req: LeaseRequest, s: AsyncSession) -> LeaseResponse:
    w = await s.get(Worker, req.worker_id)
    if w is None or not w.enabled:
        raise HTTPException(403, "worker not registered or disabled")

    now = utcnow()
    expires = now + LEASE_DURATION

    # Two clamps below req.capacity: queue-based backpressure (0 disables) and
    # per-worker runtime override (belt-and-braces against an old worker that
    # doesn't self-clamp).
    limit = await _lease_limit(s, w, req)
    if limit <= 0:
        return LeaseResponse(items=[], lease_expires_at=expires)

    stmt = (
        select(Granule)
        .where(Granule.state == GranuleState.PENDING.value)
        .where((Granule.leased_by.is_(None)) | (Granule.lease_expires_at < now))
        .limit(limit)
    )
    rows = (await s.execute(stmt)).scalars().all()

    items: list[LeaseItem] = []
    for g in rows:
        # State starts at QUEUED — the worker promotes to DOWNLOADING once it
        # actually acquires the download semaphore. Keeps the UI honest about
        # what's actively transferring vs. queued behind concurrency limits.
        g.state = GranuleState.QUEUED.value
        g.leased_by = req.worker_id
        g.lease_expires_at = expires
        g.updated_at = now
        batch = await s.get(Batch, g.batch_id)
        items.append(_lease_item(g, batch))

    if items:
        await log(s, req.worker_id, f"leased {len(items)} granules")
    await s.commit()
    if items:
        publish({"scope": "batches"})
    return LeaseResponse(items=items, lease_expires_at=expires)


# Forward-only transitions reported by a leased worker. lease() writes QUEUED
# and upload() writes UPLOADED, so neither appears here.
_STATE_PREDECESSOR = {
    GranuleState.DOWNLOADING.value: GranuleState.QUEUED.value,
    GranuleState.DOWNLOADED.value: GranuleState.DOWNLOADING.value,
    GranuleState.PROCESSING.value: GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSED.value: GranuleState.PROCESSING.value,
}

# Map "transition that closes the stage" → stage name. Idle DOWNLOADED→PROCESSING
# isn't recorded (worker calls bundle.ensure() back-to-back; near-zero).
_STAGE_BY_CLOSER = {
    GranuleState.DOWNLOADED.value: "download",
    GranuleState.PROCESSED.value: "process",
    GranuleState.UPLOADED.value: "upload",
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
    g = await s.get(Granule, req.granule_id)
    if g is None:
        raise HTTPException(404, "granule not found")
    if g.leased_by != req.worker_id:
        raise HTTPException(409, "granule not leased by this worker")
    if g.state != expected:
        raise HTTPException(409, f"cannot transition {g.state!r} → {req.state.value!r}")
    prev_at = g.updated_at
    now = utcnow()
    g.state = req.state.value
    g.updated_at = now
    stage = _STAGE_BY_CLOSER.get(req.state.value)
    if stage is not None:
        _record_stage(s, g, stage, prev_at, now)
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True, "state": g.state}


@router.post("/upload")
async def upload(req: UploadReport, s: AsyncSession = Depends(session)) -> dict:
    g = await s.get(Granule, req.granule_id)
    if g is None:
        raise HTTPException(404, "granule not found")
    if g.leased_by != req.worker_id:
        raise HTTPException(409, "granule not leased by this worker")

    for o in req.objects:
        s.add(
            GranuleObject(
                granule_id=g.granule_id,
                worker_id=req.worker_id,
                object_key=o.object_key,
                presigned_url=o.presigned_url,
                sha256=o.sha256,
                size=o.size,
            )
        )
    prev_at = g.updated_at
    now = utcnow()
    g.state = GranuleState.UPLOADED.value
    g.leased_by = None
    g.lease_expires_at = None
    g.error = None
    g.updated_at = now
    _record_stage(s, g, "upload", prev_at, now)
    await log(s, req.worker_id, f"uploaded {len(req.objects)} objects", granule_id=g.granule_id)
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True}


@router.post("/failure")
async def failure(req: ProcessFailure, s: AsyncSession = Depends(session)) -> dict:
    g = await s.get(Granule, req.granule_id)
    if g is None:
        raise HTTPException(404, "granule not found")
    if g.leased_by != req.worker_id:
        raise HTTPException(409, "granule not leased by this worker")

    g.retry_count += 1
    g.error = req.error[:2000]
    g.leased_by = None
    g.lease_expires_at = None
    g.state = (
        GranuleState.BLACKLISTED.value
        if g.retry_count >= settings.max_retries
        else GranuleState.PENDING.value
    )
    g.updated_at = utcnow()
    await log(
        s,
        req.worker_id,
        f"processing failed (exit={req.exit_code}) retry={g.retry_count}",
        level="error" if g.state == GranuleState.BLACKLISTED.value else "warn",
        granule_id=g.granule_id,
    )
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True, "state": g.state}


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
    w = await s.get(Worker, worker_id)
    if w is None:
        raise HTTPException(404, "worker not found")
    w.desired_capacity = desired_capacity
    await log(s, worker_id, f"capacity override → {desired_capacity} (env cap {w.capacity})")
    await s.commit()
    publish({"scope": "workers"})
    return {"ok": True, "desired_capacity": desired_capacity}


@router.put("/{worker_id}/enabled")
async def set_enabled(
    worker_id: str,
    enabled: bool = Body(embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    """Runtime kill-switch. Disabled workers receive 403 on next lease call,
    so in-flight work drains naturally before the worker goes idle."""
    w = await s.get(Worker, worker_id)
    if w is None:
        raise HTTPException(404, "worker not found")
    w.enabled = enabled
    await log(s, worker_id, f"worker {'enabled' if enabled else 'disabled'}")
    await s.commit()
    publish({"scope": "workers"})
    return {"ok": True, "enabled": enabled}


@router.delete("/{worker_id}")
async def forget_worker(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Permanently remove a decommissioned worker row. Refuses if the worker is
    still enabled or still holding any granule storage — operator must disable
    and let it drain first."""
    w = await s.get(Worker, worker_id)
    if w is None:
        raise HTTPException(404, "worker not found")
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
    await s.commit()
    publish({"scope": "workers"})
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
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True}
