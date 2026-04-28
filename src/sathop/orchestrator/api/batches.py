"""Batch management endpoints: create, list, detail. Driven by Web UI."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import (
    IN_FLIGHT_STATES,
    BatchCreate,
    BatchSummary,
    GranuleBulkAdd,
    GranuleRow,
    GranuleState,
)

from ..bundle_schema import InputsSchema, parse_shared_files, validate_granule
from ..config import require_token, settings
from ..db import (
    Batch,
    Bundle,
    Event,
    Granule,
    GranuleObject,
    GranuleProgress,
    GranuleStageTiming,
    SharedFile,
    session,
    utcnow,
)
from ..pubsub import log_event as log
from ..pubsub import publish


def _parse_orch_ref(ref: str) -> tuple[str, str]:
    """Strict `orch:<name>@<version>` parser. Raises HTTPException on mismatch."""
    if not ref.startswith("orch:"):
        raise HTTPException(422, "bundle_ref must be in the form 'orch:<name>@<version>'")
    body = ref[len("orch:") :]
    if "@" not in body:
        raise HTTPException(422, "bundle_ref missing '@<version>'")
    name, version = body.rsplit("@", 1)
    if not name or not version:
        raise HTTPException(422, "bundle_ref name/version must both be non-empty")
    return name, version


router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_token)])


def _compose_gid(batch_id: str, user_gid: str) -> str:
    """Internal granule_id is `<batch_id>:<user_gid>` so user-supplied IDs only
    have to be unique within their batch. The prefix is the same `batch_id` PK
    that already enforces global uniqueness, so collisions are impossible
    across batches and the UI can strip it for display."""
    return f"{batch_id}:{user_gid}"


async def _counts(s: AsyncSession, batch_id: str) -> dict[str, int]:
    return (await _counts_bulk(s, [batch_id]))[batch_id]


async def _counts_bulk(s: AsyncSession, batch_ids: list[str]) -> dict[str, dict[str, int]]:
    if not batch_ids:
        return {}
    stmt = (
        select(Granule.batch_id, Granule.state, func.count(Granule.granule_id))
        .where(Granule.batch_id.in_(batch_ids))
        .group_by(Granule.batch_id, Granule.state)
    )
    out: dict[str, dict[str, int]] = {bid: {} for bid in batch_ids}
    for batch_id, state, n in (await s.execute(stmt)).all():
        out[batch_id][state] = n
    return out


async def _exhausted_objects(s: AsyncSession, batch_id: str) -> int:
    """Number of still-pending objects in the batch that hit the pull-failure
    cap — i.e., delivery has effectively given up. Mirrors the predicate in
    the receiver pull endpoint and the per-batch reset action."""
    return int(
        await s.scalar(
            select(func.count(GranuleObject.id))
            .join(Granule, GranuleObject.granule_id == Granule.granule_id)
            .where(Granule.batch_id == batch_id)
            .where(GranuleObject.acked_at.is_(None))
            .where(GranuleObject.deleted_at.is_(None))
            .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        )
        or 0
    )


async def _eta_seconds_bulk(
    s: AsyncSession,
    counts_map: dict[str, dict[str, int]],
) -> dict[str, int | None]:
    """ETA = remaining_in_flight * (wall_seconds / closed_upload_stages).
    None when sample <3 uploads, wall <=0, or no in-flight granules."""
    if not counts_map:
        return {}
    batch_ids = list(counts_map)
    rows = (
        await s.execute(
            select(
                GranuleStageTiming.batch_id,
                func.min(GranuleStageTiming.started_at),
                func.max(GranuleStageTiming.finished_at),
                func.sum(case((GranuleStageTiming.stage == "upload", 1), else_=0)),
            )
            .where(GranuleStageTiming.batch_id.in_(batch_ids))
            .group_by(GranuleStageTiming.batch_id)
        )
    ).all()

    out: dict[str, int | None] = dict.fromkeys(batch_ids, None)
    for batch_id, first, last, done in rows:
        done_n = int(done or 0)
        if done_n < 3 or first is None or last is None:
            continue
        wall_sec = (last - first).total_seconds()
        if wall_sec <= 0:
            continue
        remaining = sum(counts_map[batch_id].get(st, 0) for st in IN_FLIGHT_STATES)
        if remaining <= 0:
            continue
        out[batch_id] = int(remaining * wall_sec / done_n)
    return out


async def _exhausted_objects_bulk(s: AsyncSession, batch_ids: list[str]) -> dict[str, int]:
    """One grouped query for the batch list — keeps list_batches at O(1) DB
    round-trips instead of O(N)."""
    if not batch_ids:
        return {}
    stmt = (
        select(Granule.batch_id, func.count(GranuleObject.id))
        .join(Granule, GranuleObject.granule_id == Granule.granule_id)
        .where(Granule.batch_id.in_(batch_ids))
        .where(GranuleObject.acked_at.is_(None))
        .where(GranuleObject.deleted_at.is_(None))
        .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        .group_by(Granule.batch_id)
    )
    return dict((await s.execute(stmt)).all())


@router.post("", response_model=BatchSummary)
async def create(req: BatchCreate, s: AsyncSession = Depends(session)) -> BatchSummary:
    existing = await s.get(Batch, req.batch_id)
    if existing is not None:
        raise HTTPException(409, "batch_id already exists")

    name, version = _parse_orch_ref(req.bundle_ref)
    bundle = await s.get(Bundle, (name, version))
    if bundle is None:
        raise HTTPException(422, f"bundle {name}@{version} not registered — upload it to /api/bundles first")

    # Re-verify shared-file references at batch-create time too: a shared name
    # could have been deleted after the bundle was uploaded, and we want the
    # batch to fail fast rather than crash mid-lease.
    manifest = json.loads(bundle.manifest_json)
    shared_names = parse_shared_files(manifest)
    missing_shared = [n for n in shared_names if await s.get(SharedFile, n) is None]
    if missing_shared:
        raise HTTPException(
            422,
            f"bundle {name}@{version} references shared file(s) not in registry: {missing_shared}",
        )

    schema = InputsSchema.parse(manifest)
    seen: set[str] = set()
    dups: set[str] = set()
    all_errors: list[str] = []
    all_warnings: list[str] = []
    for g in req.granules:
        if g.granule_id in seen:
            dups.add(g.granule_id)
        seen.add(g.granule_id)
        r = validate_granule(schema, g.granule_id, [i.model_dump() for i in g.inputs], g.meta)
        all_errors.extend(r.errors)
        all_warnings.extend(r.warnings)
    if dups:
        raise HTTPException(422, f"duplicate granule_id(s) within batch: {sorted(dups)[:20]}")
    if all_errors:
        raise HTTPException(
            422,
            "granule schema validation failed:\n"
            + "\n".join(all_errors[:20])
            + (f"\n... ({len(all_errors) - 20} more)" if len(all_errors) > 20 else ""),
        )

    b = Batch(
        batch_id=req.batch_id,
        name=req.name,
        bundle_ref=req.bundle_ref,
        target_receiver_id=req.target_receiver_id,
        execution_env_json=json.dumps(req.execution_env, ensure_ascii=False),
        credentials_json=json.dumps(
            {k: c.model_dump() for k, c in req.credentials.items()}, ensure_ascii=False
        ),
    )
    s.add(b)

    for g in req.granules:
        s.add(
            Granule(
                granule_id=_compose_gid(req.batch_id, g.granule_id),
                batch_id=req.batch_id,
                state=GranuleState.PENDING.value,
                inputs_json=json.dumps([i.model_dump() for i in g.inputs]),
                meta_json=json.dumps(g.meta, ensure_ascii=False),
            )
        )
    await log(s, "orchestrator", f"created batch {req.batch_id} with {len(req.granules)} granules")
    for w in all_warnings[:20]:
        await log(s, "orchestrator", w, level="warn")
    await s.commit()
    publish({"scope": "batches"})

    return BatchSummary(
        batch_id=b.batch_id,
        name=b.name,
        bundle_ref=b.bundle_ref,
        target_receiver_id=b.target_receiver_id,
        status=b.status,
        created_at=b.created_at,
        counts=await _counts(s, b.batch_id),
        objects_exhausted=0,
        eta_seconds=None,
    )


@router.get("", response_model=list[BatchSummary])
async def list_batches(s: AsyncSession = Depends(session)) -> list[BatchSummary]:
    rows = (await s.execute(select(Batch).order_by(Batch.created_at.desc()))).scalars().all()
    ids = [b.batch_id for b in rows]
    counts_map = await _counts_bulk(s, ids)
    exh_map = await _exhausted_objects_bulk(s, ids)
    eta_map = await _eta_seconds_bulk(s, counts_map)
    return [
        BatchSummary(
            batch_id=b.batch_id,
            name=b.name,
            bundle_ref=b.bundle_ref,
            target_receiver_id=b.target_receiver_id,
            status=b.status,
            created_at=b.created_at,
            counts=counts_map[b.batch_id],
            objects_exhausted=exh_map.get(b.batch_id, 0),
            eta_seconds=eta_map.get(b.batch_id),
        )
        for b in rows
    ]


@router.get("/{batch_id}", response_model=BatchSummary)
async def detail(batch_id: str, s: AsyncSession = Depends(session)) -> BatchSummary:
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    counts = await _counts(s, batch_id)
    eta_map = await _eta_seconds_bulk(s, {batch_id: counts})
    return BatchSummary(
        batch_id=b.batch_id,
        name=b.name,
        bundle_ref=b.bundle_ref,
        target_receiver_id=b.target_receiver_id,
        status=b.status,
        created_at=b.created_at,
        counts=counts,
        objects_exhausted=await _exhausted_objects(s, batch_id),
        eta_seconds=eta_map.get(batch_id),
    )


@router.post("/{batch_id}/granules")
async def add_granules(batch_id: str, req: GranuleBulkAdd, s: AsyncSession = Depends(session)) -> dict:
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")

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
        s.add(
            Granule(
                granule_id=gid,
                batch_id=batch_id,
                state=GranuleState.PENDING.value,
                inputs_json=json.dumps([i.model_dump() for i in g.inputs]),
                meta_json=json.dumps(g.meta, ensure_ascii=False),
            )
        )
        added += 1
    await s.commit()
    if added:
        publish({"scope": "batches"})
    return {"added": added, "skipped": skipped}


@router.get("/{batch_id}/granules", response_model=list[GranuleRow])
async def list_granules(
    batch_id: str,
    state: str | None = Query(default=None, description="filter by state (repeatable via comma-separated)"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    s: AsyncSession = Depends(session),
) -> list[GranuleRow]:
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    stmt = select(Granule).where(Granule.batch_id == batch_id)
    if state:
        wanted = [x.strip() for x in state.split(",") if x.strip()]
        stmt = stmt.where(Granule.state.in_(wanted))
    stmt = stmt.order_by(Granule.updated_at.desc()).limit(limit).offset(offset)
    rows = (await s.execute(stmt)).scalars().all()

    # One grouped query for exhausted-object counts → avoid N+1. Only granules
    # that actually have any exhausted objects appear in the dict; others map
    # to the default 0 below.
    gids = [g.granule_id for g in rows]
    exh_map: dict[str, int] = {}
    if gids:
        exh_stmt = (
            select(GranuleObject.granule_id, func.count(GranuleObject.id))
            .where(GranuleObject.granule_id.in_(gids))
            .where(GranuleObject.acked_at.is_(None))
            .where(GranuleObject.deleted_at.is_(None))
            .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
            .group_by(GranuleObject.granule_id)
        )
        exh_map = dict((await s.execute(exh_stmt)).all())
    return [
        GranuleRow(
            granule_id=g.granule_id,
            batch_id=g.batch_id,
            state=g.state,
            retry_count=g.retry_count,
            leased_by=g.leased_by,
            error=g.error,
            updated_at=g.updated_at,
            objects_exhausted=exh_map.get(g.granule_id, 0),
        )
        for g in rows
    ]


@router.post("/{batch_id}/reset-exhausted-objects")
async def reset_exhausted_objects(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Zero `failed_pulls` on all of this batch's still-pending objects that
    hit the pull-failure cap. Use after fixing the upstream cause (worker
    restored, network healed). Already-acked or already-deleted objects are
    untouched."""
    if await s.get(Batch, batch_id) is None:
        raise HTTPException(404, "batch not found")
    granule_ids_subq = select(Granule.granule_id).where(Granule.batch_id == batch_id).scalar_subquery()
    result = await s.execute(
        update(GranuleObject)
        .where(GranuleObject.granule_id.in_(granule_ids_subq))
        .where(GranuleObject.acked_at.is_(None))
        .where(GranuleObject.deleted_at.is_(None))
        .where(func.coalesce(GranuleObject.failed_pulls, 0) >= settings.max_pull_failures)
        .values(failed_pulls=0)
    )
    reset = getattr(result, "rowcount", 0) or 0
    if reset:
        await log(s, "orchestrator", f"reset {reset} exhausted-pull objects in batch {batch_id}")
    await s.commit()
    if reset:
        publish({"scope": "batches"})
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
    for g in rows:
        g.state = GranuleState.PENDING.value
        g.retry_count = 0
        g.error = None
        g.updated_at = now
    await s.commit()
    if rows:
        publish({"scope": "batches"})
    return {"ok": True, "reset": len(rows)}


