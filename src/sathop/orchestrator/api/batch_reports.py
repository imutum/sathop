"""Delivery CSV: public batch facts and retained manifests, never access URLs/logs."""

from __future__ import annotations

import csv
import io
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Batch, DeliveryRecord, Granule, GranuleObject, get_session_maker, utcnow
from .batch_readmodels import summary

_CHUNK_SIZE = 500
_STATES = {
    "pending": "待分配",
    "queued": "已领取",
    "downloading": "下载中",
    "downloaded": "待处理",
    "processing": "处理中",
    "processed": "待上传",
    "uploading": "上传中",
    "uploaded": "待交付",
    "acked": "已交付待清理",
    "deleted": "已交付已清理",
    "failed": "待重试",
    "blacklisted": "已停止（含主动取消）",
}


def _csv(rows: list[list[object]]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    for row in rows:
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            # Quoting alone does not stop spreadsheet formula evaluation.
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return buf.getvalue()


async def retained_delivery_count(s: AsyncSession, batch_id: str) -> int:
    return (
        await s.scalar(
            select(func.count())
            .select_from(Granule)
            .where(Granule.batch_id == batch_id, Granule.state == "deleted")
        )
        or 0
    )


async def delivery_report(s: AsyncSession, batch: Batch) -> StreamingResponse:
    snapshot = await summary(s, batch)
    archived = max(0, (batch.delivered_count or 0) - await retained_delivery_count(s, batch.batch_id))
    # Bound the export to objects present when requested. Fetch only report
    # columns in keyset chunks; release the DB connection between chunks.
    upper = (
        await s.scalar(
            select(func.max(GranuleObject.id)).join(Granule).where(Granule.batch_id == batch.batch_id)
        )
        or 0
    )
    ledger_upper = (
        await s.scalar(select(func.max(DeliveryRecord.id)).where(DeliveryRecord.batch_id == batch.batch_id))
        or 0
    )
    recorded = (
        select(DeliveryRecord.id)
        .where(
            DeliveryRecord.id <= ledger_upper,
            DeliveryRecord.source_object_id == GranuleObject.id,
            DeliveryRecord.uploaded_at == GranuleObject.uploaded_at,
            DeliveryRecord.granule_id == GranuleObject.granule_id,
        )
        .exists()
    )
    header: list[list[object]] = [
        ["SatHop 批次交付报告"],
        ["生成时间（UTC）", utcnow().isoformat()],
        ["批次 ID", batch.batch_id],
        ["批次名称", batch.name],
        ["处理包", batch.bundle_ref],
        ["指定接收端", batch.target_receiver_id or "任意"],
        ["调度状态", "已暂停" if batch.status == "paused" else "运行中"],
        ["累计数据粒", sum(snapshot.counts.values())],
        ["累计已交付", snapshot.counts.get("acked", 0) + snapshot.counts.get("deleted", 0)],
        ["拉取重试耗尽产物", snapshot.objects_exhausted],
        ["历史已清理明细（数据粒）", archived],
        [
            "范围说明",
            "包含长期交付台账和仍保留的其他产物。升级前已清理的明细无法恢复；运行中的状态可能在导出期间变化。",
        ],
        ["验收说明", "已交付表示接收端已确认接收，请结合接收端实际文件验收。"],
        [],
        ["数据粒状态", "数量"],
        *[[_STATES.get(state, state), count] for state, count in snapshot.counts.items()],
        [],
        ["数据粒 ID", "产物路径", "大小（字节）", "SHA-256", "交付状态", "接收端", "确认时间（UTC）"],
    ]
    batch_id = batch.batch_id
    # End the metadata read transaction before streaming to a slow client.
    await s.rollback()

    async def chunks():
        yield "\ufeff" + _csv(header)
        after = 0
        while after < upper:
            async with get_session_maker()() as read:
                records = (
                    await read.execute(
                        select(
                            GranuleObject.id,
                            GranuleObject.granule_id,
                            GranuleObject.object_key,
                            GranuleObject.size,
                            GranuleObject.sha256,
                            GranuleObject.acked_at,
                            GranuleObject.acked_by,
                        )
                        .join(Granule)
                        .where(
                            Granule.batch_id == batch_id,
                            GranuleObject.id > after,
                            GranuleObject.id <= upper,
                            ~recorded,
                        )
                        .order_by(GranuleObject.id)
                        .limit(_CHUNK_SIZE)
                    )
                ).all()
            if not records:
                break
            yield _csv(
                [
                    [
                        gid,
                        key,
                        size,
                        sha,
                        "已交付" if ack else "待交付",
                        receiver,
                        ack.isoformat() if ack else "",
                    ]
                    for _, gid, key, size, sha, ack, receiver in records
                ]
            )
            after = records[-1][0]

        after = 0
        while after < ledger_upper:
            async with get_session_maker()() as read:
                receipts = (
                    await read.scalars(
                        select(DeliveryRecord)
                        .where(
                            DeliveryRecord.batch_id == batch_id,
                            DeliveryRecord.id > after,
                            DeliveryRecord.id <= ledger_upper,
                        )
                        .order_by(DeliveryRecord.id)
                        .limit(_CHUNK_SIZE)
                    )
                ).all()
            if not receipts:
                break
            yield _csv(
                [
                    [
                        r.granule_id,
                        r.object_key,
                        r.size,
                        r.sha256,
                        "已交付",
                        r.receiver_id,
                        r.delivered_at.isoformat(),
                    ]
                    for r in receipts
                ]
            )
            after = receipts[-1].id

    return StreamingResponse(
        chunks(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(batch_id, safe='')}-delivery.csv",
            "Cache-Control": "no-store",
        },
    )
