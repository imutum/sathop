"""Handler-layer Transition applier.

Wraps the dance every state-changing endpoint repeats: snapshot_of → apply →
StateConflict policy → Runner. Does not commit or publish — handlers retain
transaction control so event-log rows stay atomic with the transition (see
ADR-0003)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal, overload

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import (
    GranuleEvent,
    StateConflict,
    TransitionResult,
)
from sathop.shared.state_machine import (
    apply as apply_event,
)

from ..config import settings
from ..db import Granule
from ._runner import apply_to_session, snapshot_of


@overload
async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: GranuleEvent,
    *,
    now: datetime,
    on_conflict: Literal["raise_409"] = "raise_409",
    conflict_message: Callable[[Granule, StateConflict], str] | None = None,
) -> TransitionResult: ...


@overload
async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: GranuleEvent,
    *,
    now: datetime,
    on_conflict: Literal["skip"],
    conflict_message: Callable[[Granule, StateConflict], str] | None = None,
) -> TransitionResult | None: ...


async def apply_transition(
    s: AsyncSession,
    granule: Granule,
    event: GranuleEvent,
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
            snapshot_of(granule),
            event,
            now=now,
            max_retries=settings.max_retries,
        )
    except StateConflict as e:
        if on_conflict == "skip":
            return None
        msg = conflict_message(granule, e) if conflict_message else str(e)
        raise HTTPException(409, msg) from e
    await apply_to_session(s, granule, result)
    return result
