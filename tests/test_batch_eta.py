"""Coverage for `_eta_seconds_bulk` — the per-batch ETA helper that powers
BatchSummary.eta_seconds in both list and detail responses."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.batches import _eta_seconds_bulk
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, GranuleStageTiming, utcnow
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def db(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "eta.db")
    await orch_db.init_db()
    try:
        yield orch_db
    finally:
        await orch_db.shutdown_db()


async def _seed_batch(batch_id: str, *, in_flight: int, uploads: int, span_sec: float) -> None:
    """Create a batch with `in_flight` PENDING granules and `uploads` closed
    upload-stage timing rows spanning `span_sec` of wall time. Done granules
    are marked ACKED so they don't count toward in-flight."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name=batch_id, bundle_ref="local:x"))
        for i in range(in_flight):
            s.add(
                Granule(
                    granule_id=f"{batch_id}:g{i}",
                    batch_id=batch_id,
                    state=GranuleState.PENDING.value,
                    inputs_json="[]",
                )
            )
        if uploads > 0:
            t0 = utcnow()
            for i in range(uploads):
                gid = f"{batch_id}:done{i}"
                s.add(
                    Granule(
                        granule_id=gid,
                        batch_id=batch_id,
                        state=GranuleState.ACKED.value,
                        inputs_json="[]",
                    )
                )
                started = t0 + timedelta(seconds=span_sec * i / max(uploads - 1, 1))
                finished = started
                s.add(
                    GranuleStageTiming(
                        granule_id=gid,
                        batch_id=batch_id,
                        stage="upload",
                        started_at=started,
                        finished_at=finished,
                        duration_ms=0,
                    )
                )
        await s.commit()


async def _counts(batch_id: str) -> dict[str, int]:
    from sathop.orchestrator.api.batches import _counts as real_counts

    async with orch_db._session_maker() as s:
        return await real_counts(s, batch_id)


async def test_empty_returns_empty(db):
    async with orch_db._session_maker() as s:
        assert await _eta_seconds_bulk(s, {}) == {}


async def test_thin_data_returns_none(db):
    """<3 closed upload stages → None."""
    await _seed_batch("b-thin", in_flight=10, uploads=2, span_sec=60.0)
    counts = {"b-thin": await _counts("b-thin")}
    async with orch_db._session_maker() as s:
        assert await _eta_seconds_bulk(s, counts) == {"b-thin": None}


async def test_no_in_flight_returns_none(db):
    """Batch with timing data but nothing left to do → None."""
    await _seed_batch("b-done", in_flight=0, uploads=5, span_sec=50.0)
    counts = {"b-done": await _counts("b-done")}
    async with orch_db._session_maker() as s:
        assert await _eta_seconds_bulk(s, counts) == {"b-done": None}


async def test_healthy_extrapolation(db):
    """5 uploads over 40s @ 10 in-flight → 10 * (40/5) = 80 seconds."""
    await _seed_batch("b-ok", in_flight=10, uploads=5, span_sec=40.0)
    counts = {"b-ok": await _counts("b-ok")}
    async with orch_db._session_maker() as s:
        out = await _eta_seconds_bulk(s, counts)
    assert out["b-ok"] == 80


async def test_missing_batch_id_returns_none(db):
    """A batch_id not found in timing rows still appears in the output map."""
    async with orch_db._session_maker() as s:
        out = await _eta_seconds_bulk(s, {"does-not-exist": {}})
    assert out == {"does-not-exist": None}


async def test_uploaded_state_not_in_remaining(db):
    """UPLOADED granules already finished the upload stage (counted in done_n);
    counting them again as remaining would double-count and inflate ETA."""
    await _seed_batch("b-up", in_flight=0, uploads=5, span_sec=40.0)
    async with orch_db._session_maker() as s:
        s.add(
            Granule(
                granule_id="b-up:upl",
                batch_id="b-up",
                state=GranuleState.UPLOADED.value,
                inputs_json="[]",
            )
        )
        await s.commit()
    counts = {"b-up": await _counts("b-up")}
    async with orch_db._session_maker() as s:
        out = await _eta_seconds_bulk(s, counts)
    assert out["b-up"] is None


async def test_bulk_independence(db):
    """Mixed batch in one call: each is computed independently."""
    await _seed_batch("b-ok", in_flight=10, uploads=5, span_sec=40.0)
    await _seed_batch("b-thin", in_flight=10, uploads=2, span_sec=60.0)
    await _seed_batch("b-done", in_flight=0, uploads=5, span_sec=50.0)
    counts = {
        "b-ok": await _counts("b-ok"),
        "b-thin": await _counts("b-thin"),
        "b-done": await _counts("b-done"),
    }
    async with orch_db._session_maker() as s:
        out = await _eta_seconds_bulk(s, counts)
    assert out["b-ok"] == 80
    assert out["b-thin"] is None
    assert out["b-done"] is None
