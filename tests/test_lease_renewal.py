"""Lease auto-renewal on heartbeat + bidirectional revoked-granule sync.

Heartbeat doubles as a keep-alive: every check-in pushes the
`lease_expires_at` of every granule the worker holds forward by
LEASE_DURATION. Without this, a slow processor (e.g. a granule that takes
>30 min) sees its lease swept while still running, the row flips back to
PENDING, and subsequent events 409 — the worker's in-memory pipeline turns
into wasted ghost work.

Revocation is heartbeat-driven: the orchestrator returns `revoked_granule_ids`
and the worker cancels the matching handler task (no per-event 4xx path)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.worker_leases import LEASE_DURATION
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


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


async def _seed_worker_with_leased_granules(
    worker_id: str = "w1",
    expires_at: datetime | None = None,
    states: list[str] | None = None,
) -> list[str]:
    """Seed one batch + N granules each leased to `worker_id`. Returns granule
    IDs in insertion order. Default expiry is "10 minutes ago" so we can
    detect renewal pushing it well into the future."""
    states = states or [GranuleState.DOWNLOADING.value, GranuleState.PROCESSING.value]
    expires_at = expires_at or (utcnow() - timedelta(minutes=10))
    gids = []
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=4))
        s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        for i, st in enumerate(states):
            gid = f"g{i}"
            s.add(
                Granule(
                    granule_id=gid,
                    batch_id="b",
                    state=st,
                    inputs=[],
                    leased_by=worker_id,
                    lease_expires_at=expires_at,
                )
            )
            gids.append(gid)
        await s.commit()
    return gids


async def _granule_lease_expiry(granule_id: str) -> datetime | None:
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, granule_id)
        return g.lease_expires_at if g else None


def _heartbeat_payload(worker_id: str = "w1") -> dict:
    return {
        "worker_id": worker_id,
        "disk_used_gb": 1.0,
        "disk_total_gb": 100.0,
        "cpu_percent": 10.0,
        "mem_percent": 20.0,
        "monthly_egress_gb": 0.0,
        "queue_pending_download": 0,
        "queue_downloading": 1,
        "queue_pending_processing": 0,
        "queue_processing": 1,
        "queue_uploading": 0,
        "paused": False,
    }


async def test_heartbeat_pushes_lease_expiry_forward(client):
    gids = await _seed_worker_with_leased_granules()
    before = utcnow()

    r = client.post("/api/workers/heartbeat", json=_heartbeat_payload())
    assert r.status_code == 200, r.text

    # Each granule's lease_expires_at must now be roughly now + LEASE_DURATION.
    for gid in gids:
        new_expiry = await _granule_lease_expiry(gid)
        assert new_expiry is not None
        delta = new_expiry - before
        # Allow a few seconds slack for the request round-trip.
        assert LEASE_DURATION - timedelta(seconds=5) <= delta <= LEASE_DURATION + timedelta(seconds=5)


async def test_heartbeat_does_not_renew_other_workers_leases(client):
    """Lease renewal must scope to the heartbeating worker — otherwise w1's
    heartbeat would extend granules leased by w2."""
    await _seed_worker_with_leased_granules("w1")
    other_expiry = utcnow() - timedelta(minutes=5)
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w2", version="t", capacity=4))
        s.add(
            Granule(
                granule_id="g-w2",
                batch_id="b",
                state=GranuleState.DOWNLOADING.value,
                inputs=[],
                leased_by="w2",
                lease_expires_at=other_expiry,
            )
        )
        await s.commit()

    client.post("/api/workers/heartbeat", json=_heartbeat_payload("w1"))

    # w2's granule must still have its original (stale) expiry — the sweeper
    # will reclaim it on its next pass.
    g_w2_expiry = await _granule_lease_expiry("g-w2")
    assert g_w2_expiry is not None
    assert abs((g_w2_expiry - other_expiry).total_seconds()) < 1


async def test_heartbeat_skips_pending_granules_for_renewal(client):
    """Granules in PENDING (sweeper-reclaimed or never-leased) shouldn't get
    a lease_expires_at — they'd suddenly look "leased" to the next /lease
    call's predicate."""
    await _seed_worker_with_leased_granules("w1")
    async with orch_db._session_maker() as s:
        s.add(
            Granule(
                granule_id="g-pending",
                batch_id="b",
                state=GranuleState.PENDING.value,
                inputs=[],
                leased_by=None,
                lease_expires_at=None,
            )
        )
        await s.commit()

    client.post("/api/workers/heartbeat", json=_heartbeat_payload("w1"))

    g_pending_expiry = await _granule_lease_expiry("g-pending")
    assert g_pending_expiry is None


# ─── Bidirectional sync: heartbeat returns revoked granule IDs ────────────


