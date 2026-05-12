"""Worker-reported granule state transitions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import ProcessFailure, StateUpdate, UploadReport
from sathop.shared.state_machine import STAGE_BY_CLOSER, GranuleState

from ..config import settings
from ..db import Granule, GranuleObject, GranuleStageTiming


def record_stage(s: AsyncSession, granule: Granule, stage: str, started_at, finished_at) -> None:
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    s.add(
        GranuleStageTiming(
            granule_id=granule.granule_id,
            batch_id=granule.batch_id,
            stage=stage,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
    )


def apply_state_report(s: AsyncSession, granule: Granule, req: StateUpdate, now) -> None:
    prev_at = granule.updated_at
    granule.state = req.state.value
    granule.updated_at = now
    stage = STAGE_BY_CLOSER.get(req.state.value)
    if stage is not None:
        record_stage(s, granule, stage, prev_at, now)


def mark_uploaded(s: AsyncSession, granule: Granule, req: UploadReport, now) -> None:
    for obj in req.objects:
        s.add(
            GranuleObject(
                granule_id=granule.granule_id,
                worker_id=req.worker_id,
                object_key=obj.object_key,
                presigned_url=obj.presigned_url,
                sha256=obj.sha256,
                size=obj.size,
            )
        )
    prev_at = granule.updated_at
    granule.state = GranuleState.UPLOADED.value
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.error = None
    granule.stdout_tail = None
    granule.stderr_tail = None
    granule.updated_at = now
    started = req.upload_started_at
    if started is not None and prev_at <= started <= now:
        record_stage(s, granule, "upload_wait", prev_at, started)
        record_stage(s, granule, "upload", started, now)
    else:
        record_stage(s, granule, "upload", prev_at, now)


def mark_failed(granule: Granule, req: ProcessFailure, now) -> None:
    granule.retry_count += 1
    granule.error = req.error[:2000]
    if req.stdout_tail is not None:
        granule.stdout_tail = req.stdout_tail[:16000]
    if req.stderr_tail is not None:
        granule.stderr_tail = req.stderr_tail[:16000]
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.state = (
        GranuleState.BLACKLISTED.value
        if granule.retry_count >= settings.max_retries
        else GranuleState.PENDING.value
    )
    granule.updated_at = now
