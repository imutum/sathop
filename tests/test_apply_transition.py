"""Unit tests for the handler-layer Transition applier."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api._transition import apply_transition
from sathop.orchestrator.db import Batch, Granule, utcnow
from sathop.shared.state_machine import (
    CancelGranule,
    DownloadStarted,
    GranuleState,
)


@pytest.fixture
async def session(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "t.db", token="", max_retries=3)
    await orch_db.init_db()
    try:
        async with orch_db._session_maker() as s:
            s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
            s.add(
                Granule(
                    granule_id="g1",
                    batch_id="b",
                    state=GranuleState.QUEUED.value,
                    inputs_json="[]",
                    leased_by="w1",
                    lease_expires_at=utcnow(),
                )
            )
            await s.commit()
        async with orch_db._session_maker() as s:
            yield s
    finally:
        await orch_db.shutdown_db()


async def test_success_applies_to_session(session):
    g = await session.get(Granule, "g1")
    result = await apply_transition(
        session,
        g,
        DownloadStarted(granule_id="g1", worker_id="w1"),
        now=utcnow(),
    )
    assert result is not None
    assert result.new_state == GranuleState.DOWNLOADING
    assert g.state == GranuleState.DOWNLOADING.value


async def test_state_conflict_raises_409_with_default_message(session):
    g = await session.get(Granule, "g1")
    g.state = GranuleState.UPLOADED.value
    with pytest.raises(HTTPException) as exc:
        await apply_transition(
            session,
            g,
            DownloadStarted(granule_id="g1", worker_id="w1"),
            now=utcnow(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail  # str(StateConflict) is non-empty


async def test_state_conflict_uses_conflict_message_callback(session):
    g = await session.get(Granule, "g1")
    g.state = GranuleState.UPLOADED.value
    seen: list[tuple[str, str]] = []

    def msg(granule, conflict):
        seen.append((granule.state, type(conflict).__name__))
        return f"cannot in state {granule.state!r}"

    with pytest.raises(HTTPException) as exc:
        await apply_transition(
            session,
            g,
            CancelGranule(granule_id="g1"),
            now=utcnow(),
            conflict_message=msg,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "cannot in state 'uploaded'"
    assert seen == [("uploaded", "StateConflict")]


async def test_state_conflict_skip_returns_none(session):
    g = await session.get(Granule, "g1")
    g.state = GranuleState.UPLOADED.value
    result = await apply_transition(
        session,
        g,
        DownloadStarted(granule_id="g1", worker_id="w1"),
        now=utcnow(),
        on_conflict="skip",
    )
    assert result is None
    assert g.state == GranuleState.UPLOADED.value
