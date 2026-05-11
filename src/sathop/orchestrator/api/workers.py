"""Worker-facing endpoints: register, heartbeat, lease, upload, delete-confirm."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    LEASED_STATES,
    DeletableGranule,
    GranuleState,
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

from ..config import require_token
from ..db import Granule, GranuleObject, Worker, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from .worker_heartbeat import (
    apply_worker_heartbeat,
    consume_gc_signal,
    consume_restart_signal,
    record_worker_version,
    revoked_active_granules,
)
from .worker_leases import (
    LEASE_DURATION,
    claim_pending_granules,
    count_worker_inflight,
    held_granule_sample,
    lease_limit,
    renew_worker_leases,
    revoke_worker_leases,
)
from .worker_transitions import STATE_PREDECESSOR, apply_state_report, mark_failed, mark_uploaded

router = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_token)])


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
    await record_worker_version(s, w, req)
    apply_worker_heartbeat(w, req, now)
    await renew_worker_leases(s, req.worker_id, now)

    # Diff worker's active set vs. DB; any mismatch becomes a cancellation
    # instruction in this heartbeat response.
    revoked = await revoked_active_granules(s, req)

    restart_requested = await consume_restart_signal(s, w)
    gc_requested = await consume_gc_signal(s, w)

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
    limit = await lease_limit(s, worker, req)
    if limit <= 0:
        return LeaseResponse(items=[], lease_expires_at=expires)

    items = await claim_pending_granules(s, req.worker_id, limit, now, expires)
    if items:
        await log(s, req.worker_id, f"leased {len(items)} granules")
    await commit_and_publish(s, "batches" if items else None)
    return LeaseResponse(items=items, lease_expires_at=expires)


@router.post("/state")
async def report_state(req: StateUpdate, s: AsyncSession = Depends(session)) -> dict:
    expected = STATE_PREDECESSOR.get(req.state.value)
    if expected is None:
        raise HTTPException(422, f"state {req.state.value!r} is not worker-reportable")
    g = await _leased_granule_or_409(s, req.granule_id, req.worker_id)
    if g.state != expected:
        raise HTTPException(409, f"cannot transition {g.state!r} → {req.state.value!r}")
    apply_state_report(s, g, req, utcnow())
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

    mark_uploaded(s, g, req, utcnow())
    await log(s, req.worker_id, f"uploaded {len(req.objects)} objects", granule_id=g.granule_id)
    await commit_and_publish(s, "batches")
    return {"ok": True}


@router.post("/failure")
async def failure(req: ProcessFailure, s: AsyncSession = Depends(session)) -> dict:
    g = await _leased_granule_or_409(s, req.granule_id, req.worker_id)
    # The failure path can only fire while the worker still genuinely owns
    # the granule. Anything outside the leased states means cancel/sweeper
    # got there first; the worker should swallow the 409 and stop reporting.
    if g.state not in LEASED_STATES:
        raise HTTPException(409, f"failure not accepted in state {g.state!r} (lease was revoked)")

    mark_failed(g, req, utcnow())
    await log(
        s,
        req.worker_id,
        f"processing failed (exit={req.exit_code}) retry={g.retry_count}",
        level="error" if g.state == GranuleState.BLACKLISTED.value else "warn",
        granule_id=g.granule_id,
    )
    await commit_and_publish(s, "batches")
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
        await s.execute(
            select(GranuleObject)
            .where(GranuleObject.worker_id == worker_id)
            .where(GranuleObject.acked_at.is_not(None))
            .where(GranuleObject.deleted_at.is_(None))
            .where(GranuleObject.granule_id.in_(fully_acked_granules))
        )
    ).scalars().all()

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
    revoked = await revoke_worker_leases(s, worker_id, utcnow())
    if revoked:
        await log(s, worker_id, f"force-revoked {revoked} lease(s) via UI")
    await commit_and_publish(s, "workers", "batches" if revoked else None)
    return {"ok": True, "revoked": revoked}


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
    inflight = await count_worker_inflight(s, worker_id)
    if inflight > 0:
        sample = await held_granule_sample(s, worker_id)
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
