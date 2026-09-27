"""Durable delivery history, usable after task retention or batch deletion."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from ..config import require_token
from ..db import Batch, DeliveryRecord, session, utcnow
from ..delivery_ledger import iter_receipt_chunks
from .csv_export import csv_response

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
) -> list[ColumnElement[bool]]:
    if since and until and since >= until:
        raise HTTPException(422, "开始时间必须早于结束时间")
    result = []
    if q.strip():
        result.append(
            or_(
                *(
                    column.icontains(q.strip(), autoescape=True)
                    for column in [
                        DeliveryRecord.batch_id,
                        DeliveryRecord.batch_name,
                        DeliveryRecord.granule_id,
                        DeliveryRecord.object_key,
                        DeliveryRecord.receiver_id,
                    ]
                )
            )
        )
    if batch_id:
        result.append(DeliveryRecord.batch_id == batch_id)
    if since:
        result.append(DeliveryRecord.delivered_at >= since)
    if until:
        result.append(DeliveryRecord.delivered_at < until)
    return result


@router.get("", response_model=DeliveryPage)
async def list_deliveries(
    conditions: list[ColumnElement[bool]] = Depends(filters),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: AsyncSession = Depends(session),
) -> DeliveryPage:
    total, size, granules, batches = (
        await s.execute(
            select(
                func.count(),
                func.coalesce(func.sum(DeliveryRecord.size), 0),
                func.count(func.distinct(DeliveryRecord.granule_id)),
                func.count(func.distinct(DeliveryRecord.batch_id)),
            )
            .select_from(DeliveryRecord)
            .where(*conditions)
        )
    ).one()
    rows = (
        await s.execute(
            select(DeliveryRecord, Batch.batch_id)
            .outerjoin(Batch, Batch.batch_id == DeliveryRecord.batch_id)
            .where(*conditions)
            .order_by(DeliveryRecord.delivered_at.desc(), DeliveryRecord.id.desc())
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
async def export_deliveries(
    conditions: list[ColumnElement[bool]] = Depends(filters), s: AsyncSession = Depends(session)
) -> StreamingResponse:
    upper = await s.scalar(select(func.max(DeliveryRecord.id)).where(*conditions)) or 0
    await s.rollback()

    async def chunks():
        yield [
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
        async for receipts in iter_receipt_chunks(*conditions, upper_id=upper):
            yield [
                [
                    receipt.batch_id,
                    receipt.batch_name,
                    receipt.bundle_ref,
                    receipt.granule_id,
                    receipt.object_key,
                    receipt.size,
                    receipt.sha256,
                    receipt.receiver_id,
                    receipt.delivered_at.isoformat(),
                ]
                for receipt in receipts
            ]

    return csv_response(chunks(), "delivery-ledger.csv")
