"""Receiver /pull soft-claim (A3): the atomic per-receiver claim window that lets
N receivers fetch *disjoint* object sets instead of all redundantly pulling the
same ones. Mirrors the worker lease — an UPDATE…RETURNING stamps
pull_lease_by/expires_at; a receiver's own live claim is self-excluded, an expired
claim re-offers to whoever asks next, and a pull failure clears the claim at once.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Batch, Granule, GranuleObject, Receiver, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="", max_pull_failures=3, pull_lease_sec=600)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_receivers(*ids: str) -> None:
    async with orch_db._session_maker() as s:
        for rid in ids:
            s.add(Receiver(receiver_id=rid, version="t", platform="linux"))
        await s.commit()


async def _seed_objects(n: int, *, batch_id: str = "b", target: str | None = None) -> list[int]:
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name="t", bundle_ref="orch:x@1", target_receiver_id=target))
        ids: list[int] = []
        for i in range(n):
            gid = f"{batch_id}-g{i}"
            s.add(Granule(granule_id=gid, batch_id=batch_id, state=GranuleState.UPLOADED.value, inputs=[]))
            o = GranuleObject(
                granule_id=gid,
                worker_id="w1",
                object_key=f"{batch_id}/{gid}/o.bin",
                presigned_url="http://w1/x",
                sha256="abc",
                size=10,
            )
            s.add(o)
            await s.flush()
            ids.append(o.id)
        await s.commit()
        return ids


def _pull(client: TestClient, rid: str, limit: int = 10) -> list[int]:
    r = client.post("/api/receivers/pull", json={"receiver_id": rid, "limit": limit})
    assert r.status_code == 200, r.text
    return [it["object_id"] for it in r.json()["items"]]


async def _expire(oid: int) -> None:
    async with orch_db._session_maker() as s:
        o = await s.get(GranuleObject, oid)
        o.pull_lease_expires_at = utcnow() - timedelta(seconds=1)
        await s.commit()


async def test_pull_claims_then_self_excludes(client):
    [oid] = await _seed_objects(1)
    await _seed_receivers("r1")
    assert _pull(client, "r1") == [oid]  # claimed
    assert _pull(client, "r1") == []  # own live claim is excluded — no re-pull churn


async def test_two_receivers_get_disjoint_sets(client):
    ids = await _seed_objects(6)
    await _seed_receivers("r1", "r2")
    a = set(_pull(client, "r1", limit=3))
    b = set(_pull(client, "r2", limit=3))
    assert len(a) == 3 and len(b) == 3
    assert a.isdisjoint(b)  # the whole point of A3: no two receivers fetch the same object
    assert a | b == set(ids)


async def test_limit_is_respected(client):
    await _seed_objects(5)
    await _seed_receivers("r1")
    assert len(_pull(client, "r1", limit=2)) == 2


async def test_expired_claim_is_reoffered_to_peer(client):
    [oid] = await _seed_objects(1)
    await _seed_receivers("r1", "r2")
    assert _pull(client, "r1") == [oid]
    assert _pull(client, "r2") == []  # r1 holds a live claim → peer sees nothing
    await _expire(oid)
    assert _pull(client, "r2") == [oid]  # expired (dead receiver) → re-claimable


async def test_failed_pull_clears_claim_for_instant_failover(client):
    [oid] = await _seed_objects(1)
    await _seed_receivers("r1", "r2")
    assert _pull(client, "r1") == [oid]
    r = client.post(
        "/api/receivers/ack",
        json={"receiver_id": "r1", "object_id": oid, "sha256": "", "success": False, "error": "boom"},
    )
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        o = await s.get(GranuleObject, oid)
        assert o.pull_lease_by is None and o.pull_lease_expires_at is None
    assert _pull(client, "r2") == [oid]  # re-offered at once, no waiting out the lease


async def test_self_reclaims_and_extends_after_expiry(client):
    """An active-but-slow receiver re-extends its own expired claim instead of
    losing it: the SAME receiver re-pulls past expiry and gets it back, freshly
    dated."""
    [oid] = await _seed_objects(1)
    await _seed_receivers("r1")
    assert _pull(client, "r1") == [oid]
    await _expire(oid)
    assert _pull(client, "r1") == [oid]  # expired → claimable by self again
    async with orch_db._session_maker() as s:
        o = await s.get(GranuleObject, oid)
        assert o.pull_lease_by == "r1"
        assert o.pull_lease_expires_at > utcnow()  # extended


async def test_target_receiver_binding_respected(client):
    [oid] = await _seed_objects(1, target="r2")
    await _seed_receivers("r1", "r2")
    assert _pull(client, "r1") == []  # batch is bound to r2
    assert _pull(client, "r2") == [oid]


async def test_double_ack_of_same_object_is_idempotent(client):
    """If a claim expires mid-pull (object slower than pull_lease_sec) a peer can
    pull the same object, so both receivers ack it. The second ack must be a safe
    no-op — this idempotency is what makes the advisory-lease duplicate-pull window
    acceptable (vs. a hard lock)."""
    [oid] = await _seed_objects(1)
    await _seed_receivers("r1", "r2")
    a = client.post(
        "/api/receivers/ack",
        json={"receiver_id": "r1", "object_id": oid, "sha256": "abc", "success": True},
    )
    assert a.status_code == 200 and a.json()["ok"] is True
    b = client.post(
        "/api/receivers/ack",
        json={"receiver_id": "r2", "object_id": oid, "sha256": "abc", "success": True},
    )
    assert b.status_code == 200 and b.json()["ok"] is True
    async with orch_db._session_maker() as s:
        assert (await s.get(GranuleObject, oid)).acked_at is not None
    assert _pull(client, "r1") == [] and _pull(client, "r2") == []  # acked → offered to no one