# States where "cancel" still makes sense — worker either hasn't started, or is
# mid-flight but the result hasn't entered the storage pipeline. After UPLOADED
# the data is already on worker storage (and soon on receiver), so cancel is
# a no-op operationally.
_CANCELLABLE = {
    GranuleState.PENDING.value,
    GranuleState.QUEUED.value,
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
}

# retry_count resets to 0 so the auto-blacklist counter starts fresh for the retry.
_RETRYABLE = {
    GranuleState.FAILED.value,
    GranuleState.BLACKLISTED.value,
}


async def _cancel_one(g: Granule, now) -> bool:
    if g.state not in _CANCELLABLE:
        return False
    g.state = GranuleState.BLACKLISTED.value
    g.leased_by = None
    g.lease_expires_at = None
    g.updated_at = now
    return True


async def _retry_one(g: Granule, now) -> bool:
    if g.state not in _RETRYABLE:
        return False
    g.state = GranuleState.PENDING.value
    g.retry_count = 0
    g.error = None
    g.leased_by = None
    g.lease_expires_at = None
    g.updated_at = now
    return True


@router.post("/{batch_id}/granules/{granule_id}/cancel")
async def cancel_granule(batch_id: str, granule_id: str, s: AsyncSession = Depends(session)) -> dict:
    g = await s.get(Granule, granule_id)
    if g is None or g.batch_id != batch_id:
        raise HTTPException(404, "granule not found in batch")
    if not await _cancel_one(g, utcnow()):
        raise HTTPException(409, f"cannot cancel granule in state {g.state!r}")
    await log(s, "admin", f"cancelled granule {granule_id}", level="warn", granule_id=granule_id)
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True, "state": g.state}


