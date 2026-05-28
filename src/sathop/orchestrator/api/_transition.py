"""Handler-layer Transition applier.

Wraps the dance every state-changing endpoint repeats: snapshot → apply →
StateConflict policy → materialise to session. Does not commit or publish —
handlers retain transaction control so event-log rows stay atomic with the
transition (see ADR-0003).

The Runner (snapshot/materialise) lives here as private helpers rather than in
a separate _runner.py — they are inseparable from apply_transition and don't
constitute an independent module."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal, overload

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import (
    AnyGranuleEvent,
    GranuleSnapshot,
    GranuleState,
    StateConflict,
    TransitionResult,
)
from sathop.shared.state_machine import (
    apply as apply_event,
)

from ..config import settings
from ..db import Granule, GranuleObject, GranuleStageTiming


def _snapshot_of(granule: Granule) -> GranuleSnapshot:
    return GranuleSnapshot(
        state=GranuleState(granule.state),
        updated_at=granule.updated_at,
        retry_count=granule.retry_count or 0,
    )


async def _apply_to_session(s: AsyncSession, granule: Granule, result: TransitionResult) -> None:
    granule.state = result.new_state.value
    for obj in result.new_objects:
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


@overload
async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: AnyGranuleEvent,
    *,
    now: datetime,
    on_conflict: Literal["raise_409"] = "raise_409",
    conflict_message: Callable[[Granule, StateConflict], str] | None = None,
) -> TransitionResult: ...


@overload
async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: AnyGranuleEvent,
    *,
    now: datetime,
    on_conflict: Literal["skip"],
    conflict_message: Callable[[Granule, StateConflict], str] | None = None,
) -> TransitionResult | None: ...


async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: AnyGranuleEvent,
    *,
    now: datetime,
    on_conflict: Literal["raise_409", "skip"] = "raise_409",
    conflict_message: Callable[[Granule, StateConflict], str] | None = None,
) -> TransitionResult | None:
    """Apply one GranuleEvent to `granule` on `s`.

    Returns the `TransitionResult` so the caller can read `publish_scope` for
    its own `commit_and_publish` call. Returns `None` only when
    `on_conflict="skip"` and the event hit a `StateConflict` — bulk loops and
    `receivers.ack` rely on this branch.
    """
    try:
        result = apply_event(
            _snapshot_of(granule),
            event,
            now=now,
            max_retries=settings.max_retries,
        )
    except StateConflict as e:
        if on_conflict == "skip":
            return None
        msg = conflict_message(granule, e) if conflict_message else str(e)
        raise HTTPException(409, msg) from e
    await _apply_to_session(s, granule, result)
    return result
