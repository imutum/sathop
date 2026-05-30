"""Coverage for the realtime ETA + throughput that power BatchSummary.

The historical `eta_seconds` (whole-history min/max/sum scan) was removed; ETA is
now realtime-only — extrapolated from deliveries in the recent rolling window via
`_recent_delivered` + `_eta_from_recent`. These tests exercise that path through
`summaries()` and the dashboard's `system_delivery_rate()`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.batch_readmodels import (
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
    deliver-stage timing rows spanning `span_sec` of wall time, all finishing at
    ~now so they fall inside the recent window. Done granules are ACKED so they
    don't count toward remaining."""
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
                s.add(
                    GranuleStageTiming(
                        granule_id=gid,
                        batch_id=batch_id,
                        stage="deliver",
                        started_at=started,
                        finished_at=started,
                        duration_ms=0,
                    )
                )
        await s.commit()


async def _counts(batch_id: str) -> dict[str, int]:
    async with orch_db._session_maker() as s:
        return (await state_counts(s, [batch_id])).get(batch_id, {})


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


async def test_summaries_eta_none_when_nothing_remaining(db):
    """Recent deliveries but nothing left to deliver → eta_realtime is None even
    though throughput is non-zero (counts down to delivery, and there's nothing
    to count down)."""
    await _seed_batch("b-fin", in_flight=0, uploads=5, span_sec=40.0)
    async with orch_db._session_maker() as s:
        batch = await s.get(Batch, "b-fin")
        out = (await summaries(s, [batch]))[0]
    assert out.throughput_per_min == 5.0
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
    """Mixed batches in one summaries() call: each realtime figure is computed
    independently and zipped back in input order. b-rt: 5 recent deliveries →
    5/min, 10 in-flight remaining → 10 * 60 / 5 = 120s. b-idle: no deliveries →
    None."""
    await _seed_batch("b-rt", in_flight=10, uploads=5, span_sec=40.0)
    await _seed_batch("b-idle", in_flight=5, uploads=0, span_sec=0.0)
    async with orch_db._session_maker() as s:
        batches = [await s.get(Batch, "b-rt"), await s.get(Batch, "b-idle")]
        out = await summaries(s, batches)
    by_id = {o.batch_id: o for o in out}
    assert by_id["b-rt"].eta_realtime == 120
    assert by_id["b-idle"].eta_realtime is None
