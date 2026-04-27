"""Receiver-facing endpoints: register, heartbeat, pull, ack."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    AckReport,
    GranuleState,
    PullItem,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverRegister,
)

from ..config import require_token
from ..db import Batch, Granule, GranuleObject, Receiver, session, utcnow
from ..pubsub import log_event as log
from ..pubsub import publish

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
    await s.commit()
    publish({"scope": "receivers"})
    return {"ok": True}


@router.post("/heartbeat")
async def heartbeat(req: ReceiverHeartbeat, s: AsyncSession = Depends(session)) -> dict:
    r = await s.get(Receiver, req.receiver_id)
    if r is None:
        raise HTTPException(404, "receiver not registered")
    r.last_seen = utcnow()
    r.disk_free_gb = req.disk_free_gb
    await s.commit()
    publish({"scope": "receivers"})
    return {"ok": True}


@router.post("/pull", response_model=PullResponse)
async def pull(req: PullRequest, s: AsyncSession = Depends(session)) -> PullResponse:
    """Return objects this receiver should fetch. Excludes already-acked and other-receiver-bound objects."""
    r = await s.get(Receiver, req.receiver_id)
    if r is None or not r.enabled:
        raise HTTPException(403, "receiver not registered or disabled")

    stmt = (
        select(GranuleObject, Granule, Batch)
        .join(Granule, GranuleObject.granule_id == Granule.granule_id)
        .join(Batch, Granule.batch_id == Batch.batch_id)
        .where(GranuleObject.acked_at.is_(None))
        .where(GranuleObject.deleted_at.is_(None))
        .where((Batch.target_receiver_id == req.receiver_id) | (Batch.target_receiver_id.is_(None)))
        .where(Granule.state == GranuleState.UPLOADED.value)
        .limit(req.limit)
    )
    rows = (await s.execute(stmt)).all()

    items = [
        PullItem(
            granule_id=o.granule_id,
            batch_id=g.batch_id,
            object_id=o.id,
            object_key=o.object_key,
            presigned_url=o.presigned_url,
            sha256=o.sha256,
            size=o.size,
        )
        for (o, g, _b) in rows
    ]
    return PullResponse(items=items)


@router.post("/ack")
async def ack(req: AckReport, s: AsyncSession = Depends(session)) -> dict:
    obj = await s.get(GranuleObject, req.object_id)
    if obj is None:
        raise HTTPException(404, "object not found")

    if not req.success:
        await log(
            s,
            req.receiver_id,
            f"pull failed: {req.error}",
            level="warn",
            granule_id=obj.granule_id,
        )
        await s.commit()
        return {"ok": True, "retried": False}

    if req.sha256 != obj.sha256:
        await log(
            s,
            req.receiver_id,
            f"sha256 mismatch object_id={req.object_id}",
            level="error",
            granule_id=obj.granule_id,
        )
        raise HTTPException(400, "sha256 mismatch")

    now = utcnow()
    obj.acked_at = now
    obj.acked_by = req.receiver_id

    siblings = (
        (await s.execute(select(GranuleObject).where(GranuleObject.granule_id == obj.granule_id)))
        .scalars()
        .all()
    )
    if all(o.acked_at is not None for o in siblings):
        g = await s.get(Granule, obj.granule_id)
        if g is not None:
            g.state = GranuleState.ACKED.value
            g.updated_at = now
    await log(s, req.receiver_id, f"acked {obj.object_key}", granule_id=obj.granule_id)
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True}
