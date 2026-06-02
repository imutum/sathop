"""Receiver-facing endpoints: register, heartbeat, pull, ack, ca-bundle."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    AckBatch,
    AckBatchResponse,
    AckReport,
    PullItem,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverHeartbeatResponse,
    ReceiverRegister,
)
from sathop.shared.state_machine import (
    GranuleState,
    ObjectAcked,
    Scope,
)

from .. import db, telemetry
from ..config import require_token, settings
from ..db import Batch, Granule, GranuleObject, Receiver, Worker, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from ._helpers import all_objects_acked, get_or_404, object_pull_claimable
from ._transition import apply_transition
from .one_shot import consume_one_shot_signal, record_version_flap, signal_one_shot

router = APIRouter(prefix="/receivers", tags=["receivers"], dependencies=[Depends(require_token)])


@router.post("/register")
async def register(req: ReceiverRegister, s: AsyncSession = Depends(session)) -> dict:
    r = await s.get(Receiver, req.receiver_id)
    if r is None:
        r = Receiver(receiver_id=req.receiver_id, version=req.version, platform=req.platform)
        s.add(r)
        await log(s, req.receiver_id, f"receiver registered ({req.platform})")
    else:
        r.version = req.version
        r.platform = req.platform
        r.last_seen = utcnow()
    await commit_and_publish(s, Scope.RECEIVERS)
    return {"ok": True}


@router.post("/heartbeat", response_model=ReceiverHeartbeatResponse)
async def heartbeat(req: ReceiverHeartbeat, s: AsyncSession = Depends(session)) -> ReceiverHeartbeatResponse:
    r = await get_or_404(s, Receiver, req.receiver_id, "receiver not registered")
    now = utcnow()

    # PG (multi-process): telemetry must be cross-process → write it to the
    # Receiver row (receiver_snapshot's DB fallback reads it back). SQLite: keep
    # it in-memory to avoid WAL churn.
    if db.is_postgres():
        r.last_seen = now
        r.disk_free_gb = req.disk_free_gb
        r.queue_pulling = req.queue_pulling or 0
        r.recent_pull_bps = req.recent_pull_bps or 0
    else:
        telemetry.update_receiver(
            req.receiver_id,
            telemetry.ReceiverTelemetry(
                last_seen=now,
                disk_free_gb=req.disk_free_gb,
                queue_pulling=req.queue_pulling or 0,
                recent_pull_bps=req.recent_pull_bps or 0,
            ),
        )

    flapped = await record_version_flap(
        s, r, new_version=req.version, source=req.receiver_id, kind="receiver"
    )
    restart_requested = await consume_one_shot_signal(
        s, r, "restart_requested_at", source=req.receiver_id, message="restart signal delivered to receiver"
    )

    if flapped or restart_requested or db.is_postgres():
        await commit_and_publish(s, Scope.RECEIVERS)

    return ReceiverHeartbeatResponse(restart_requested=restart_requested)


@router.post("/pull", response_model=PullResponse)
async def pull(req: PullRequest, s: AsyncSession = Depends(session)) -> PullResponse:
    """Atomically soft-claim up to `limit` pullable objects for this receiver so
    that N receivers fetch disjoint sets rather than all redundantly pulling the
    same objects. Mirrors the worker lease (worker_leases.claim_pending_granules):
    one `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED LIMIT n) RETURNING`
    stamps pull_lease_by/expires_at. The claim is advisory — an expired lease is
    re-claimable so no sweeper is needed — and `_record_pull_failure` clears it for
    instant failover. Excludes already-acked, exhausted, and peer-claimed objects."""
    r = await s.get(Receiver, req.receiver_id)
    if r is None or not r.enabled:
        raise HTTPException(403, "receiver not registered or disabled")

    now = utcnow()
    expires = now + timedelta(seconds=settings.pull_lease_sec)
    claimable = (
        select(GranuleObject.id)
        .join(Granule, GranuleObject.granule_id == Granule.granule_id)
        .join(Batch, Granule.batch_id == Batch.batch_id)
        .where(object_pull_claimable(now))
        .where(Granule.state == GranuleState.UPLOADED.value)
        .where((Batch.target_receiver_id == req.receiver_id) | (Batch.target_receiver_id.is_(None)))
        .order_by(GranuleObject.id)
        .limit(req.limit)
        # Postgres: lock only the picked object rows and skip any a concurrent
        # receiver's /pull already holds, so claims are disjoint. SQLite has no row
        # locks — SQLAlchemy omits this and the single writer serialises claims.
        .with_for_update(skip_locked=True, of=GranuleObject)
        .scalar_subquery()
    )
    rows = (
        await s.execute(
            update(GranuleObject)
            .where(GranuleObject.id.in_(claimable))
            .values(pull_lease_by=req.receiver_id, pull_lease_expires_at=expires)
            .returning(
                GranuleObject.id,
                GranuleObject.granule_id,
                GranuleObject.object_key,
                GranuleObject.presigned_url,
                GranuleObject.sha256,
                GranuleObject.size,
            )
        )
    ).all()
    if not rows:
        return PullResponse(items=[])

    gids = {row.granule_id for row in rows}
    batch_by_gid = {
        g.granule_id: g.batch_id
        for g in (await s.execute(select(Granule).where(Granule.granule_id.in_(gids)))).scalars().all()
    }
    await commit_and_publish(s)
    items = [
        PullItem(
            granule_id=row.granule_id,
            batch_id=batch_by_gid.get(row.granule_id, ""),
            object_id=row.id,
            object_key=row.object_key,
            presigned_url=row.presigned_url,
            sha256=row.sha256,
            size=row.size,
        )
        for row in rows
    ]
    return PullResponse(items=items)


async def _record_pull_failure(
    s: AsyncSession, receiver_id: str, obj: GranuleObject, error: str | None, bid: str | None
) -> bool:
    """Bump the object's failed-pull counter and log it; return whether it's now
    exhausted (>= max_pull_failures). Shared by /ack and /ack/batch."""
    count = (obj.failed_pulls or 0) + 1
    obj.failed_pulls = count
    # Release the soft-claim so the object re-offers immediately (to this or any
    # other receiver) rather than waiting out the lease. Once exhausted it leaves
    # the pullable set anyway, so this never resurrects a dead object.
    obj.pull_lease_by = None
    obj.pull_lease_expires_at = None
    exhausted = count >= settings.max_pull_failures
    await log(
        s,
        receiver_id,
        f"pull failed ({obj.failed_pulls}/{settings.max_pull_failures}): {error}"
        + (" — giving up, no further offers" if exhausted else ""),
        level="error" if exhausted else "warn",
        granule_id=obj.granule_id,
        batch_id=bid,
    )
    return exhausted


async def _log_sha_mismatch(s: AsyncSession, receiver_id: str, obj: GranuleObject, bid: str | None) -> None:
    await log(
        s,
        receiver_id,
        f"sha256 mismatch object_id={obj.id}",
        level="error",
        granule_id=obj.granule_id,
        batch_id=bid,
    )


async def _mark_acked(s: AsyncSession, receiver_id: str, obj: GranuleObject, bid: str | None, now) -> None:
    obj.acked_at = now
    obj.acked_by = receiver_id
    await log(s, receiver_id, f"acked {obj.object_key}", granule_id=obj.granule_id, batch_id=bid)


@router.post("/ack")
async def ack(req: AckReport, s: AsyncSession = Depends(session)) -> dict:
    obj = await get_or_404(s, GranuleObject, req.object_id, "object not found")
    g = await s.get(Granule, obj.granule_id)
    bid = g.batch_id if g else None

    if not req.success:
        exhausted = await _record_pull_failure(s, req.receiver_id, obj, req.error, bid)
        await commit_and_publish(s)
        return {"ok": True, "retried": not exhausted, "failed_pulls": obj.failed_pulls}

    if req.sha256 != obj.sha256:
        await _log_sha_mismatch(s, req.receiver_id, obj, bid)
        raise HTTPException(400, "sha256 mismatch")

    now = utcnow()
    await _mark_acked(s, req.receiver_id, obj, bid, now)
    # Flush so the just-set acked_at is visible to the aggregate count below.
    await s.flush()
    all_acked = await s.scalar(select(all_objects_acked()).where(GranuleObject.granule_id == obj.granule_id))
    if g is not None and all_acked:
        await apply_transition(s, g, ObjectAcked(granule_id=g.granule_id), now=now, on_conflict="skip")
    await commit_and_publish(s, Scope.BATCHES)
    return {"ok": True}


async def _apply_ack(s: AsyncSession, a: AckReport, obj: GranuleObject, bid: str | None, now) -> bool:
    """Apply one ack to its (already-loaded) object. Returns True if it became
    acked (so the caller checks that granule for UPLOADED→ACKED). Shares the
    failure/mismatch/ack-set side effects with the single /ack via the helpers
    above; differs only in that a non-fatal issue logs and returns False rather
    than shaping a response / raising 400 / committing."""
    if not a.success:
        await _record_pull_failure(s, a.receiver_id, obj, a.error, bid)
        return False
    if a.sha256 != obj.sha256:
        await _log_sha_mismatch(s, a.receiver_id, obj, bid)
        return False
    await _mark_acked(s, a.receiver_id, obj, bid, now)
    return True


@router.post("/ack/batch", response_model=AckBatchResponse)
async def ack_batch(req: AckBatch, s: AsyncSession = Depends(session)) -> AckBatchResponse:
    """Batched twin of /ack: apply a receiver's buffered ack reports in ONE
    transaction, paying the per-request cost once. Objects + granules are bulk-
    loaded; acks apply in list order; granules whose objects all become acked
    transition UPLOADED→ACKED in the same commit. A missing object or a
    sha-mismatched success is skipped (logged) — never fails the batch."""
    if not req.acks:
        return AckBatchResponse()
    oids = list({a.object_id for a in req.acks})
    objs = (await s.execute(select(GranuleObject).where(GranuleObject.id.in_(oids)))).scalars().all()
    by_id = {o.id: o for o in objs}
    gids = list({o.granule_id for o in objs})
    g_by_id = {
        g.granule_id: g
        for g in (await s.execute(select(Granule).where(Granule.granule_id.in_(gids)))).scalars().all()
    }
    now = utcnow()
    acked_granules: set[str] = set()
    for a in req.acks:
        obj = by_id.get(a.object_id)
        if obj is None:
            continue
        g = g_by_id.get(obj.granule_id)
        if await _apply_ack(s, a, obj, g.batch_id if g else None, now):
            acked_granules.add(obj.granule_id)

    # Flush so the just-set acked_at is visible, then promote in one query every
    # touched granule whose objects are now all acked (batched all_objects_acked).
    if acked_granules:
        await s.flush()
        done = (
            (
                await s.execute(
                    select(GranuleObject.granule_id)
                    .where(GranuleObject.granule_id.in_(acked_granules))
                    .group_by(GranuleObject.granule_id)
                    .having(all_objects_acked())
                )
            )
            .scalars()
            .all()
        )
        for gid in done:
            g = g_by_id.get(gid)
            if g is not None:
                await apply_transition(s, g, ObjectAcked(granule_id=gid), now=now, on_conflict="skip")

    await commit_and_publish(s, Scope.BATCHES)
    return AckBatchResponse()


@router.post("/{receiver_id}/restart")
async def request_restart(receiver_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Operator-triggered restart — see workers.request_restart."""
    return await signal_one_shot(
        s,
        Receiver,
        receiver_id,
        "restart_requested_at",
        scope=Scope.RECEIVERS,
        message="restart requested via UI",
    )


