"""Batch management endpoints: create, list, detail. Driven by Web UI."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.bundle_manifest import InputsSchema, parse_shared_files
from sathop.shared.bundle_ref import parse_bundle_ref
from sathop.shared.protocol import (
    BatchCreate,
    BatchSummary,
    GranuleBulkAdd,
    GranuleCreate,
    GranuleRow,
)
from sathop.shared.state_machine import (
    CANCELLABLE_STATES,
    LEASED_STATES,
    CancelGranule,
    GranuleState,
    RetryGranule,
    Scope,
)

from .. import db, event_store
from ..bundle_schema import validate_granule
from ..config import require_token
from ..db import (
    Batch,
    Bundle,
    Granule,
    GranuleObject,
    SharedFile,
    session,
    utcnow,
)
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from ..reaping import reap_granules
from ._helpers import get_or_404, object_is_exhausted
from ._transition import apply_transition
from .batch_readmodels import (
    granule_rows,
    state_counts,
    summaries,
    summary,
    summary_just_created,
)
from .progress import evict_granule, evict_granules

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_token)])


def _compose_gid(batch_id: str, user_gid: str) -> str:
    """Internal granule_id is `<batch_id>:<user_gid>` so user-supplied IDs only
    have to be unique within their batch. The prefix is the same `batch_id` PK
    that already enforces global uniqueness, so collisions are impossible
    across batches and the UI can strip it for display."""
    return f"{batch_id}:{user_gid}"


async def _granule_in_batch_or_404(s: AsyncSession, batch_id: str, granule_id: str) -> Granule:
    granule = await get_or_404(s, Granule, granule_id, "granule not found in batch")
    if granule.batch_id != batch_id:
        raise HTTPException(404, "granule not found in batch")
    return granule


def _new_granule(batch_id: str, granule: GranuleCreate) -> Granule:
    return Granule(
        granule_id=_compose_gid(batch_id, granule.granule_id),
        batch_id=batch_id,
        state=GranuleState.PENDING.value,
        inputs=[i.model_dump() for i in granule.inputs],
        meta=granule.meta,
    )


async def _validate_granules_for_bundle(
    s: AsyncSession,
    bundle_ref: str,
    granules: list[GranuleCreate],
) -> list[str]:
    """Validate each granule against its bundle's input schema; refuse on
    duplicates or schema errors. Returns warnings (non-blocking, caller
    logs them). Used by both `create` and `add_granules` so they reject
    bad granules identically."""
    name, version = parse_bundle_ref(bundle_ref)
    bundle = await s.get(Bundle, (name, version))
    if bundle is None:
        raise HTTPException(422, f"bundle {name}@{version} not registered")
    schema = InputsSchema.parse(bundle.manifest)
    seen: set[str] = set()
    dups: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []
    for g in granules:
        if g.granule_id in seen:
            dups.add(g.granule_id)
        seen.add(g.granule_id)
        r = validate_granule(schema, g.granule_id, [i.model_dump() for i in g.inputs], g.meta)
        errors.extend(r.errors)
        warnings.extend(r.warnings)
    if dups:
        raise HTTPException(422, f"duplicate granule_id(s) within batch: {sorted(dups)[:20]}")
    if errors:
        raise HTTPException(
            422,
            "granule schema validation failed:\n"
            + "\n".join(errors[:20])
            + (f"\n... ({len(errors) - 20} more)" if len(errors) > 20 else ""),
        )
    return warnings


async def _batch_granule_ids(s: AsyncSession, batch_id: str) -> list[str]:
    return list(
        (await s.execute(select(Granule.granule_id).where(Granule.batch_id == batch_id))).scalars().all()
    )


@router.post("", response_model=BatchSummary)
async def create(req: BatchCreate, s: AsyncSession = Depends(session)) -> BatchSummary:
    # 客户端没指定 ID ⇒ 生成 8 字符 URL-safe 随机串。secrets.token_urlsafe(6)
    # 给 6 字节随机熵 ≈ 281T 组合，重试 10 次即可在百万级批次量下保证唯一。
    if req.batch_id is None:
        for _ in range(10):
            candidate = secrets.token_urlsafe(6)
            if await s.get(Batch, candidate) is None:
                batch_id = candidate
                break
        else:
            raise HTTPException(500, "failed to generate unique batch_id")
    else:
        if await s.get(Batch, req.batch_id) is not None:
            raise HTTPException(409, "batch_id already exists")
        batch_id = req.batch_id

    # Re-verify shared-file references at batch-create time too: a shared
    # name could have been deleted after the bundle was uploaded, and we
    # want the batch to fail fast rather than crash mid-lease.
    try:
        name, version = parse_bundle_ref(req.bundle_ref)
    except ValueError as e:
        raise HTTPException(422, str(e))
    bundle = await s.get(Bundle, (name, version))
    if bundle is None:
        raise HTTPException(422, f"bundle {name}@{version} not registered — upload it to /api/bundles first")
    missing_shared = [n for n in parse_shared_files(bundle.manifest) if await s.get(SharedFile, n) is None]
    if missing_shared:
        raise HTTPException(
            422,
            f"bundle {name}@{version} references shared file(s) not in registry: {missing_shared}",
        )

    warnings = await _validate_granules_for_bundle(s, req.bundle_ref, req.granules)

    b = Batch(
        batch_id=batch_id,
        name=req.name,
        bundle_ref=req.bundle_ref,
        target_receiver_id=req.target_receiver_id,
        execution_env=req.execution_env,
        credentials={k: c.model_dump() for k, c in req.credentials.items()},
    )
    s.add(b)

    for g in req.granules:
        s.add(_new_granule(batch_id, g))
    await log(s, "orchestrator", f"created batch {batch_id} with {len(req.granules)} granules")
    for w in warnings[:20]:
        await log(s, "orchestrator", w, level="warn")
    await commit_and_publish(s, Scope.BATCHES)

    counts = (await state_counts(s, [b.batch_id])).get(b.batch_id, {})
    return summary_just_created(b, counts=counts)


@router.get("", response_model=list[BatchSummary])
async def list_batches(s: AsyncSession = Depends(session)) -> list[BatchSummary]:
    rows = (await s.execute(select(Batch).order_by(Batch.created_at.desc()))).scalars().all()
    return await summaries(s, list(rows))


@router.get("/{batch_id}", response_model=BatchSummary)
async def detail(batch_id: str, s: AsyncSession = Depends(session)) -> BatchSummary:
    b = await get_or_404(s, Batch, batch_id, "batch not found")
    return await summary(s, b)


@router.post("/{batch_id}/granules")
async def add_granules(batch_id: str, req: GranuleBulkAdd, s: AsyncSession = Depends(session)) -> dict:
    batch = await get_or_404(s, Batch, batch_id, "batch not found")
    warnings = await _validate_granules_for_bundle(s, batch.bundle_ref, req.granules)

    existing = set(
        (await s.execute(select(Granule.granule_id).where(Granule.batch_id == batch_id))).scalars().all()
    )

    added = 0
    skipped = 0
    for g in req.granules:
        gid = _compose_gid(batch_id, g.granule_id)
        if gid in existing:
            skipped += 1
            continue
        s.add(_new_granule(batch_id, g))
        added += 1
    for w in warnings[:20]:
        await log(s, "orchestrator", w, level="warn")
    await commit_and_publish(s, Scope.BATCHES if added else None)
    return {"added": added, "skipped": skipped}


@router.get("/{batch_id}/granules", response_model=list[GranuleRow])
async def list_granules(
    batch_id: str,
    state: str | None = Query(default=None, description="filter by state (repeatable via comma-separated)"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    s: AsyncSession = Depends(session),
) -> list[GranuleRow]:
    await get_or_404(s, Batch, batch_id, "batch not found")
    stmt = select(Granule).where(Granule.batch_id == batch_id)
    if state:
        wanted = [x.strip() for x in state.split(",") if x.strip()]
        stmt = stmt.where(Granule.state.in_(wanted))
    stmt = stmt.order_by(Granule.updated_at.desc()).limit(limit).offset(offset)
    rows = (await s.execute(stmt)).scalars().all()
    return await granule_rows(s, list(rows))


@router.post("/{batch_id}/reset-exhausted-objects")
async def reset_exhausted_objects(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Zero `failed_pulls` on all of this batch's still-pending objects that
    hit the pull-failure cap. Use after fixing the upstream cause (worker
    restored, network healed). Already-acked or already-deleted objects are
    untouched."""
    await get_or_404(s, Batch, batch_id, "batch not found")
    granule_ids_subq = select(Granule.granule_id).where(Granule.batch_id == batch_id).scalar_subquery()
    result = await s.execute(
        update(GranuleObject)
        .where(GranuleObject.granule_id.in_(granule_ids_subq))
        .where(object_is_exhausted())
        .values(failed_pulls=0)
    )
    reset = getattr(result, "rowcount", 0) or 0
    if reset:
        await log(s, "orchestrator", f"reset {reset} exhausted-pull objects in batch {batch_id}")
    await commit_and_publish(s, Scope.BATCHES if reset else None)
    return {"ok": True, "reset": reset}


