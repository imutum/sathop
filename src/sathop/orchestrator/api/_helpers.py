from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import GranuleObject

T = TypeVar("T")


async def get_or_404(s: AsyncSession, model: type[T], key: Any, detail: str) -> T:
    obj = await s.get(model, key)
    if obj is None:
        raise HTTPException(404, detail)
    return obj


def object_is_pending() -> ColumnElement[bool]:
    return and_(GranuleObject.acked_at.is_(None), GranuleObject.deleted_at.is_(None))


def object_is_exhausted() -> ColumnElement[bool]:
    return and_(
        object_is_pending(),
        func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures,
    )


def object_is_pullable() -> ColumnElement[bool]:
    return and_(
        object_is_pending(),
        func.coalesce(GranuleObject.failed_pulls, 0) < settings.max_pull_failures,
    )


def all_objects_acked() -> ColumnElement[bool]:
    """Aggregate predicate: every GranuleObject row in the current filter/group
    has acked_at set. One canonical home for "are all of a granule's objects
    acked?" — used both as a HAVING clause (workers.deletable, grouped per
    granule) and as a scalar over one granule (receivers.ack's UPLOADED→ACKED
    gate). Callers scope deleted_at themselves: ack counts every row, deletable
    only non-deleted ones."""
    return func.count() == func.count(GranuleObject.acked_at)
