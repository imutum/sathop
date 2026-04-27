"""Cancel / retry endpoints on batches + individual granules."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, utcnow
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


async def _seed(batch_id: str, granules: list[tuple[str, str]]):
    """Seed a batch with (granule_id, state) pairs. leased_by set for in-flight."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name="t", bundle_ref="local:x"))
        for gid, state in granules:
            s.add(
                Granule(
                    granule_id=gid,
                    batch_id=batch_id,
                    state=state,
                    inputs_json="[]",
                    leased_by="w1" if state == GranuleState.DOWNLOADING.value else None,
                    lease_expires_at=utcnow() if state == GranuleState.DOWNLOADING.value else None,
                )
            )
        await s.commit()


async def _state(gid: str) -> str:
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, gid)
        return g.state if g else "<missing>"


# ─── per-granule cancel ───────────────────────────────────────────────────


async def test_cancel_pending_granule(client):
    await _seed("b", [("g1", GranuleState.PENDING.value)])
    r = client.post("/api/batches/b/granules/g1/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == GranuleState.BLACKLISTED.value
    assert await _state("g1") == GranuleState.BLACKLISTED.value


async def test_cancel_downloading_clears_lease(client):
    await _seed("b", [("g1", GranuleState.DOWNLOADING.value)])
    r = client.post("/api/batches/b/granules/g1/cancel")
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.BLACKLISTED.value
        assert g.leased_by is None
        assert g.lease_expires_at is None


async def test_cancel_already_terminal_409(client):
    """UPLOADED means data already on worker storage — cancel doesn't apply."""
    await _seed("b", [("g1", GranuleState.UPLOADED.value)])
    r = client.post("/api/batches/b/granules/g1/cancel")
    assert r.status_code == 409
    assert "cannot cancel" in r.json()["detail"]
    assert await _state("g1") == GranuleState.UPLOADED.value


async def test_cancel_granule_not_in_batch_404(client):
    await _seed("b", [("g1", GranuleState.PENDING.value)])
    r = client.post("/api/batches/wrong-batch/granules/g1/cancel")
    assert r.status_code == 404


async def test_cancel_missing_granule_404(client):
    await _seed("b", [("g1", GranuleState.PENDING.value)])
    r = client.post("/api/batches/b/granules/nope/cancel")
    assert r.status_code == 404


# ─── per-granule retry ────────────────────────────────────────────────────


async def test_retry_failed_granule(client):
    await _seed("b", [("g1", GranuleState.FAILED.value)])
    # Mark with error + retry count so we can verify they get cleared
    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        g.error = "previous failure"
        g.retry_count = 2
        await s.commit()

    r = client.post("/api/batches/b/granules/g1/retry")
    assert r.status_code == 200
    assert r.json()["state"] == GranuleState.PENDING.value

    async with orch_db._session_maker() as s:
        g = await s.get(Granule, "g1")
        assert g.state == GranuleState.PENDING.value
        assert g.error is None
        assert g.retry_count == 0


async def test_retry_blacklisted_granule(client):
    await _seed("b", [("g1", GranuleState.BLACKLISTED.value)])
    r = client.post("/api/batches/b/granules/g1/retry")
    assert r.status_code == 200
    assert await _state("g1") == GranuleState.PENDING.value


async def test_retry_pending_409(client):
    """PENDING isn't retryable — no failure to retry from."""
    await _seed("b", [("g1", GranuleState.PENDING.value)])
    r = client.post("/api/batches/b/granules/g1/retry")
    assert r.status_code == 409


# ─── batch cancel ─────────────────────────────────────────────────────────


async def test_batch_cancel_blacklists_all_in_flight(client):
    await _seed(
        "b",
        [
            ("g_pending", GranuleState.PENDING.value),
            ("g_downloading", GranuleState.DOWNLOADING.value),
            ("g_processing", GranuleState.PROCESSING.value),
            ("g_uploaded", GranuleState.UPLOADED.value),  # past cancellable
            ("g_acked", GranuleState.ACKED.value),  # past cancellable
            ("g_failed", GranuleState.FAILED.value),  # already terminal; untouched
        ],
    )
    r = client.post("/api/batches/b/cancel")
    assert r.status_code == 200
    assert r.json()["cancelled"] == 3  # pending + downloading + processing

    assert await _state("g_pending") == GranuleState.BLACKLISTED.value
    assert await _state("g_downloading") == GranuleState.BLACKLISTED.value
    assert await _state("g_processing") == GranuleState.BLACKLISTED.value
    assert await _state("g_uploaded") == GranuleState.UPLOADED.value
    assert await _state("g_acked") == GranuleState.ACKED.value
    assert await _state("g_failed") == GranuleState.FAILED.value


async def test_batch_cancel_missing_batch_404(client):
    r = client.post("/api/batches/no-such/cancel")
    assert r.status_code == 404


async def test_batch_cancel_empty_no_affected(client):
    await _seed("b", [("g1", GranuleState.UPLOADED.value)])  # nothing cancellable
    r = client.post("/api/batches/b/cancel")
    assert r.status_code == 200
    assert r.json()["cancelled"] == 0


# ─── existing retry-failed (regression test for prior behavior) ───────────


async def test_retry_failed_bulk(client):
    await _seed(
        "b",
        [
            ("g1", GranuleState.FAILED.value),
            ("g2", GranuleState.BLACKLISTED.value),
            ("g3", GranuleState.ACKED.value),  # not retryable
        ],
    )
    r = client.post("/api/batches/b/retry-failed")
    assert r.status_code == 200
    assert r.json()["reset"] == 2

    assert await _state("g1") == GranuleState.PENDING.value
    assert await _state("g2") == GranuleState.PENDING.value
    assert await _state("g3") == GranuleState.ACKED.value
