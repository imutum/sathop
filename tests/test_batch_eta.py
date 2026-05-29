"""Coverage for the per-batch ETA helper that powers BatchSummary.eta_seconds."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.batch_readmodels import (
    eta_seconds,
    state_counts,
    summaries,
    system_delivery_rate,
)
from sathop.orchestrator.db import Batch, Granule, GranuleStageTiming, utcnow
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def db(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "eta.db")
    await orch_db.init_db()
    try:
        yield orch_db
    finally:
        await orch_db.shutdown_db()


async def _seed_batch(batch_id: str, *, in_flight: int, uploads: int, span_sec: float) -> None:
    """Create a batch with `in_flight` PENDING granules and `uploads` closed
    deliver-stage timing rows spanning `span_sec` of wall time. Done granules
    are marked ACKED (delivered) so they don't count toward remaining."""
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id=batch_id, name=batch_id, bundle_ref="local:x"))
        for i in range(in_flight):
            s.add(
                Granule(
                    granule_id=f"{batch_id}:g{i}",
                    batch_id=batch_id,
                    state=GranuleState.PENDING.value,
                    inputs=[],
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
                        inputs=[],
                    )
                )
                started = t0 + timedelta(seconds=span_sec * i / max(uploads - 1, 1))
                finished = started
                s.add(
                    GranuleStageTiming(
                        granule_id=gid,
                        batch_id=batch_id,
                        stage="deliver",
                        started_at=started,
                        finished_at=finished,
                        duration_ms=0,
                    )
                )
        await s.commit()


async def _counts(batch_id: str) -> dict[str, int]:
    async with orch_db._session_maker() as s:
        return (await state_counts(s, [batch_id])).get(batch_id, {})


async def test_empty_returns_empty(db):
    async with orch_db._session_maker() as s:
        assert await eta_seconds(s, {}) == {}


async def test_thin_data_returns_none(db):
    """<3 closed upload stages → None."""
    await _seed_batch("b-thin", in_flight=10, uploads=2, span_sec=60.0)
    counts = {"b-thin": await _counts("b-thin")}
    async with orch_db._session_maker() as s:
        assert await eta_seconds(s, counts) == {"b-thin": None}


async def test_no_in_flight_returns_none(db):
    """Batch with timing data but nothing left to do → None."""
    await _seed_batch("b-done", in_flight=0, uploads=5, span_sec=50.0)
    counts = {"b-done": await _counts("b-done")}
    async with orch_db._session_maker() as s:
        assert await eta_seconds(s, counts) == {"b-done": None}


async def test_healthy_extrapolation(db):
    """5 uploads over 40s @ 10 in-flight → 10 * (40/5) = 80 seconds."""
    await _seed_batch("b-ok", in_flight=10, uploads=5, span_sec=40.0)
    counts = {"b-ok": await _counts("b-ok")}
    async with orch_db._session_maker() as s:
        out = await eta_seconds(s, counts)
    assert out["b-ok"] == 80


async def test_missing_batch_id_returns_none(db):
    """A batch_id not found in timing rows still appears in the output map."""
    async with orch_db._session_maker() as s:
        out = await eta_seconds(s, {"does-not-exist": {}})
    assert out == {"does-not-exist": None}


async def test_uploaded_state_counts_as_remaining(db):
    """UPLOADED granules finished processing but are NOT yet delivered (acked).
    Under delivery-completion they're still remaining: 5 deliveries over 40s @
    1 uploaded → 1 * (40/5) = 8 seconds."""
    await _seed_batch("b-up", in_flight=0, uploads=5, span_sec=40.0)
    async with orch_db._session_maker() as s:
        s.add(
            Granule(
                granule_id="b-up:upl",
                batch_id="b-up",
                state=GranuleState.UPLOADED.value,
                inputs=[],
            )
        )
        await s.commit()
    counts = {"b-up": await _counts("b-up")}
    async with orch_db._session_maker() as s:
        out = await eta_seconds(s, counts)
    assert out["b-up"] == 8


async def test_summaries_realtime_throughput_and_eta(db):
    """Realtime path via summaries(): 5 recent deliveries (60s window) → 5/min;
    remaining-to-deliver = 10 in-flight + 2 uploaded = 12 → eta_realtime =
    12 * 60 / 5 = 144s. Exercises _recent_delivered + _throughput_per_min +
    _eta_from_recent + the uploaded-in-remaining rule together."""
    await _seed_batch("b-rt", in_flight=10, uploads=5, span_sec=40.0)
    async with orch_db._session_maker() as s:
        for i in range(2):
            s.add(
                Granule(
                    granule_id=f"b-rt:up{i}",
                    batch_id="b-rt",
                    state=GranuleState.UPLOADED.value,
                    inputs=[],
                )
            )
        await s.commit()
    async with orch_db._session_maker() as s:
        batch = await s.get(Batch, "b-rt")
        out = (await summaries(s, [batch]))[0]
    assert out.throughput_per_min == 5.0
    assert out.eta_realtime == 144


async def test_summaries_throughput_zero_and_eta_none_when_idle(db):
    """No recent deliveries → throughput is a meaningful 0.0 (not None) and the
    realtime ETA is None (rate unknown)."""
    await _seed_batch("b-idle", in_flight=5, uploads=0, span_sec=0.0)
    async with orch_db._session_maker() as s:
        batch = await s.get(Batch, "b-idle")
        out = (await summaries(s, [batch]))[0]
    assert out.throughput_per_min == 0.0
    assert out.eta_realtime is None


async def test_system_delivery_rate(db):
    """System-wide (dashboard): counts deliver-stage closures across ALL batches
    for throughput, and uses the passed system state_counts for remaining.
    5 recent deliveries → 5/min; remaining = 10 pending + 1 uploaded = 11 →
    eta = 11 * 60 / 5 = 132s."""
    await _seed_batch("b-a", in_flight=10, uploads=5, span_sec=40.0)
    async with orch_db._session_maker() as s:
        s.add(
            Granule(
                granule_id="b-a:up",
                batch_id="b-a",
                state=GranuleState.UPLOADED.value,
                inputs=[],
            )
        )
        await s.commit()
    system_counts = {"pending": 10, "acked": 5, "uploaded": 1}
    async with orch_db._session_maker() as s:
        throughput, eta = await system_delivery_rate(s, system_counts)
    assert throughput == 5.0
    assert eta == 132


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
        out = await eta_seconds(s, counts)
    assert out["b-ok"] == 80
    assert out["b-thin"] is None
    assert out["b-done"] is None
