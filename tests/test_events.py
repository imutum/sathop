"""/api/events: verify the batch_id field — events tied to a granule carry the
parent batch_id so the UI can deep-link straight to the batch-detail page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator import event_store
from sathop.orchestrator.db import utcnow
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
    )
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def test_event_with_granule_carries_batch_id(client):
    now = utcnow()
    event_store.append(
        ts=now, source="worker-a", level="error", granule_id="g1", batch_id="b1", message="oops"
    )
    event_store.append(ts=now, source="orchestrator", level="info", message="started")

    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    by_msg = {e["message"]: e for e in data}

    assert by_msg["oops"]["granule_id"] == "g1"
    assert by_msg["oops"]["batch_id"] == "b1"

    assert by_msg["started"]["granule_id"] is None
    assert by_msg["started"]["batch_id"] is None


async def test_event_with_orphaned_granule_has_null_batch_id(client):
    """Event references a granule_id whose row was pruned — batch_id is null."""
    event_store.append(ts=utcnow(), source="old", level="warn", granule_id="long-gone", message="stale ref")

    r = client.get("/api/events")
    assert r.status_code == 200
    (e,) = r.json()
    assert e["granule_id"] == "long-gone"
    assert e["batch_id"] is None


async def test_since_id_and_limit_still_work(client):
    now = utcnow()
    for i in range(5):
        event_store.append(ts=now, source="t", level="info", message=f"e{i}")

    r = client.get("/api/events?limit=2")
    assert len(r.json()) == 2
    # Latest first
    assert [e["message"] for e in r.json()] == ["e4", "e3"]

    r2 = client.get("/api/events?since_id=3")
    assert [e["message"] for e in r2.json()] == ["e4", "e3"]


async def test_granule_id_filter_isolates_one_granule(client):
    """BatchDetail's expanded-row events panel relies on granule_id= filter."""
    now = utcnow()
    for i in range(3):
        event_store.append(
            ts=now, source="w", level="error", granule_id="b1:g-a", batch_id="b1", message=f"a-err-{i}"
        )
    event_store.append(ts=now, source="w", level="info", granule_id="b1:g-b", batch_id="b1", message="b-ok")
    event_store.append(ts=now, source="o", level="info", message="orchestrator-noise")

    r = client.get("/api/events?granule_id=b1:g-a")
    msgs = sorted(e["message"] for e in r.json())
    assert msgs == ["a-err-0", "a-err-1", "a-err-2"]
    assert all(e["batch_id"] == "b1" for e in r.json())


async def test_before_id_pages_backward(client):
    """before_id lets the UI load older events past the rolling 500-row window."""
    now = utcnow()
    for i in range(10):
        event_store.append(ts=now, source="t", level="info", message=f"e{i}")

    # First page: latest 3 → ids 10,9,8 (1-indexed)
    page1 = client.get("/api/events?limit=3").json()
    assert [e["message"] for e in page1] == ["e9", "e8", "e7"]

    # Page backward from the oldest of page1 (id=8) → next 3 older
    oldest = page1[-1]["id"]
    page2 = client.get(f"/api/events?limit=3&before_id={oldest}").json()
    assert all(e["id"] < oldest for e in page2)
    assert [e["message"] for e in page2] == ["e6", "e5", "e4"]

    # before_id combines with level filter
    event_store.append(ts=now, source="t", level="error", message="boom")
    boom_id = client.get("/api/events?level=error&limit=1").json()[0]["id"]
    older_errs = client.get(f"/api/events?level=error&before_id={boom_id}").json()
    assert older_errs == []
