from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, func, or_
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


def object_pull_claimable(now) -> ColumnElement[bool]:
    """A pullable object a receiver may soft-claim on /pull: pullable AND its
    pull-lease is free (never claimed) or expired. A non-expired claim — held by
    any receiver, including the requester — is excluded, so concurrent receivers
    claim disjoint sets and one receiver can't out-claim what it can drain. An
    expired claim (dead receiver) re-offers to whoever asks next, which is why no
    sweeper is needed; on pull failure the claim is cleared for instant failover."""
    return and_(
        object_is_pullable(),
        or_(
            GranuleObject.pull_lease_by.is_(None),
            GranuleObject.pull_lease_expires_at < now,
        ),
    )


def all_objects_acked() -> ColumnElement[bool]:
    """Aggregate predicate: every GranuleObject row in the current filter/group
    has acked_at set. One canonical home for "are all of a granule's objects
    acked?" — used both as a HAVING clause (workers.deletable, grouped per
    granule) and as a scalar over one granule (receivers.ack's UPLOADED→ACKED
    gate). Callers scope deleted_at themselves: ack counts every row, deletable
    only non-deleted ones."""
    return func.count() == func.count(GranuleObject.acked_at)
