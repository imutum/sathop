"""Batch management endpoints: create, list, detail. Driven by Web UI."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import BatchCreate, BatchSummary, GranuleBulkAdd, GranuleRow, GranuleState

from ..bundle_schema import InputsSchema, parse_shared_files, validate_granule
from ..config import require_token
from ..db import Batch, Bundle, Granule, SharedFile, session, utcnow
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


async def _counts(s: AsyncSession, batch_id: str) -> dict[str, int]:
    stmt = (
        select(Granule.state, func.count(Granule.granule_id))
        .where(Granule.batch_id == batch_id)
        .group_by(Granule.state)
    )
    rows = (await s.execute(stmt)).all()
    return {state: n for state, n in rows}


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
    all_errors: list[str] = []
    all_warnings: list[str] = []
    for g in req.granules:
        r = validate_granule(schema, g.granule_id, [i.model_dump() for i in g.inputs], g.meta)
        all_errors.extend(r.errors)
        all_warnings.extend(r.warnings)
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
                granule_id=g.granule_id,
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
    )


@router.get("", response_model=list[BatchSummary])
async def list_batches(s: AsyncSession = Depends(session)) -> list[BatchSummary]:
    rows = (await s.execute(select(Batch).order_by(Batch.created_at.desc()))).scalars().all()
    out: list[BatchSummary] = []
    for b in rows:
        out.append(
            BatchSummary(
                batch_id=b.batch_id,
                name=b.name,
                bundle_ref=b.bundle_ref,
                target_receiver_id=b.target_receiver_id,
                status=b.status,
                created_at=b.created_at,
                counts=await _counts(s, b.batch_id),
            )
        )
    return out


@router.get("/{batch_id}", response_model=BatchSummary)
async def detail(batch_id: str, s: AsyncSession = Depends(session)) -> BatchSummary:
    b = await s.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    return BatchSummary(
        batch_id=b.batch_id,
        name=b.name,
        bundle_ref=b.bundle_ref,
        target_receiver_id=b.target_receiver_id,
        status=b.status,
        created_at=b.created_at,
        counts=await _counts(s, b.batch_id),
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
        if g.granule_id in existing:
            skipped += 1
            continue
        s.add(
            Granule(
                granule_id=g.granule_id,
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
    return [
        GranuleRow(
            granule_id=g.granule_id,
            batch_id=g.batch_id,
            state=g.state,
            retry_count=g.retry_count,
            leased_by=g.leased_by,
            error=g.error,
            updated_at=g.updated_at,
        )
        for g in rows
    ]


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
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
}

# retry_count resets to 0 so auto-blacklist-after-3 starts fresh for the retry.
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