async def test_heartbeat_returns_revoked_for_unleased_active_granule(client):
    """Worker reports an active granule that the DB no longer credits to it
    (e.g. after cancel_batch cleared leased_by) → orchestrator returns it in
    revoked_granule_ids so the worker can cancel the asyncio task."""
    await _seed_worker_with_leased_granules("w1")
    # Simulate the worker still claiming an extra granule ID that is now
    # cancelled (BLACKLISTED, leased_by=null).
    async with orch_db._session_maker() as s:
        s.add(
            Granule(
                granule_id="g-cancelled",
                batch_id="b",
                state=GranuleState.BLACKLISTED.value,
                inputs=[],
                leased_by=None,
                lease_expires_at=None,
            )
        )
        await s.commit()

    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = ["g0", "g1", "g-cancelled", "g-doesnt-exist"]
    r = client.post("/api/workers/heartbeat", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    revoked = set(body["revoked_granule_ids"])
    # g0/g1 are still legitimately leased to w1 → not revoked.
    assert "g0" not in revoked
    assert "g1" not in revoked
    # Cancelled and unknown IDs both end up revoked (worker should drop them).
    assert "g-cancelled" in revoked
    assert "g-doesnt-exist" in revoked


async def test_heartbeat_returns_revoked_for_other_workers_lease(client):
    """If worker w1 still thinks it owns a granule that's now leased by w2
    (manual reassignment / sweeper handed off), w1 must drop it."""
    await _seed_worker_with_leased_granules("w1")
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w2", version="t", capacity=4))
        s.add(
            Granule(
                granule_id="g-w2",
                batch_id="b",
                state=GranuleState.DOWNLOADING.value,
                inputs=[],
                leased_by="w2",
                lease_expires_at=utcnow() + timedelta(minutes=30),
            )
        )
        await s.commit()

    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = ["g0", "g-w2"]
    r = client.post("/api/workers/heartbeat", json=payload)
    body = r.json()

    assert "g0" not in body["revoked_granule_ids"]
    assert "g-w2" in body["revoked_granule_ids"]


async def test_heartbeat_empty_active_returns_no_revokes(client):
    """Quiet worker (no in-flight tasks) shouldn't get any spurious revoke
    list — empty input ⇒ empty output."""
    await _seed_worker_with_leased_granules("w1")
    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = []
    body = client.post("/api/workers/heartbeat", json=payload).json()
    assert body["revoked_granule_ids"] == []


# ─── Re-register reclaims orphaned leases ─────────────────────────────────


async def test_reregister_reclaims_orphaned_leases(client):
    """A restarted worker re-registers with no in-flight state, so its still-pinned
    leases are orphans the heartbeat would renew forever — register must reclaim
    them to PENDING for re-lease."""
    gids = await _seed_worker_with_leased_granules("w1")
    r = client.post("/api/workers/register", json={"worker_id": "w1", "version": "t", "capacity": 4})
    assert r.status_code == 200, r.text
    async with orch_db._session_maker() as s:
        for gid in gids:
            g = await s.get(Granule, gid)
            assert g.state == GranuleState.PENDING.value, (gid, g.state)
            assert g.leased_by is None
            assert g.lease_expires_at is None


async def test_reregister_scopes_reclaim_to_self(client):
    """w1's re-register must not disturb w2's leases."""
    await _seed_worker_with_leased_granules("w1")
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w2", version="t", capacity=4))
        s.add(
            Granule(
                granule_id="g-w2",
                batch_id="b",
                state=GranuleState.DOWNLOADING.value,
                inputs=[],
                leased_by="w2",
                lease_expires_at=utcnow() + timedelta(minutes=30),
            )
        )
        await s.commit()
    client.post("/api/workers/register", json={"worker_id": "w1", "version": "t", "capacity": 4})
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g-w2")
        assert g.state == GranuleState.DOWNLOADING.value
        assert g.leased_by == "w2"


# ─── Heartbeat reconcile: reclaim orch-restart orphans ────────────────────


async def _age_granules(gids: list[str], minutes: int) -> None:
    async with orch_db._session_maker() as s:
        for gid in gids:
            (await s.get(Granule, gid)).updated_at = utcnow() - timedelta(minutes=minutes)
        await s.commit()


async def test_heartbeat_reclaims_orphaned_lease(client):
    """Granule leased to w1, frozen (old updated_at), but NOT in the worker's
    reported active set → an orch-restart orphan the heartbeat reclaims to PENDING."""
    gids = await _seed_worker_with_leased_granules("w1")
    await _age_granules(gids, minutes=5)  # older than the reclaim grace window
    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = []  # worker reports nothing in-flight
    assert client.post("/api/workers/heartbeat", json=payload).status_code == 200
    async with orch_db._session_maker() as s:
        for gid in gids:
            g = await s.get(Granule, gid)
            assert g.state == GranuleState.PENDING.value, (gid, g.state)
            assert g.leased_by is None
            assert g.retry_count == 0  # reclaim is sweeper-style: no retry penalty


async def test_heartbeat_does_not_reclaim_active_granule(client):
    """A granule the worker still actively holds (in active set) is never reclaimed,
    even if its state hasn't advanced for a while (e.g. a long download)."""
    gids = await _seed_worker_with_leased_granules("w1")
    await _age_granules(gids, minutes=5)
    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = gids
    client.post("/api/workers/heartbeat", json=payload)
    async with orch_db._session_maker() as s:
        for gid in gids:
            assert (await s.get(Granule, gid)).leased_by == "w1"


async def test_heartbeat_does_not_reclaim_fresh_lease(client):
    """A just-leased granule not yet in the worker's active set must survive — the
    grace window on updated_at guards the lease→handler-report gap."""
    gids = await _seed_worker_with_leased_granules("w1")  # updated_at defaults to now
    payload = _heartbeat_payload("w1")
    payload["active_granule_ids"] = []
    client.post("/api/workers/heartbeat", json=payload)
    async with orch_db._session_maker() as s:
        for gid in gids:
            assert (await s.get(Granule, gid)).leased_by == "w1"


async def test_heartbeat_without_active_ids_skips_reclaim(client):
    """A pre-reconcile worker omits active_granule_ids (None) → the orchestrator
    must not reclaim its leases, or it would revoke real in-flight work."""
    gids = await _seed_worker_with_leased_granules("w1")
    await _age_granules(gids, minutes=5)
    payload = _heartbeat_payload("w1")  # no active_granule_ids key → None
    client.post("/api/workers/heartbeat", json=payload)
    async with orch_db._session_maker() as s:
        for gid in gids:
            assert (await s.get(Granule, gid)).leased_by == "w1"
