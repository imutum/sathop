"""Lease lifecycle for the Worker scope.

Three concerns live here:

1. **Quota policy** (`compute_lease_quota`) — the pure-function clamp that
   decides how many Granules a Worker may lease this round, given its
   self-reported capacity, the orchestrator's per-Worker cap, and any
   operator-set runtime override. Pure: testable without an AsyncSession.

2. **Lease acquisition / renewal / revocation** — async helpers that flow
   through `apply_transition` (ADR-0003) so every state change goes through
   the canonical Runner; renewal stays the documented bulk-UPDATE carve-out
   (ADR-0002) because it must remain race-safe against the sweeper.

3. **Worker-state introspection** — `count_worker_inflight` and
   `held_granule_sample` answer "what is this Worker still holding?" for
   both the quota path and operator-facing forget-worker flow.
"""

from __future__ import annotations

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

LEASE_DURATION = timedelta(minutes=30)


def compute_lease_quota(
    requested: int,
    *,
    current_inflight: int,
    max_inflight_per_worker: int,
    desired_capacity: int | None,
) -> int:
    """How many new Granules this Worker may lease this round.

    Pure: takes already-fetched state, returns the clamp. Three clamps:
      - Worker self-reports capacity (`requested`)
      - Orchestrator-wide cap minus what the Worker still holds
        (`max_inflight_per_worker - current_inflight`), 0 disables
      - Operator runtime override (`desired_capacity`, None means unset)
    Returns the minimum of the active clamps, never negative.
    """
    limit = requested
    if max_inflight_per_worker > 0:
        limit = min(limit, max(0, max_inflight_per_worker - current_inflight))
    if desired_capacity is not None:
        limit = min(limit, max(0, desired_capacity))
    return limit


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
    """Async wrapper: fetch the Worker's current inflight count, then ask
    `compute_lease_quota` for the policy answer. Kept as a thin adapter so
    the quota policy itself stays pure-function testable."""
    current_inflight = (
        await count_worker_inflight(s, req.worker_id) if settings.max_inflight_per_worker > 0 else 0
    )
    return compute_lease_quota(
        req.capacity,
        current_inflight=current_inflight,
        max_inflight_per_worker=settings.max_inflight_per_worker,
        desired_capacity=worker.desired_capacity,
    )


def lease_item(granule: Granule, batch: Batch | None) -> LeaseItem:
    return LeaseItem(
        granule_id=granule.granule_id,
        batch_id=granule.batch_id,
        bundle_ref=batch.bundle_ref if batch else "",
        inputs=granule.inputs,
        meta=granule.meta or {},
        execution_env=batch.execution_env if batch else {},
        credentials={
            k: Credential.model_validate(v) for k, v in (batch.credentials if batch else {}).items()
        },
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
