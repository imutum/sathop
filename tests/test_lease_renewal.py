"""Lease auto-renewal on heartbeat + worker-side LeaseRevoked handling.

Heartbeat doubles as a keep-alive: every check-in pushes the
`lease_expires_at` of every granule the worker holds forward by
LEASE_DURATION. Without this, a slow processor (e.g. a granule that takes
>30 min) sees its lease swept while still running, the row flips back to
PENDING, and subsequent events 409 — the worker's in-memory pipeline turns
into wasted ghost work.

The worker side of the contract: when /api/workers/events returns 404/409,
the worker raises LeaseRevoked so the granule handler aborts immediately
instead of continuing to download/process bytes whose upload will be
rejected anyway."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
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


# ─── Worker-side: LeaseRevoked translation of 404/409 ─────────────────────


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://orch/api/workers/events")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


class _StubAgent:
    """Minimal stand-in for OrchestratorClient — only `emit_event` matters
    for the LeaseRevoked path. Each call dequeues from `responses`: a status
    code int ⇒ raise that 4xx/5xx, None ⇒ succeed silently."""

    def __init__(self, responses: list[int | None]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def emit_event(self, event) -> None:
        self.calls.append(event.kind)
        next_status = self.responses.pop(0) if self.responses else None
        if next_status is not None:
            raise _http_error(next_status)


def _download_started(gid: str = "g1"):
    from sathop.shared.state_machine import DownloadStarted

    return DownloadStarted(granule_id=gid, worker_id="w1")


def _process_started(gid: str = "g1"):
    from sathop.shared.state_machine import ProcessStarted

    return ProcessStarted(granule_id=gid, worker_id="w1")


async def test_emit_lease_event_409_raises_lease_revoked():
    from sathop.worker.handler import LeaseRevoked, emit_lease_event

    with pytest.raises(LeaseRevoked):
        await emit_lease_event(_StubAgent([409]), _download_started())


async def test_emit_lease_event_404_raises_lease_revoked():
    from sathop.worker.handler import LeaseRevoked, emit_lease_event

    with pytest.raises(LeaseRevoked):
        await emit_lease_event(_StubAgent([404]), _process_started())


async def test_emit_lease_event_500_swallowed_as_best_effort():
    """5xx and network errors stay best-effort — the next phase boundary
    will retry. Raising would abort the whole granule on a transient
    orchestrator hiccup."""
    from sathop.worker.handler import emit_lease_event

    await emit_lease_event(_StubAgent([500]), _download_started())


async def test_emit_lease_event_success_returns_silently():
    from sathop.worker.handler import emit_lease_event

    agent = _StubAgent([None])
    await emit_lease_event(agent, _download_started())
    assert agent.calls == ["download_started"]


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
