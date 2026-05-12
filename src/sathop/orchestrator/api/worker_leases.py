"""Worker lease helpers."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import Credential, LeaseItem, LeaseRequest
from sathop.shared.state_machine import (
    LEASED_STATES,
    ClaimByLease,
    GranuleState,
    RevokedByOperator,
)

from ..config import settings
from ..db import Batch, Granule, GranuleObject, Worker
from ._transition import apply_transition

log = logging.getLogger("sathop.orchestrator.worker_leases")

LEASE_DURATION = timedelta(minutes=30)


async def count_worker_inflight(s: AsyncSession, worker_id: str) -> int:
    pre = await s.scalar(
        select(func.count())
        .select_from(Granule)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
    )
    post = await s.scalar(
        select(func.count(distinct(GranuleObject.granule_id)))
        .where(GranuleObject.worker_id == worker_id)
        .where(GranuleObject.deleted_at.is_(None))
    )
    return int(pre or 0) + int(post or 0)


async def lease_limit(s: AsyncSession, worker: Worker, req: LeaseRequest) -> int:
    limit = req.capacity
    if settings.max_inflight_per_worker > 0:
        holding = await count_worker_inflight(s, req.worker_id)
        limit = min(limit, max(0, settings.max_inflight_per_worker - holding))
    if worker.desired_capacity is not None:
        limit = min(limit, max(0, worker.desired_capacity))
    return limit


def json_dict_or_empty(raw: str | None, *, field: str, context: str) -> dict:
    """Parse a DB-stored JSON dict, falling back to {} on any shape error.
    `field`/`context` go into the warning so operators can trace a silently
    empty payload back to its row."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("%s: corrupted %s JSON (%s) — treating as empty", context, field, e)
        return {}
    if not isinstance(value, dict):
        log.warning("%s: %s JSON is not an object — treating as empty", context, field)
        return {}
    return value


def credential_map(raw: str | None, *, context: str) -> dict[str, Credential]:
    """Build {name: Credential} from a DB-stored JSON object. Validation
    failure is logged with `context` and yields {}; the worker downloads
    will surface as 401/403 with no auth (downloader emits its own warning
    on partial credentials)."""
    source = json_dict_or_empty(raw, field="credentials", context=context)
    try:
        return {k: Credential.model_validate(v) for k, v in source.items()}
    except ValueError as e:
        log.warning("%s: credential validation failed (%s) — using empty map", context, e)
        return {}


def lease_item(granule: Granule, batch: Batch | None) -> LeaseItem:
    ctx = f"granule {granule.granule_id}"
    return LeaseItem(
        granule_id=granule.granule_id,
        batch_id=granule.batch_id,
        bundle_ref=batch.bundle_ref if batch else "",
        inputs=json.loads(granule.inputs_json),
        meta=json.loads(granule.meta_json or "{}"),
        execution_env=json_dict_or_empty(
            batch.execution_env_json if batch else None, field="execution_env", context=ctx
        ),
        credentials=credential_map(batch.credentials_json if batch else None, context=ctx),
    )


async def claim_pending_granules(
    s: AsyncSession,
    worker_id: str,
    limit: int,
    now,
    expires,
) -> list[LeaseItem]:
    stmt = (
        select(Granule)
        .where(Granule.state == GranuleState.PENDING.value)
        .where((Granule.leased_by.is_(None)) | (Granule.lease_expires_at < now))
        .limit(limit)
    )
    rows = (await s.execute(stmt)).scalars().all()

    items: list[LeaseItem] = []
    for granule in rows:
        # SQL above pre-filters state==PENDING so apply_transition's default
        # raise_409 policy is unreachable in practice.
        await apply_transition(
            s,
            granule,
            ClaimByLease(
                granule_id=granule.granule_id,
                worker_id=worker_id,
                lease_expires_at=expires,
            ),
            now=now,
        )
        batch = await s.get(Batch, granule.batch_id)
        items.append(lease_item(granule, batch))
    return items


async def held_granule_sample(s: AsyncSession, worker_id: str, limit: int = 5) -> list[str]:
    leased = (
        (
            await s.execute(
                select(Granule.granule_id)
                .where(Granule.leased_by == worker_id)
                .where(Granule.state.in_(LEASED_STATES))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    uploaded = (
        (
            await s.execute(
                select(distinct(GranuleObject.granule_id))
                .where(GranuleObject.worker_id == worker_id)
                .where(GranuleObject.deleted_at.is_(None))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list({*leased, *uploaded})[:limit]


async def renew_worker_leases(s: AsyncSession, worker_id: str, now) -> None:
    await s.execute(
        update(Granule)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
        .where(Granule.lease_expires_at < now + LEASE_DURATION / 2)
        .values(lease_expires_at=now + LEASE_DURATION)
    )


async def revoke_worker_leases(s: AsyncSession, worker_id: str, now) -> int:
    rows = (
        (
            await s.execute(
                select(Granule).where(Granule.leased_by == worker_id).where(Granule.state.in_(LEASED_STATES))
            )
        )
        .scalars()
        .all()
    )
    for granule in rows:
        # SQL above pre-filters LEASED_STATES so the default raise_409 policy
        # is unreachable in practice.
        await apply_transition(
            s,
            granule,
            RevokedByOperator(granule_id=granule.granule_id),
            now=now,
        )
    return len(rows)
