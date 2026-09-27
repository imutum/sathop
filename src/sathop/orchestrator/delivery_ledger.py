"""Transactional, idempotent receipt archival; no URLs, inputs or credentials."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Collection, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from .db import Batch, DeliveryRecord, Granule, GranuleObject, get_session_maker


def has_delivery_record(*, upper_id: int | None = None) -> ColumnElement[bool]:
    """Match a retained object to its receipt, including possible SQLite ID reuse."""
    stmt = select(DeliveryRecord.id).where(
        DeliveryRecord.source_object_id == GranuleObject.id,
        DeliveryRecord.uploaded_at == GranuleObject.uploaded_at,
        DeliveryRecord.granule_id == GranuleObject.granule_id,
    )
    if upper_id is not None:
        stmt = stmt.where(DeliveryRecord.id <= upper_id)
    return stmt.exists()


async def iter_receipt_chunks(
    *conditions: ColumnElement[bool], upper_id: int, chunk_size: int = 500
) -> AsyncIterator[Sequence[DeliveryRecord]]:
    """Read up to the export's initial ID bound, releasing connections before yielding."""
    stmt = select(DeliveryRecord).where(*conditions, DeliveryRecord.id <= upper_id)
    after = 0
    while after < upper_id:
        async with get_session_maker()() as read:
            receipts = (
                await read.scalars(
                    stmt.where(DeliveryRecord.id > after).order_by(DeliveryRecord.id).limit(chunk_size)
                )
            ).all()
        if not receipts:
            break
        yield receipts
        after = receipts[-1].id


async def archive_confirmed(
    s: AsyncSession, *, granule_ids: Collection[str] | None = None, object_ids: Collection[int] | None = None
) -> None:
    """Archive in the caller's transaction, chunking both scans and inserts.

    Include upload timestamp in the identity: SQLite may reuse object IDs after
    retention. A repeated ACK or migration must preserve the original receipt.
    """
    stmt = (
        select(GranuleObject, Batch.batch_id, Batch.name, Batch.bundle_ref)
        .join(Granule, Granule.granule_id == GranuleObject.granule_id)
        .join(Batch, Batch.batch_id == Granule.batch_id)
        .where(GranuleObject.acked_at.is_not(None), ~has_delivery_record())
    )
    if granule_ids is not None:
        stmt = stmt.where(GranuleObject.granule_id.in_(granule_ids))
    if object_ids is not None:
        stmt = stmt.where(GranuleObject.id.in_(object_ids))
    insert = pg_insert if s.get_bind().dialect.name == "postgresql" else sqlite_insert
    after = 0
    while True:
        rows = (
            await s.execute(stmt.where(GranuleObject.id > after).order_by(GranuleObject.id).limit(500))
        ).all()
        if not rows:
            break
        values = []
        for obj, bid, name, bundle in rows:
            identity = hashlib.sha256(
                json.dumps([bid, obj.granule_id, obj.id, obj.uploaded_at.isoformat()]).encode()
            ).hexdigest()
            values.append(
                dict(
                    identity=identity,
                    source_object_id=obj.id,
                    uploaded_at=obj.uploaded_at,
                    batch_id=bid,
                    batch_name=name,
                    bundle_ref=bundle,
                    granule_id=obj.granule_id,
                    object_key=obj.object_key,
                    sha256=obj.sha256,
                    size=obj.size,
                    receiver_id=obj.acked_by,
                    delivered_at=obj.acked_at,
                )
            )
        await s.execute(
            insert(DeliveryRecord).values(values).on_conflict_do_nothing(index_elements=["identity"])
        )
        after = rows[-1][0].id