@router.post("/{batch_id}/retry-failed")
async def retry_failed(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    now = utcnow()
    stmt = (
        select(Granule)
        .where(Granule.batch_id == batch_id)
        .where(Granule.state.in_([GranuleState.FAILED.value, GranuleState.BLACKLISTED.value]))
    )
    rows = (await s.execute(stmt)).scalars().all()
    for granule in rows:
        await apply_transition(
            s,
            granule,
            RetryGranule(granule_id=granule.granule_id),
            now=now,
            on_conflict="skip",
        )
    await commit_and_publish(s, Scope.BATCHES if rows else None)
    return {"ok": True, "reset": len(rows)}


@router.post("/{batch_id}/granules/{granule_id}/cancel")
async def cancel_granule(batch_id: str, granule_id: str, s: AsyncSession = Depends(session)) -> dict:
    g = await _granule_in_batch_or_404(s, batch_id, granule_id)
    await apply_transition(
        s,
        g,
        CancelGranule(granule_id=granule_id),
        now=utcnow(),
        conflict_message=lambda g, _e: f"cannot cancel granule in state {g.state!r}",
    )
    evict_granule(granule_id)
    await log(
        s, "admin", f"cancelled granule {granule_id}", level="warn", granule_id=granule_id, batch_id=batch_id
    )
    await commit_and_publish(s, Scope.BATCHES)
    return {"ok": True, "state": g.state}


@router.post("/{batch_id}/granules/{granule_id}/retry")
async def retry_granule(batch_id: str, granule_id: str, s: AsyncSession = Depends(session)) -> dict:
    g = await _granule_in_batch_or_404(s, batch_id, granule_id)
    await apply_transition(
        s,
        g,
        RetryGranule(granule_id=granule_id),
        now=utcnow(),
        conflict_message=lambda g, _e: f"cannot retry granule in state {g.state!r}",
    )
    await log(s, "admin", f"retried granule {granule_id}", granule_id=granule_id, batch_id=batch_id)
    await commit_and_publish(s, Scope.BATCHES)
    return {"ok": True, "state": g.state}


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Bulk cancel: every granule in a cancellable state → blacklisted."""
    await get_or_404(s, Batch, batch_id, "batch not found")
    now = utcnow()
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.batch_id == batch_id)
                .where(Granule.state.in_(list(CANCELLABLE_STATES)))
            )
        )
        .scalars()
        .all()
    )
    for g in rows:
        await apply_transition(
            s,
            g,
            CancelGranule(granule_id=g.granule_id),
            now=now,
            on_conflict="skip",
        )
        evict_granule(g.granule_id)
    if rows:
        await log(s, "admin", f"cancelled batch {batch_id}: {len(rows)} granules blacklisted", level="warn")
    await commit_and_publish(s, Scope.BATCHES if rows else None)
    return {"ok": True, "cancelled": len(rows)}


@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: str,
    force: bool = Query(False, description="delete even if granules are mid-flight"),
    s: AsyncSession = Depends(session),
) -> dict:
    """Hard-delete a batch and every row that references it (granules,
    objects, stage timings, scoped events).

    Refuses by default if any granule is mid-flight on a worker — cancel the
    batch first so the worker drops the lease cleanly, or pass `?force=true`
    to delete anyway (workers will get 404s on their next state report).

    Already-uploaded objects on worker storage are not cleaned up here; the
    operator drops them via the worker's own retention or by hand. This
    endpoint only removes orchestrator state."""
    b = await get_or_404(s, Batch, batch_id, "batch not found")

    if not force:
        active = (
            await s.execute(
                select(func.count(Granule.granule_id))
                .where(Granule.batch_id == batch_id)
                .where(Granule.state.in_(LEASED_STATES))
            )
        ).scalar_one()
        if active:
            raise HTTPException(
                409,
                f"{active} granules are mid-flight on workers; cancel the batch first or pass ?force=true",
            )

    granule_ids = await _batch_granule_ids(s, batch_id)

    counts = await reap_granules(s, granule_ids)
    counts["events"] = 0
    # PG: drop this batch's events in the same txn as the reap (Event has no FK to
    # granules, so order is free). SQLite: the in-memory deque is swept post-commit.
    if granule_ids and db.is_postgres():
        counts["events"] = await event_store.evict_by_granule_ids_db(s, set(granule_ids))

    await s.delete(b)
    await log(
        s,
        "admin",
        f"deleted batch {batch_id} (force={force}, {counts})",
        level="warn",
    )
    await commit_and_publish(s, Scope.BATCHES)
    if granule_ids and not db.is_postgres():
        counts["events"] = event_store.evict_by_granule_ids(set(granule_ids))
    if granule_ids:
        evict_granules(granule_ids)
    return {"ok": True, **counts}
