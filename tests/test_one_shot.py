from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.one_shot import consume_one_shot_signal
from sathop.orchestrator.db import Event


@dataclass
class Owner:
    requested_at: datetime | None = None


@pytest.fixture
async def db(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        async with orch_db._session_maker() as s:
            yield s
    finally:
        await orch_db.shutdown_db()


async def test_consume_one_shot_signal_noops_when_absent(db):
    owner = Owner()

    def clear() -> None:
        owner.requested_at = None

    assert (
        await consume_one_shot_signal(
            db,
            owner.requested_at is not None,
            clear,
            source="w1",
            message="delivered",
        )
        is False
    )
    assert owner.requested_at is None


async def test_consume_one_shot_signal_clears_flag_and_logs(db):
    owner = Owner(datetime.now(UTC))

    def clear() -> None:
        owner.requested_at = None

    assert (
        await consume_one_shot_signal(
            db,
            owner.requested_at is not None,
            clear,
            source="w1",
            message="delivered",
        )
        is True
    )
    assert owner.requested_at is None
    [event] = (await db.execute(select(Event))).scalars().all()
    assert event.source == "w1"
    assert event.message == "delivered"
