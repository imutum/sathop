"""Endpoint contract for /api/workers/upload and /api/workers/failure.

These two endpoints are the worker's terminal state-write paths and must
both:
- Reject when the worker no longer owns the granule (lease revoked, cancel
  cleared leased_by).
- Reject when the granule isn't in a state that justifies the call (upload
  needs PROCESSED; failure needs LEASED_STATES).

Covers the contract that lets the worker safely treat 4xx as "give up on
this granule" without risking inconsistent stage timings."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(
        db_path=tmp_path / "test.db",
        token="",
        max_retries=3,
    )
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_granule(
    granule_id: str = "g1",
    state: str = GranuleState.PROCESSED.value,
    leased_by: str | None = "w1",
) -> None:
    async with orch_db._session_maker() as s:
        if await s.get(Worker, "w1") is None:
            s.add(Worker(worker_id="w1", version="t", capacity=4))
        if await s.get(Batch, "b") is None:
            s.add(Batch(batch_id="b", name="t", bundle_ref="local:x"))
        s.add(
            Granule(
                granule_id=granule_id,
                batch_id="b",
                state=state,
                inputs_json="[]",
                leased_by=leased_by,
                lease_expires_at=(utcnow() + timedelta(minutes=30)) if leased_by else None,
            )
        )
        await s.commit()


def _upload_payload(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {
        "granule_id": granule_id,
        "worker_id": worker_id,
        "objects": [
            {
                "object_key": "out.tif",
                "presigned_url": "http://w/out.tif",
                "sha256": "0" * 64,
                "size": 100,
            }
        ],
    }


# ─── upload contract ───────────────────────────────────────────────────────


async def test_upload_happy_path_processed_to_uploaded(client):
    await _seed_granule(state=GranuleState.PROCESSED.value)
    r = client.post("/api/workers/upload", json=_upload_payload())
    assert r.status_code == 200, r.text


async def test_upload_rejects_when_not_processed(client):
    """Worker must report PROCESSED before upload — otherwise process timing
    silently absorbs upload duration."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    r = client.post("/api/workers/upload", json=_upload_payload())
    assert r.status_code == 409
    assert "processed" in r.text.lower()


async def test_upload_rejects_when_lease_revoked(client):
    """leased_by=None ⇒ cancel/sweeper got there first ⇒ upload 409 so the
    worker stops trying."""
    await _seed_granule(state=GranuleState.BLACKLISTED.value, leased_by=None)
    r = client.post("/api/workers/upload", json=_upload_payload())
    assert r.status_code == 409


async def test_upload_rejects_when_other_worker_owns_lease(client):
    """w1 trying to upload a granule now owned by w2 ⇒ 409."""
    await _seed_granule(state=GranuleState.PROCESSED.value, leased_by="w2")
    r = client.post("/api/workers/upload", json=_upload_payload(worker_id="w1"))
    assert r.status_code == 409


async def test_upload_404_for_unknown_granule(client):
    r = client.post("/api/workers/upload", json=_upload_payload(granule_id="ghost"))
    assert r.status_code == 404


# ─── failure contract ──────────────────────────────────────────────────────


def _failure_payload(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {
        "granule_id": granule_id,
        "worker_id": worker_id,
        "error": "boom",
        "exit_code": 7,
    }


async def test_failure_during_processing_marks_pending_for_retry(client):
    await _seed_granule(state=GranuleState.PROCESSING.value)
    r = client.post("/api/workers/failure", json=_failure_payload())
    assert r.status_code == 200
    assert r.json()["state"] == GranuleState.PENDING.value


async def test_failure_rejects_after_cancel(client):
    """If cancel set state=BLACKLISTED already, a late failure report from
    the worker must 409 — the worker should drop the granule, not get the
    state to flip back to PENDING."""
    await _seed_granule(state=GranuleState.BLACKLISTED.value, leased_by=None)
    r = client.post("/api/workers/failure", json=_failure_payload())
    assert r.status_code == 409
    # State must remain BLACKLISTED — failure mustn't sneak it back to PENDING.
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.BLACKLISTED.value


async def test_failure_rejects_when_state_uploaded(client):
    """Late failure report after a successful upload must not corrupt state.
    Catches the ordering bug where worker reports failure post-upload because
    of a bookkeeping issue downstream."""
    await _seed_granule(state=GranuleState.UPLOADED.value, leased_by=None)
    r = client.post("/api/workers/failure", json=_failure_payload())
    assert r.status_code == 409


async def test_failure_rejects_when_other_worker_owns(client):
    await _seed_granule(state=GranuleState.PROCESSING.value, leased_by="w2")
    r = client.post("/api/workers/failure", json=_failure_payload(worker_id="w1"))
    assert r.status_code == 409


async def test_failure_persists_stdout_stderr_tails(client):
    """Bundle subprocess output captured at failure time is persisted so the UI
    can show it without operators ssh'ing into a worker."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    payload = {
        **_failure_payload(),
        "stdout_tail": "step 1: ok\nstep 2: ok\nstep 3: BOOM",
        "stderr_tail": "Traceback (most recent call last):\n  ...\nValueError: bad",
    }
    r = client.post("/api/workers/failure", json=payload)
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.stdout_tail == "step 1: ok\nstep 2: ok\nstep 3: BOOM"
        assert g.stderr_tail.startswith("Traceback")


async def test_failure_caps_oversized_tails(client):
    """Worker is supposed to cap before sending, but the orch must not trust
    that — a misbehaving / older worker mustn't be able to write multi-MB rows."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    huge = "x" * 50_000
    r = client.post(
        "/api/workers/failure",
        json={**_failure_payload(), "stdout_tail": huge, "stderr_tail": huge},
    )
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert len(g.stdout_tail) == 16000
        assert len(g.stderr_tail) == 16000


async def test_upload_clears_previous_failure_tails(client):
    """A retried granule whose previous attempt failed (stdout_tail set) and
    then succeeded (PROCESSED → UPLOADED) shouldn't keep the stale tails."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    # First attempt fails with tails.
    client.post(
        "/api/workers/failure",
        json={**_failure_payload(), "stdout_tail": "noisy", "stderr_tail": "broken"},
    )
    # Operator clicks retry → state back to PENDING; assume worker leases and
    # marches all the way to PROCESSED. Simulate by directly setting state.
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        g.state = GranuleState.PROCESSED.value
        g.leased_by = "w1"
        g.lease_expires_at = utcnow() + timedelta(minutes=30)
        await s.commit()
    r = client.post("/api/workers/upload", json=_upload_payload())
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.stdout_tail is None
        assert g.stderr_tail is None