@router.put("/{receiver_id}/enabled")
async def set_enabled(
    receiver_id: str,
    enabled: bool = Body(embed=True),
    s: AsyncSession = Depends(session),
) -> dict:
    """Runtime kill-switch. Disabled receivers receive 403 on next pull,
    so already-pulled objects can still be acked but no new ones flow."""
    r = await get_or_404(s, Receiver, receiver_id, "receiver not found")
    r.enabled = enabled
    await log(s, receiver_id, f"receiver {'enabled' if enabled else 'disabled'}")
    await commit_and_publish(s, Scope.RECEIVERS)
    return {"ok": True, "enabled": enabled}


@router.get("/ca-bundle")
async def ca_bundle(s: AsyncSession = Depends(session)) -> Response:
    """Concatenate every registered worker's self-signed root CA into a single
    PEM bundle. Receiver writes this to a local file at startup and points
    httpx at it (verify=path), giving precise trust without skip_verify.

    Empty bundle (no workers uploaded a CA) returns 204 — receiver should treat
    that as "no orchestrator-managed trust available, fall back to system CAs"."""
    rows = (await s.execute(select(Worker.ca_pem).where(Worker.ca_pem.is_not(None)))).scalars().all()
    pems = [p.strip() for p in rows if p and p.strip()]
    if not pems:
        return Response(status_code=204)
    return PlainTextResponse("\n".join(pems) + "\n")


@router.delete("/{receiver_id}")
async def forget_receiver(receiver_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Permanently remove a decommissioned receiver row. Refuses if it's still
    enabled — operator must disable first to stop in-flight ack races."""
    r = await get_or_404(s, Receiver, receiver_id, "receiver not found")
    if r.enabled:
        raise HTTPException(409, "receiver is still enabled — disable it first")
    await s.delete(r)
    await log(s, receiver_id, "receiver forgotten (row deleted)")
    await commit_and_publish(s, Scope.RECEIVERS)
    telemetry.evict_receiver(receiver_id)
    return {"ok": True}
