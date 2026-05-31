"""PG-mode heartbeat telemetry write-gating (apply_worker_heartbeat).

In Postgres mode a steady-state beat must NOT rewrite the whole Worker row every
time — that per-beat UPDATE + commit is the dominant PG write load. The row is
persisted only on a material change (live concurrency / pause) or when it's due
(>= _TELEMETRY_PERSIST_SEC since last_seen), so last_seen still advances well
inside acked_orphan_grace_sec. Pure function, no DB needed — is_postgres is
monkeypatched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sathop.orchestrator.api.worker_heartbeat import _TELEMETRY_PERSIST_SEC, apply_worker_heartbeat
from sathop.orchestrator.db import Worker
from sathop.shared.protocol import WorkerHeartbeat

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _worker() -> Worker:
    return Worker(
        worker_id="w1",
        version="1.0.7",
        capacity=6,
        public_url="http://w",
        last_seen=_NOW,
        cpu_percent=0.0,
        live_download_concurrency=2,
        live_process_concurrency=4,
        paused=False,
    )


def _hb(**kw) -> WorkerHeartbeat:
    base = dict(
        worker_id="w1",
        version="1.0.7",
        cpu_percent=0.0,
        paused=False,
        download_concurrency=2,
        process_concurrency=4,
    )
    base.update(kw)
    return WorkerHeartbeat(**base)


def test_steady_state_beat_skips_row_write(monkeypatch):
    monkeypatch.setattr("sathop.orchestrator.db.is_postgres", lambda: True)
    w = _worker()
    # Same instant, nothing material moved → no persist, no commit.
    assert apply_worker_heartbeat(w, _hb(), _NOW) is False

    # Due after the persist window → persist, last_seen + telemetry advance.
    later = _NOW + timedelta(seconds=_TELEMETRY_PERSIST_SEC + 1)
    assert apply_worker_heartbeat(w, _hb(cpu_percent=42.0), later) is True
    assert w.cpu_percent == 42.0
    assert w.last_seen == later

    # Immediately again (not due, unchanged) → skipped, telemetry frozen.
    assert apply_worker_heartbeat(w, _hb(cpu_percent=99.0), later) is False
    assert w.cpu_percent == 42.0


def test_material_change_persists_even_when_not_due(monkeypatch):
    monkeypatch.setattr("sathop.orchestrator.db.is_postgres", lambda: True)
    w = _worker()
    # Live process concurrency moved → material → persist at the same instant.
    assert apply_worker_heartbeat(w, _hb(process_concurrency=8), _NOW) is True
    assert w.live_process_concurrency == 8

    w2 = _worker()
    # Pause state moved → material → persist.
    assert apply_worker_heartbeat(w2, _hb(paused=True), _NOW) is True
    assert w2.paused is True


def test_last_seen_advances_within_orphan_grace(monkeypatch):
    """Across a run of steady beats the row is written at least once per persist
    window, so last_seen never drifts beyond it — the orphan-acked sweep's
    liveness read stays correct."""
    monkeypatch.setattr("sathop.orchestrator.db.is_postgres", lambda: True)
    w = _worker()
    t = _NOW
    persisted = 0
    for _ in range(20):  # 20 beats × 30s = 600s of wall time
        t = t + timedelta(seconds=30)
        if apply_worker_heartbeat(w, _hb(), t):
            persisted += 1
            assert w.last_seen == t
    # 30s beats vs a 45s window → persists at least every other beat.
    assert persisted >= 6
    assert (t - w.last_seen).total_seconds() < _TELEMETRY_PERSIST_SEC
