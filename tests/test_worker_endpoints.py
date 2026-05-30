"""Endpoint contract for POST /api/workers/events (upload_completed and
processing_failed payloads).

These two events are the worker's terminal state-write paths and must both:
- Reject when the worker no longer owns the granule (lease revoked, cancel
  cleared leased_by).
- Reject when the granule isn't in a state that justifies the event
  (upload_completed needs UPLOADING; processing_failed needs LEASED_STATES).

Covers the contract that lets the worker safely treat 4xx as "give up on
this granule" without risking inconsistent stage timings."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Batch, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.state_machine import GranuleState


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
    state: str = GranuleState.UPLOADING.value,
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
                inputs=[],
                leased_by=leased_by,
                lease_expires_at=(utcnow() + timedelta(minutes=30)) if leased_by else None,
            )
        )
        await s.commit()


def _upload_completed_payload(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {
        "kind": "upload_completed",
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


def _failure_payload(granule_id: str = "g1", worker_id: str = "w1", **extra) -> dict:
    return {
        "kind": "processing_failed",
        "granule_id": granule_id,
        "worker_id": worker_id,
        "error": "boom",
        "exit_code": 7,
        **extra,
    }


# ─── upload_completed contract ────────────────────────────────────────────


async def test_upload_completed_happy_path_uploading_to_uploaded(client):
    await _seed_granule(state=GranuleState.UPLOADING.value)
    r = client.post("/api/workers/events", json=_upload_completed_payload())
    assert r.status_code == 200, r.text
    assert r.json()["state"] == GranuleState.UPLOADED.value


async def test_upload_completed_collapsed_path_processing_to_uploaded(client):
    """Collapsed 3-event path (current worker): UploadCompleted is valid straight
    from PROCESSING — ProcessFinished + UploadStarted are folded in."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    r = client.post("/api/workers/events", json=_upload_completed_payload())
    assert r.status_code == 200, r.text
    assert r.json()["state"] == GranuleState.UPLOADED.value


async def test_upload_completed_rejects_wrong_predecessor(client):
    """Neither PROCESSING (collapsed) nor UPLOADING (legacy) — e.g. DOWNLOADED —
    must 409 so the worker drops the granule instead of corrupting stage timing."""
    await _seed_granule(state=GranuleState.DOWNLOADED.value)
    r = client.post("/api/workers/events", json=_upload_completed_payload())
    assert r.status_code == 409


async def test_upload_completed_rejects_when_lease_revoked(client):
    """leased_by=None ⇒ cancel/sweeper got there first ⇒ upload 409 so the
    worker stops trying."""
    await _seed_granule(state=GranuleState.BLACKLISTED.value, leased_by=None)
    r = client.post("/api/workers/events", json=_upload_completed_payload())
    assert r.status_code == 409


async def test_upload_completed_rejects_when_other_worker_owns_lease(client):
    """w1 trying to upload a granule now owned by w2 ⇒ 409."""
    await _seed_granule(state=GranuleState.UPLOADING.value, leased_by="w2")
    r = client.post("/api/workers/events", json=_upload_completed_payload(worker_id="w1"))
    assert r.status_code == 409


async def test_upload_completed_404_for_unknown_granule(client):
    r = client.post("/api/workers/events", json=_upload_completed_payload(granule_id="ghost"))
    assert r.status_code == 404


# ─── processing_failed contract ───────────────────────────────────────────


async def test_failure_during_processing_marks_pending_for_retry(client):
    await _seed_granule(state=GranuleState.PROCESSING.value)
    r = client.post("/api/workers/events", json=_failure_payload())
    assert r.status_code == 200
    assert r.json()["state"] == GranuleState.PENDING.value


async def test_failure_rejects_after_cancel(client):
    """If cancel set state=BLACKLISTED already, a late failure report from
    the worker must 409 — the worker should drop the granule, not get the
    state to flip back to PENDING."""
    await _seed_granule(state=GranuleState.BLACKLISTED.value, leased_by=None)
    r = client.post("/api/workers/events", json=_failure_payload())
    assert r.status_code == 409
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.BLACKLISTED.value


async def test_failure_rejects_when_state_uploaded(client):
    """Late failure report after a successful upload must not corrupt state.
    Catches the ordering bug where worker reports failure post-upload because
    of a bookkeeping issue downstream."""
    await _seed_granule(state=GranuleState.UPLOADED.value, leased_by=None)
    r = client.post("/api/workers/events", json=_failure_payload())
    assert r.status_code == 409


async def test_failure_rejects_when_other_worker_owns(client):
    await _seed_granule(state=GranuleState.PROCESSING.value, leased_by="w2")
    r = client.post("/api/workers/events", json=_failure_payload(worker_id="w1"))
    assert r.status_code == 409


