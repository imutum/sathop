from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store
from sathop.orchestrator.api.one_shot import consume_one_shot_signal, record_version_flap
from sathop.orchestrator.pubsub import publish_scopes


@dataclass
class Owner:
    requested_at: datetime | None = None


@dataclass
class Versioned:
    version: str = "0.0.0"


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
    assert await consume_one_shot_signal(db, owner, "requested_at", source="w1", message="delivered") is False
    assert owner.requested_at is None


async def test_consume_one_shot_signal_clears_flag_and_logs(db):
    owner = Owner(datetime.now(UTC))
    assert await consume_one_shot_signal(db, owner, "requested_at", source="w1", message="delivered") is True
    assert owner.requested_at is None
    publish_scopes(db)  # flush staged events to event_store
    events = event_store.query(limit=100)
    assert len(events) == 1
    assert events[0]["source"] == "w1"
    assert events[0]["message"] == "delivered"


async def test_record_version_flap_noop_on_match(db):
    v = Versioned(version="1.0.0")
    await record_version_flap(db, v, new_version="1.0.0", source="w1", kind="worker")
    assert v.version == "1.0.0"
    publish_scopes(db)
    assert event_store.query(limit=100) == []


async def test_record_version_flap_noop_on_empty_new_version(db):
    v = Versioned(version="1.0.0")
    await record_version_flap(db, v, new_version="", source="w1", kind="worker")
    assert v.version == "1.0.0"
    publish_scopes(db)
    assert event_store.query(limit=100) == []


async def test_record_version_flap_logs_warn_and_updates(db):
    v = Versioned(version="1.0.0")
    await record_version_flap(db, v, new_version="0.9.0", source="w1", kind="worker")
    assert v.version == "0.9.0"
    publish_scopes(db)  # flush staged events to event_store
    events = event_store.query(limit=100)
    assert len(events) == 1
    assert events[0]["level"] == "warn"
    assert "'1.0.0' → '0.9.0'" in events[0]["message"]
    assert "worker" in events[0]["message"]
