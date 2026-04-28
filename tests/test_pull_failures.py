"""Receiver pull-failure throttling.

Permanently broken presigned URLs used to spin every receiver forever — the
pull endpoint had no notion of "give up". Now `failed_pulls` increments on
every success=false ack and the orchestrator stops offering past
`SATHOP_MAX_PULL_FAILURES`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleObject, Receiver
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "max_pull_failures", 3)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed(receiver_id: str = "r1") -> int:
    async with orch_db._session_maker() as s:
        s.add(Receiver(receiver_id=receiver_id, version="t", platform="linux"))
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b",
                state=GranuleState.UPLOADED.value,
                inputs_json="[]",
            )
        )
        obj = GranuleObject(
            granule_id="g1",
            worker_id="w1",
            object_key="b/g1/out.bin",
            presigned_url="http://w1/x",
            sha256="abc",
            size=10,
        )
        s.add(obj)
        await s.commit()
        return obj.id


async def test_pull_offers_object_initially(client):
    obj_id = await _seed()
    r = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["object_id"] == obj_id


async def test_failed_acks_increment_counter_and_eventually_retire(client):
    obj_id = await _seed()
    # Three failures (== max_pull_failures): the third ack should mark exhausted.
    for i in range(1, 4):
        r = client.post(
            "/api/receivers/ack",
            json={
                "receiver_id": "r1",
                "object_id": obj_id,
                "sha256": "",
                "success": False,
                "error": f"transport error #{i}",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["failed_pulls"] == i
    assert body["retried"] is False  # type: ignore[possibly-undefined]

    # Object should no longer be offered.
    r = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10})
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_reset_exhausted_objects_endpoint_zeroes_counters(client):
    obj_id = await _seed()
    # Burn all three retries.
    for _ in range(3):
        client.post(
            "/api/receivers/ack",
            json={"receiver_id": "r1", "object_id": obj_id, "sha256": "", "success": False, "error": "x"},
        )
    assert client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10}).json()["items"] == []

    # Reset → counters back to 0 → object is offered again.
    r = client.post("/api/batches/b/reset-exhausted-objects")
    assert r.status_code == 200
    assert r.json()["reset"] == 1

    items = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10}).json()["items"]
    assert len(items) == 1 and items[0]["object_id"] == obj_id


async def test_reset_endpoint_404s_on_missing_batch(client):
    r = client.post("/api/batches/no-such-batch/reset-exhausted-objects")
    assert r.status_code == 404


async def test_success_ack_clears_offering_independent_of_counter(client):
    obj_id = await _seed()
    # One failure, then a successful ack — object should be acked, no longer offered.
    client.post(
        "/api/receivers/ack",
        json={"receiver_id": "r1", "object_id": obj_id, "sha256": "", "success": False, "error": "x"},
    )
    r = client.post(
        "/api/receivers/ack",
        json={"receiver_id": "r1", "object_id": obj_id, "sha256": "abc", "success": True},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r = client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10})
    assert r.json()["items"] == []
