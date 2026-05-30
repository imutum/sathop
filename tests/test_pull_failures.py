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
from sathop.orchestrator.db import Batch, Granule, GranuleObject, Receiver
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
        max_pull_failures=3,
    )
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
                inputs=[],
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


async def _seed_two_objects(receiver_id: str = "r1") -> tuple[int, int]:
    async with orch_db._session_maker() as s:
        s.add(Receiver(receiver_id=receiver_id, version="t", platform="linux"))
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        s.add(Granule(granule_id="g1", batch_id="b", state=GranuleState.UPLOADED.value, inputs=[]))
        ids: list[int] = []
        for key in ("b/g1/out1.bin", "b/g1/out2.bin"):
            o = GranuleObject(
                granule_id="g1",
                worker_id="w1",
                object_key=key,
                presigned_url="http://w1/x",
                sha256="abc",
                size=10,
            )
            s.add(o)
            await s.flush()
            ids.append(o.id)
        await s.commit()
        return ids[0], ids[1]


async def _granule_state(gid: str = "g1") -> str:
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, gid)
        return g.state


async def test_granule_acked_only_after_all_objects_acked(client):
    """UPLOADED→ACKED fires only once every object is acked — exercises the
    shared all_objects_acked predicate as the receiver-side transition gate."""
    id1, id2 = await _seed_two_objects()

    r = client.post(
        "/api/receivers/ack", json={"receiver_id": "r1", "object_id": id1, "sha256": "abc", "success": True}
    )
    assert r.status_code == 200
    assert await _granule_state() == GranuleState.UPLOADED.value  # one of two acked → no transition

    r = client.post(
        "/api/receivers/ack", json={"receiver_id": "r1", "object_id": id2, "sha256": "abc", "success": True}
    )
    assert r.status_code == 200
    assert await _granule_state() == GranuleState.ACKED.value  # all acked → ACKED


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


# ─── batched ingress (/ack/batch) ──────────────────────────────────────────


def _ack(object_id: int, *, success: bool = True, sha256: str = "abc", error: str | None = None) -> dict:
    return {"receiver_id": "r1", "object_id": object_id, "sha256": sha256, "success": success, "error": error}


async def test_batch_acks_all_objects_and_transitions_granule(client):
    """Both of a granule's objects acked in ONE batch → UPLOADED→ACKED in the
    same transaction (batched all_objects_acked gate)."""
    id1, id2 = await _seed_two_objects()
    r = client.post("/api/receivers/ack/batch", json={"acks": [_ack(id1), _ack(id2)]})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert await _granule_state() == GranuleState.ACKED.value


async def test_batch_partial_ack_leaves_granule_uploaded(client):
    id1, _id2 = await _seed_two_objects()
    r = client.post("/api/receivers/ack/batch", json={"acks": [_ack(id1)]})
    assert r.status_code == 200
    assert await _granule_state() == GranuleState.UPLOADED.value


async def test_batch_failed_acks_increment_and_retire(client):
    """Three failures for the same object in one batch (applied in list order)
    exhaust it — no longer offered."""
    obj_id = await _seed()
    r = client.post(
        "/api/receivers/ack/batch",
        json={"acks": [_ack(obj_id, success=False, sha256="", error=f"e{i}") for i in range(3)]},
    )
    assert r.status_code == 200, r.text
    assert client.post("/api/receivers/pull", json={"receiver_id": "r1", "limit": 10}).json()["items"] == []


async def test_batch_skips_unknown_object_applies_rest(client):
    """A missing object_id is skipped (never fails the batch); the real one acks."""
    obj_id = await _seed()
    r = client.post("/api/receivers/ack/batch", json={"acks": [_ack(999_999), _ack(obj_id)]})
    assert r.status_code == 200, r.text
    assert await _granule_state() == GranuleState.ACKED.value


async def test_batch_mixed_success_and_failure(client):
    """One success + one failure across two objects in a single batch: the
    success acks (no transition — other object still pending), the failure bumps
    its counter."""
    id1, id2 = await _seed_two_objects()
    r = client.post(
        "/api/receivers/ack/batch",
        json={"acks": [_ack(id1), _ack(id2, success=False, sha256="", error="boom")]},
    )
    assert r.status_code == 200, r.text
    assert await _granule_state() == GranuleState.UPLOADED.value  # id2 not acked
    async with orch_db._session_maker() as s:
        assert (await s.get(GranuleObject, id2)).failed_pulls == 1


async def test_batch_empty_is_noop(client):
    r = client.post("/api/receivers/ack/batch", json={"acks": []})
    assert r.status_code == 200
    assert r.json()["ok"] is True
