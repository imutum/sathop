"""Lease lifecycle for the Worker scope.

Three concerns live here:

1. **Quota policy** (`compute_lease_quota`) — the pure-function clamp that
   decides how many Granules a Worker may lease this round, given its
   self-reported capacity and the orchestrator's per-Worker cap. Pure:
   testable without an AsyncSession.

2. **Lease acquisition / renewal / revocation** — async helpers that flow
   through `apply_transition` (ADR-0003) so every state change goes through
   the canonical Runner; renewal stays the documented bulk-UPDATE carve-out
   (ADR-0002) because it must remain race-safe against the sweeper.

3. **Worker-state introspection** — `count_worker_inflight` answers
   "how many granules is this Worker still holding?" for the quota path.
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
from ..db import Batch, Granule, GranuleObject
from ._transition import apply_transition
from .progress import evict_granule

LEASE_DURATION = timedelta(minutes=30)


def compute_lease_quota(
    requested: int,
    *,
    current_inflight: int,
    max_inflight_per_worker: int,
) -> int:
    """How many new Granules this Worker may lease this round.

    Pure: takes already-fetched state, returns the clamp. Two clamps:
      - Worker self-reports capacity (`requested`)
      - Orchestrator-wide cap minus what the Worker still holds
        (`max_inflight_per_worker - current_inflight`), 0 disables
    Returns the minimum of the active clamps, never negative.
    """
    limit = requested
    if max_inflight_per_worker > 0:
        limit = min(limit, max(0, max_inflight_per_worker - current_inflight))
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


async def lease_limit(s: AsyncSession, req: LeaseRequest) -> int:
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


async def renew_worker_leases(s: AsyncSession, worker_id: str, now) -> int:
    result = await s.execute(
        update(Granule)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
        .where(Granule.lease_expires_at < now + LEASE_DURATION / 2)
        .values(lease_expires_at=now + LEASE_DURATION)
    )
    return getattr(result, "rowcount", 0) or 0


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
        evict_granule(granule.granule_id)
    return len(rows)


async def reclaim_inactive_leases(
    s: AsyncSession,
    worker_id: str,
    active_ids: list[str],
    now,
    grace_sec: int = 60,
) -> int:
    """Reclaim leases the orchestrator still pins to `worker_id` that the worker's
    reported active set no longer covers — orphans from an orchestrator restart:
    a state event was swallowed during the restart window, the worker hit a 409 on
    the next event and dropped the granule (LeaseRevoked), but the orch kept the
    lease and the heartbeat renewed it forever, wedging the granule with no worker
    behind it. The grace window on `updated_at` protects a just-leased granule the
    worker hasn't started reporting in `active_ids` yet (a granule it is actually
    tracking — even blocked on a semaphore — is already in the set).

    An orphaned lease is effectively an expired one, so reclaim it like the sweeper:
    straight back to PENDING with NO retry_count bump (unlike operator revoke). The
    granule didn't fail — penalising its retry budget would let repeated orch
    restarts silently blacklist healthy work."""
    sel = (
        select(Granule.granule_id)
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
        .where(Granule.updated_at < now - timedelta(seconds=grace_sec))
    )
    if active_ids:
        sel = sel.where(Granule.granule_id.not_in(active_ids))
    ids = (await s.execute(sel)).scalars().all()
    if not ids:
        return 0
    # Re-assert the predicate at write time (sweeper carve-out, ADR-0002) so a
    # granule a concurrent event advanced between SELECT and UPDATE is left alone.
    result = await s.execute(
        update(Granule)
        .where(Granule.granule_id.in_(ids))
        .where(Granule.leased_by == worker_id)
        .where(Granule.state.in_(LEASED_STATES))
        .values(state=GranuleState.PENDING.value, leased_by=None, lease_expires_at=None, updated_at=now)
    )
    for gid in ids:
        evict_granule(gid)
    return getattr(result, "rowcount", 0) or 0
