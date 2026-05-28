"""Worker-facing endpoints: register, heartbeat, lease, events, delete-poll."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    DeletableGranule,
    LeaseRequest,
    LeaseResponse,
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegister,
    WorkerRegisterResponse,
)
from sathop.shared.state_machine import (
    DeleteConfirmed,
    GranuleEvent,
    GranuleState,
    ProcessingFailed,
    Scope,
    UploadCompleted,
)
from sathop.shared.versioning import parse_version

from .. import telemetry
from ..config import require_token, settings
from ..db import Granule, GranuleObject, Worker, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from ._helpers import get_or_404
from ._transition import apply_transition
from .one_shot import consume_one_shot_signal, record_version_flap, signal_one_shot
from .progress import evict_granule
from .worker_heartbeat import (
    apply_worker_heartbeat,
    revoked_active_granules,
)
from .worker_leases import (
    LEASE_DURATION,
    claim_pending_granules,
    lease_limit,
    renew_worker_leases,
    revoke_worker_leases,
)

router = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_token)])


def _check_worker_version(version: str, worker_id: str) -> None:
    min_ver = settings.min_worker_version
    if not min_ver:
        return
    if parse_version(version) < parse_version(min_ver):
        raise HTTPException(
            426,
            f"worker {worker_id} 版本 {version} 低于最低要求 {min_ver}，请升级后重试。\n"
            f"升级命令：\n"
            f"  Docker:  docker compose pull && docker compose up -d\n"
            f"  pip/uv:  uv pip install --upgrade 'sathop[worker]'",
        )


async def _active_worker_or_403(s: AsyncSession, worker_id: str) -> Worker:
    worker = await s.get(Worker, worker_id)
    if worker is None or worker.removed_at is not None:
        raise HTTPException(403, "worker not registered or removed")
    if worker.operator_paused:
        raise HTTPException(403, "worker is paused")
    return worker


# Serialize lease claims process-wide so two concurrent /lease calls can't
# both observe the same PENDING rows and overwrite each other's UPDATE. The
# SELECT-then-UPDATE pattern in lease() is racy without this — SQLAlchemy's
# attribute-based UPDATE issues a primary-key-only WHERE clause, so the
# second writer wins blindly and the first worker ends up with a phantom
# lease (its later /events emit 409s, downloaded bytes wasted). SQLite
# already serializes writers at commit time, so the perf cost is negligible.
_LEASE_LOCK = asyncio.Lock()


@router.post("/register", response_model=WorkerRegisterResponse)
async def register(req: WorkerRegister, s: AsyncSession = Depends(session)) -> WorkerRegisterResponse:
    _check_worker_version(req.version, req.worker_id)
    w = await s.get(Worker, req.worker_id)
    if w is not None and w.removed_at is not None:
        raise HTTPException(410, "worker has been removed — start a new worker with a different ID")
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
        if req.ca_pem is not None:
            w.ca_pem = req.ca_pem
        w.last_seen = utcnow()
    await commit_and_publish(s, Scope.WORKERS)
    return WorkerRegisterResponse()


@router.post("/heartbeat", response_model=WorkerHeartbeatResponse)
async def heartbeat(req: WorkerHeartbeat, s: AsyncSession = Depends(session)) -> WorkerHeartbeatResponse:
    _check_worker_version(req.version, req.worker_id)
    w = await get_or_404(s, Worker, req.worker_id, "worker not registered")

    if w.removed_at is not None:
        return WorkerHeartbeatResponse(removed=True)

    now = utcnow()
    apply_worker_heartbeat(req.worker_id, req, now)

    flapped = await record_version_flap(s, w, new_version=req.version, source=req.worker_id, kind="worker")
    renewed = await renew_worker_leases(s, req.worker_id, now)
    revoked = await revoked_active_granules(s, req)
    update_requested = await consume_one_shot_signal(
        s, w, "update_requested_at", source=w.worker_id, message="update signal delivered to worker"
    )
    gc_requested = await consume_one_shot_signal(
        s, w, "gc_requested_at", source=w.worker_id, message="cache GC signal delivered to worker"
    )

    if flapped or renewed or update_requested or gc_requested:
        await commit_and_publish(s, Scope.WORKERS)

    return WorkerHeartbeatResponse(
        desired_capacity=w.desired_capacity,
        revoked_granule_ids=revoked,
        update_requested=update_requested,
        operator_paused=bool(w.operator_paused),
        gc_requested=gc_requested,
    )


@router.post("/lease", response_model=LeaseResponse)
async def lease(req: LeaseRequest, s: AsyncSession = Depends(session)) -> LeaseResponse:
    async with _LEASE_LOCK:
        return await _lease_locked(req, s)


async def _lease_locked(req: LeaseRequest, s: AsyncSession) -> LeaseResponse:
    worker = await _active_worker_or_403(s, req.worker_id)
    now = utcnow()
    expires = now + LEASE_DURATION

    # Two clamps below req.capacity: queue-based backpressure (0 disables) and
    # per-worker runtime override (belt-and-braces against an old worker that
    # doesn't self-clamp).
    limit = await lease_limit(s, worker, req)
    if limit <= 0:
        return LeaseResponse(items=[], lease_expires_at=expires)

    items = await claim_pending_granules(s, req.worker_id, limit, now, expires)
    if items:
        await log(s, req.worker_id, f"leased {len(items)} granules")
        await commit_and_publish(s, Scope.BATCHES)
    return LeaseResponse(items=items, lease_expires_at=expires)


@router.post("/events")
async def emit_event(event: GranuleEvent, s: AsyncSession = Depends(session)) -> dict:
    """Single ingress for every worker-reported transition. Replaces the old
    /state, /upload, /failure, /delete-confirmed quartet. The state machine
    (`shared/state_machine.py::apply`) owns the transition rules; this handler
    is the auth + persistence + log shell around it."""
    g = await get_or_404(s, Granule, event.granule_id, "granule not found")
    # DeleteConfirmed is gated by /deletable/{worker_id} (which filters by
    # ownership and ack state); other events require an active lease.
    if not isinstance(event, DeleteConfirmed) and g.leased_by != event.worker_id:
        raise HTTPException(409, "granule not leased by this worker")
    result = await apply_transition(s, g, event, now=utcnow())
    if isinstance(event, UploadCompleted):
        evict_granule(g.granule_id, g.batch_id)
        await log(
            s,
            event.worker_id,
            f"uploaded {len(event.objects)} objects",
            granule_id=g.granule_id,
            batch_id=g.batch_id,
        )
    elif isinstance(event, ProcessingFailed):
        evict_granule(g.granule_id, g.batch_id)
        await log(
            s,
            event.worker_id,
            f"processing failed (exit={event.exit_code}) retry={g.retry_count}",
            level="error" if g.state == GranuleState.BLACKLISTED.value else "warn",
            granule_id=g.granule_id,
            batch_id=g.batch_id,
        )
    await commit_and_publish(s, result.publish_scope)
    return {"ok": True, "state": g.state}


@router.get("/deletable/{worker_id}")
async def deletable(worker_id: str, s: AsyncSession = Depends(session)) -> list[DeletableGranule]:
    """Worker polls for granules whose all objects are acked — safe to delete source.

    Single pass: keep only granules where every non-deleted row has acked_at —
    `count(*) = count(acked_at)` on the HAVING clause filters those out. Avoids
    the N+1 of re-querying each granule's siblings."""
    fully_acked_granules = (
        select(GranuleObject.granule_id)
        .where(GranuleObject.deleted_at.is_(None))
        .group_by(GranuleObject.granule_id)
        .having(func.count() == func.count(GranuleObject.acked_at))
        .scalar_subquery()
    )
    rows = (
        (
            await s.execute(
                select(GranuleObject)
                .where(GranuleObject.worker_id == worker_id)
                .where(GranuleObject.acked_at.is_not(None))
                .where(GranuleObject.deleted_at.is_(None))
                .where(GranuleObject.granule_id.in_(fully_acked_granules))
            )
        )
        .scalars()
        .all()
    )

    by_granule: dict[str, list[str]] = {}
    for o in rows:
        by_granule.setdefault(o.granule_id, []).append(o.object_key)
    return [DeletableGranule(granule_id=gid, object_keys=keys) for gid, keys in by_granule.items()]


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
    w = await get_or_404(s, Worker, worker_id, "worker not found")
    w.desired_capacity = desired_capacity
    await log(s, worker_id, f"capacity override → {desired_capacity} (env cap {w.capacity})")
    await commit_and_publish(s, Scope.WORKERS)
    return {"ok": True, "desired_capacity": desired_capacity}


