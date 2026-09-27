"""Durable delivery history, usable after task retention or batch deletion."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import require_token
from ..db import Batch, get_session_maker, session, utcnow
from ..db import DeliveryRecord as R
from .batch_reports import _csv

router = APIRouter(prefix="/deliveries", tags=["deliveries"], dependencies=[Depends(require_token)])


class Receipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: str
    batch_name: str
    bundle_ref: str
    granule_id: str
    object_key: str
    sha256: str
    size: int
    receiver_id: str | None
    delivered_at: datetime
    batch_exists: bool = False


class DeliveryPage(BaseModel):
    items: list[Receipt]
    total: int
    total_bytes: int
    granules: int
    batches: int


def filters(
    q: str = Query("", max_length=200),
    batch_id: str | None = Query(None, max_length=200),
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> list:
    if since and until and since >= until:
        raise HTTPException(422, "开始时间必须早于结束时间")
    result = []
    if q.strip():
        result.append(
            or_(
                *(
                    c.icontains(q.strip(), autoescape=True)
                    for c in [R.batch_id, R.batch_name, R.granule_id, R.object_key, R.receiver_id]
                )
            )
        )
    if batch_id:
        result.append(R.batch_id == batch_id)
    if since:
        result.append(R.delivered_at >= since)
    if until:
        result.append(R.delivered_at < until)
    return result


@router.get("", response_model=DeliveryPage)
async def list_deliveries(
    conditions: list = Depends(filters),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: AsyncSession = Depends(session),
) -> DeliveryPage:
    total, size, granules, batches = (
        await s.execute(
            select(
                func.count(),
                func.coalesce(func.sum(R.size), 0),
                func.count(func.distinct(R.granule_id)),
                func.count(func.distinct(R.batch_id)),
            )
            .select_from(R)
            .where(*conditions)
        )
    ).one()
    rows = (
        await s.execute(
            select(R, Batch.batch_id)
            .outerjoin(Batch, Batch.batch_id == R.batch_id)
            .where(*conditions)
            .order_by(R.delivered_at.desc(), R.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return DeliveryPage(
        items=[
            Receipt.model_validate(row).model_copy(update={"batch_exists": bid is not None})
            for row, bid in rows
        ],
        total=total,
        total_bytes=size,
        granules=granules,
        batches=batches,
    )


@router.get("/export")
async def export_deliveries(conditions: list = Depends(filters), s: AsyncSession = Depends(session)):
    upper = await s.scalar(select(func.max(R.id)).where(*conditions)) or 0
    await s.rollback()

    async def chunks():
        yield "\ufeff" + _csv(
            [
                ["SatHop 已确认交付台账", "生成时间（UTC）", utcnow().isoformat()],
                ["说明", "仅包含已留存的接收确认；升级前已清理的历史无法恢复。时间为 UTC。"],
                [
                    "批次 ID",
                    "批次名称",
                    "处理包",
                    "数据粒 ID",
                    "产物路径",
                    "大小（字节）",
                    "SHA-256",
                    "接收端",
                    "确认时间（UTC）",
                ],
            ]
        )
        after = 0
        while after < upper:
            async with get_session_maker()() as read:
                rows = (
                    await read.scalars(
                        select(R).where(*conditions, R.id > after, R.id <= upper).order_by(R.id).limit(500)
                    )
                ).all()
            if not rows:
                break
            yield _csv(
                [
                    [
                        r.batch_id,
                        r.batch_name,
                        r.bundle_ref,
                        r.granule_id,
                        r.object_key,
                        r.size,
                        r.sha256,
                        r.receiver_id,
                        r.delivered_at.isoformat(),
                    ]
                    for r in rows
                ]
            )
            after = rows[-1].id

    return StreamingResponse(
        chunks(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="delivery-ledger.csv"',
            "Cache-Control": "no-store",
        },
    )
