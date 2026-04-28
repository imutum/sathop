"""GET /api/events?source=<id> — exact-match filter on Event.source.

Powers the "view events for this node" link on Worker / Receiver cards. Without
it, operators had to type the worker_id into the global fuzzy search — which
also matched messages mentioning the same string, polluting the result set.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Event, Granule
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_mixed_events() -> None:
    async with orch_db._session_maker() as s:
        # Some events for two different workers and a receiver, plus
        # orchestrator-level events. Mix levels too so a combined source+level
        # query is exercised.
        s.add(Event(level="info", source="worker-w1", message="lease 5"))
        s.add(Event(level="warn", source="worker-w1", message="processing failed"))
        s.add(Event(level="info", source="worker-w2", message="lease 3"))
        s.add(Event(level="info", source="recv-r1", message="acked obj"))
        s.add(Event(level="error", source="worker-w1", message="bundle build failed"))
        s.add(Event(level="info", source="orchestrator", message="batch created"))
        await s.commit()


async def test_source_filter_returns_only_matching_rows(client):
    await _seed_mixed_events()
    rows = client.get("/api/events?source=worker-w1").json()
    assert {r["source"] for r in rows} == {"worker-w1"}
    assert len(rows) == 3


async def test_source_filter_is_exact_match_not_substring(client):
    """`worker-w1` must not match `worker-w11` or `worker-w` — operators rely
    on the link from a worker card landing on that worker only."""
    async with orch_db._session_maker() as s:
        s.add(Event(level="info", source="worker-w1", message="a"))
        s.add(Event(level="info", source="worker-w11", message="b"))
        s.add(Event(level="info", source="worker-w", message="c"))
        await s.commit()

    rows = client.get("/api/events?source=worker-w1").json()
    assert len(rows) == 1
    assert rows[0]["message"] == "a"


async def test_source_filter_combines_with_level(client):
    await _seed_mixed_events()
    rows = client.get("/api/events?source=worker-w1&level=warn").json()
    assert [r["message"] for r in rows] == ["processing failed"]


async def test_unknown_source_returns_empty_list(client):
    await _seed_mixed_events()
    assert client.get("/api/events?source=nobody").json() == []


async def test_no_source_param_returns_everything(client):
    await _seed_mixed_events()
    rows = client.get("/api/events?limit=100").json()
    assert len(rows) == 6


async def test_source_filter_combines_with_batch(client):
    """Source + batch — narrows to "events from worker X about granules in
    batch B". No fuzzy substring; both filters apply server-side."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(
            Granule(
                granule_id="b:g1",
                batch_id="b",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        s.add(Event(level="info", source="worker-w1", granule_id="b:g1", message="ours"))
        s.add(Event(level="info", source="worker-w1", granule_id=None, message="orch-level"))
        s.add(Event(level="info", source="worker-w2", granule_id="b:g1", message="other-worker"))
        await s.commit()

    rows = client.get("/api/events?source=worker-w1&batch_id=b").json()
    assert [r["message"] for r in rows] == ["ours"]