@router.post("/{batch_id}/granules/{granule_id}/retry")
async def retry_granule(batch_id: str, granule_id: str, s: AsyncSession = Depends(session)) -> dict:
    g = await s.get(Granule, granule_id)
    if g is None or g.batch_id != batch_id:
        raise HTTPException(404, "granule not found in batch")
    if not await _retry_one(g, utcnow()):
        raise HTTPException(409, f"cannot retry granule in state {g.state!r}")
    await log(s, "admin", f"retried granule {granule_id}", granule_id=granule_id)
    await s.commit()
    publish({"scope": "batches"})
    return {"ok": True, "state": g.state}


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: str, s: AsyncSession = Depends(session)) -> dict:
    """Bulk cancel: every granule in a cancellable state → blacklisted."""
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    now = utcnow()
    rows = (
        (
            await s.execute(
                select(Granule)
                .where(Granule.batch_id == batch_id)
                .where(Granule.state.in_(list(_CANCELLABLE)))
            )
        )
        .scalars()
        .all()
    )
    for g in rows:
        await _cancel_one(g, now)
    if rows:
        await log(s, "admin", f"cancelled batch {batch_id}: {len(rows)} granules blacklisted", level="warn")
    await s.commit()
    if rows:
        publish({"scope": "batches"})
    return {"ok": True, "cancelled": len(rows)}