async def test_failure_persists_stdout_stderr_tails(client):
    """Bundle subprocess output captured at failure time is persisted so the UI
    can show it without operators ssh'ing into a worker."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    payload = _failure_payload(
        stdout_tail="step 1: ok\nstep 2: ok\nstep 3: BOOM",
        stderr_tail="Traceback (most recent call last):\n  ...\nValueError: bad",
    )
    r = client.post("/api/workers/events", json=payload)
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
        "/api/workers/events",
        json=_failure_payload(stdout_tail=huge, stderr_tail=huge),
    )
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert len(g.stdout_tail) == 16000
        assert len(g.stderr_tail) == 16000


async def test_upload_clears_previous_failure_tails(client):
    """A retried granule whose previous attempt failed (stdout_tail set) and
    then succeeded should drop the stale tails on UploadCompleted."""
    await _seed_granule(state=GranuleState.PROCESSING.value)
    # First attempt fails with tails.
    client.post(
        "/api/workers/events",
        json=_failure_payload(stdout_tail="noisy", stderr_tail="broken"),
    )
    # Operator clicks retry → state back to PENDING; assume worker leases and
    # marches all the way to UPLOADING. Simulate by direct state set.
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        g.state = GranuleState.UPLOADING.value
        g.leased_by = "w1"
        g.lease_expires_at = utcnow() + timedelta(minutes=30)
        await s.commit()
    r = client.post("/api/workers/events", json=_upload_completed_payload())
    assert r.status_code == 200
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.stdout_tail is None
        assert g.stderr_tail is None


# ─── batched ingress (/events/batch) ───────────────────────────────────────
# The batch twin applies a worker's buffered transitions in ONE transaction:
# list order is apply order (per-granule order preserved), a stale/unleased
# event is skipped (never 409s the whole batch), and unleased/unknown granules
# come back in revoked_granule_ids so the worker stops buffering for them.


def _download_started(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {"kind": "download_started", "granule_id": granule_id, "worker_id": worker_id}


def _process_started(granule_id: str = "g1", worker_id: str = "w1") -> dict:
    return {"kind": "process_started", "granule_id": granule_id, "worker_id": worker_id, "download_ms": 5}


async def test_batch_applies_one_granule_full_sequence_in_order(client):
    """A single granule's 3 collapsed events in one POST march it QUEUED →
    UPLOADED — list order is the apply order."""
    await _seed_granule(state=GranuleState.QUEUED.value)
    body = {"events": [_download_started(), _process_started(), _upload_completed_payload()]}
    r = client.post("/api/workers/events/batch", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["revoked_granule_ids"] == []
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.UPLOADED.value


async def test_batch_applies_events_across_multiple_granules(client):
    await _seed_granule(granule_id="g1", state=GranuleState.QUEUED.value)
    await _seed_granule(granule_id="g2", state=GranuleState.QUEUED.value)
    body = {"events": [_download_started("g1"), _download_started("g2")]}
    r = client.post("/api/workers/events/batch", json=body)
    assert r.status_code == 200, r.text
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.DOWNLOADING.value
        assert (await s.get(Granule, "g2")).state == GranuleState.DOWNLOADING.value


async def test_batch_skips_unleased_event_and_reports_revoked(client):
    """An event for a granule this worker no longer holds is skipped — the rest
    of the batch still applies — and its id is returned for the worker to drop."""
    await _seed_granule(granule_id="g1", state=GranuleState.QUEUED.value, leased_by="w1")
    await _seed_granule(granule_id="g2", state=GranuleState.QUEUED.value, leased_by="w2")
    body = {"events": [_download_started("g1", "w1"), _download_started("g2", "w1")]}
    r = client.post("/api/workers/events/batch", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["revoked_granule_ids"] == ["g2"]
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.DOWNLOADING.value
        assert (await s.get(Granule, "g2")).state == GranuleState.QUEUED.value  # untouched


async def test_batch_reports_unknown_granule_as_revoked(client):
    r = client.post("/api/workers/events/batch", json={"events": [_download_started("ghost", "w1")]})
    assert r.status_code == 200
    assert r.json()["revoked_granule_ids"] == ["ghost"]


async def test_batch_skips_stale_event_without_failing_batch(client):
    """A predecessor mismatch (already-advanced granule) is a no-op skip, not a
    409 — the batch as a whole still succeeds and the granule is untouched."""
    await _seed_granule(granule_id="g1", state=GranuleState.UPLOADED.value, leased_by="w1")
    r = client.post("/api/workers/events/batch", json={"events": [_download_started("g1", "w1")]})
    assert r.status_code == 200, r.text
    assert r.json()["revoked_granule_ids"] == []
    async with orch_db._session_maker() as s:
        assert (await s.get(Granule, "g1")).state == GranuleState.UPLOADED.value


async def test_batch_empty_is_noop(client):
    r = client.post("/api/workers/events/batch", json={"events": []})
    assert r.status_code == 200
    assert r.json()["revoked_granule_ids"] == []