@router.post("/{worker_id}/update")
async def request_update(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    return await signal_one_shot(
        s,
        Worker,
        worker_id,
        "update_requested_at",
        scope=Scope.WORKERS,
        message="update requested via UI",
    )


@router.post("/update-all")
async def request_update_all(s: AsyncSession = Depends(session)) -> dict:
    rows = (await s.execute(select(Worker).where(Worker.removed_at.is_(None)))).scalars().all()
    count = 0
    now = utcnow()
    for w in rows:
        if w.operator_paused:
            continue
        w.update_requested_at = now
        count += 1
    if count:
        await log(s, "operator", f"update-all: {count} worker(s)")
        await commit_and_publish(s, Scope.WORKERS)
    return {"ok": True, "count": count}


@router.post("/remove-all")
async def request_remove_all(s: AsyncSession = Depends(session)) -> dict:
    rows = (await s.execute(select(Worker).where(Worker.removed_at.is_(None)))).scalars().all()
    now = utcnow()
    for w in rows:
        w.removed_at = now
        w.operator_paused = True
    count = len(rows)
    if count:
        await log(s, "operator", f"remove-all: {count} worker(s)")
        await commit_and_publish(s, Scope.WORKERS)
        for w in rows:
            telemetry.evict_worker(w.worker_id)
    return {"ok": True, "count": count}


@router.put("/{worker_id}/pause")
async def set_paused(
    worker_id: str,
    operator_paused: bool = Body(embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    w = await get_or_404(s, Worker, worker_id, "worker not found")
    w.operator_paused = operator_paused
    await log(s, worker_id, f"worker {'paused' if operator_paused else 'resumed'} via UI")
    await commit_and_publish(s, Scope.WORKERS)
    return {"ok": True, "operator_paused": operator_paused}


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
    await get_or_404(s, Worker, worker_id, "worker not found")
    revoked = await revoke_worker_leases(s, worker_id, utcnow())
    if revoked:
        await log(s, worker_id, f"force-revoked {revoked} lease(s) via UI")
    await commit_and_publish(s, Scope.WORKERS, Scope.BATCHES if revoked else None)
    return {"ok": True, "revoked": revoked}


@router.post("/{worker_id}/gc")
async def request_gc(worker_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Operator-triggered remote GC. Same one-shot pattern as restart: orch
    sets a timestamp, next heartbeat reply forwards it, worker runs prune_caches
    out-of-band of its periodic loop."""
    return await signal_one_shot(
        s,
        Worker,
        worker_id,
        "gc_requested_at",
        scope=Scope.WORKERS,
        message="cache GC requested via UI",
    )


@router.delete("/{worker_id}")
async def remove_worker(
    worker_id: str,
    force: bool = Query(default=False),
    s: AsyncSession = Depends(session),
) -> dict:
    """Mark a worker as removed. Next heartbeat returns removed=True; worker
    drains in-flight work and exits. Row stays for retention sweep.
    Pass ?force=true to also revoke leases immediately."""
    w = await get_or_404(s, Worker, worker_id, "worker not found")
    if w.removed_at is not None:
        return {"ok": True}
    now = utcnow()
    if force:
        await revoke_worker_leases(s, worker_id, now)
        await s.execute(
            update(GranuleObject)
            .where(GranuleObject.worker_id == worker_id)
            .where(GranuleObject.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    w.removed_at = now
    w.operator_paused = True
    await log(s, worker_id, f"worker removed (force={force})")
    await commit_and_publish(s, Scope.WORKERS, Scope.BATCHES if force else None)
    telemetry.evict_worker(worker_id)
    return {"ok": True}
