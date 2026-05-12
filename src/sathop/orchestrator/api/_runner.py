"""Adapter that materialises a TransitionResult onto an AsyncSession.

The state machine (`shared/state_machine.py`) is pure — it produces a value
describing the DB changes a transition implies. This runner is the single seam
where that value meets SQLAlchemy. Keep it small."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import (
    GranuleSnapshot,
    GranuleState,
    TransitionResult,
)

from ..db import Granule, GranuleObject, GranuleStageTiming


def snapshot_of(granule: Granule) -> GranuleSnapshot:
    return GranuleSnapshot(
        state=GranuleState(granule.state),
        updated_at=granule.updated_at,
        retry_count=granule.retry_count or 0,
    )


async def apply_to_session(s: AsyncSession, granule: Granule, result: TransitionResult) -> None:
    granule.state = result.new_state.value
    for obj in result.new_objects:
        # Insert before the field updates run — UploadCompleted clears
        # `leased_by`, but the new GranuleObject rows still need the
        # originating worker id captured on the event.
        s.add(
            GranuleObject(
                granule_id=granule.granule_id,
                worker_id=obj.worker_id,
                object_key=obj.object_key,
                presigned_url=obj.presigned_url,
                sha256=obj.sha256,
                size=obj.size,
            )
        )
    for key, value in result.fields.items():
        setattr(granule, key, value)
    for row in result.stage_rows:
        duration_ms = max(0, int((row.finished_at - row.started_at).total_seconds() * 1000))
        s.add(
            GranuleStageTiming(
                granule_id=granule.granule_id,
                batch_id=granule.batch_id,
                stage=row.stage,
                started_at=row.started_at,
                finished_at=row.finished_at,
                duration_ms=duration_ms,
            )
        )
    if result.objects_deleted_at is not None:
        await s.execute(
            update(GranuleObject)
            .where(GranuleObject.granule_id == granule.granule_id)
            .values(deleted_at=result.objects_deleted_at)
        )