# Worker actively holds these on lease; deleting under them produces 404s on
# the next state report and orphans staged inputs. Cancel first, or pass
# `?force=true` to override.
_INFLIGHT_FOR_DELETE = (
    GranuleState.QUEUED.value,
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
)


@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: str,
    force: bool = Query(False, description="delete even if granules are mid-flight"),
    s: AsyncSession = Depends(session),
) -> dict:
    """Hard-delete a batch and every row that references it (granules,
    objects, progress checkpoints, stage timings, scoped events).

    Refuses by default if any granule is mid-flight on a worker — cancel the
    batch first so the worker drops the lease cleanly, or pass `?force=true`
    to delete anyway (workers will get 404s on their next state report).

    Already-uploaded objects on worker storage are not cleaned up here; the
    operator drops them via the worker's own retention or by hand. This
    endpoint only removes orchestrator state."""
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")

    if not force:
        active = (
            await s.execute(
                select(func.count(Granule.granule_id))
                .where(Granule.batch_id == batch_id)
                .where(Granule.state.in_(_INFLIGHT_FOR_DELETE))
            )
        ).scalar_one()
        if active:
            raise HTTPException(
                409,
                f"{active} granules are mid-flight on workers; cancel the batch first or pass ?force=true",
            )

    granule_ids = (
        (await s.execute(select(Granule.granule_id).where(Granule.batch_id == batch_id))).scalars().all()
    )

    counts = {"granules": 0, "objects": 0, "progress": 0, "stage_timings": 0, "events": 0}
    if granule_ids:
        # Children before parent to keep FK refs consistent (SQLite doesn't
        # enforce them, but the retention sweeper relies on the same order).
        for table, key in (
            (GranuleObject, "objects"),
            (GranuleProgress, "progress"),
            (GranuleStageTiming, "stage_timings"),
            (Event, "events"),
        ):
            r = await s.execute(delete(table).where(table.granule_id.in_(granule_ids)))
            counts[key] = getattr(r, "rowcount", 0) or 0
        r = await s.execute(delete(Granule).where(Granule.batch_id == batch_id))
        counts["granules"] = getattr(r, "rowcount", 0) or 0

    await s.delete(b)
    await log(
        s,
        "admin",
        f"deleted batch {batch_id} (force={force}, {counts})",
        level="warn",
    )
    await s.commit()
    publish({"scope": "batches"})
    if counts["events"]:
        publish({"scope": "events"})
    return {"ok": True, **counts}
