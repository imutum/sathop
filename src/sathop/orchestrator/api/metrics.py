"""Prometheus `/api/metrics` endpoint.

Scrape-driven gauges, rebuilt into a fresh `CollectorRegistry` on every call —
so we snapshot DB state at scrape time and don't carry stale values between
scrapes. Auth: same token as the rest of `/api/*`, also accepts `?token=` so
curl testing and Prometheus `bearer_token_file` both work.

Scrape config example:

    scrape_configs:
      - job_name: sathop
        metrics_path: /api/metrics
        bearer_token: <SATHOP_TOKEN>
        static_configs:
          - targets: ["orchestrator.example.com:8000"]
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import NON_TERMINAL_STATES, GranuleState

from .. import db, event_store, telemetry
from ..config import require_token_or_query, settings
from ..db import Batch, Granule, Receiver, Worker, not_in_paused_batch, session

router = APIRouter(tags=["metrics"], dependencies=[Depends(require_token_or_query)])

GB = 1024**3


def _age_seconds(now: datetime, ts: datetime | None) -> float:
    """SQLite under `DateTime(timezone=True)` can hand back naive datetimes for
    rows written directly via SQLAlchemy — treat those as UTC instead of crashing."""
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return max(0.0, (now - ts).total_seconds())


NON_TERMINAL = set(NON_TERMINAL_STATES)
STUCK_AGE_HOURS = settings.stuck_age_hours


async def _collect(s: AsyncSession) -> bytes:
    reg = CollectorRegistry()

    g_granules = Gauge("sathop_granules", "Granule count by state", ["state"], registry=reg)
    g_batches = Gauge("sathop_batches", "Batch count by status", ["status"], registry=reg)
    g_workers = Gauge("sathop_workers", "Worker count by enabled flag", ["enabled"], registry=reg)
    g_receivers = Gauge("sathop_receivers", "Receiver count by enabled flag", ["enabled"], registry=reg)
    g_hb_worker = Gauge(
        "sathop_worker_heartbeat_age_seconds",
        "Seconds since last worker heartbeat",
        ["worker_id"],
        registry=reg,
    )
    g_hb_receiver = Gauge(
        "sathop_receiver_heartbeat_age_seconds",
        "Seconds since last receiver heartbeat",
        ["receiver_id"],
        registry=reg,
    )
    g_disk_used = Gauge(
        "sathop_worker_disk_used_bytes", "Worker disk used bytes", ["worker_id"], registry=reg
    )
    g_disk_total = Gauge(
        "sathop_worker_disk_total_bytes", "Worker disk total bytes", ["worker_id"], registry=reg
    )
    g_disk_pct = Gauge(
        "sathop_worker_disk_used_ratio", "Worker disk used / total ratio", ["worker_id"], registry=reg
    )
    g_recv_free = Gauge(
        "sathop_receiver_disk_free_bytes", "Receiver free disk bytes", ["receiver_id"], registry=reg
    )
    g_recv_pulling = Gauge(
        "sathop_receiver_queue_pulling",
        "Receiver in-flight pull count",
        ["receiver_id"],
        registry=reg,
    )
    g_recv_bps = Gauge(
        "sathop_receiver_throughput_bytes_per_second",
        "Receiver pull throughput (rolling ~60s) in bytes/sec",
        ["receiver_id"],
        registry=reg,
    )
    g_queue = Gauge(
        "sathop_worker_queue", "Worker in-flight items by stage", ["worker_id", "stage"], registry=reg
    )
    g_egress = Gauge(
        "sathop_worker_egress_bytes_monthly", "Worker monthly egress bytes", ["worker_id"], registry=reg
    )
    g_events24 = Gauge("sathop_events_24h", "Event count in the last 24h by level", ["level"], registry=reg)
    g_stuck = Gauge(
        "sathop_granules_stuck",
        f"Granules in a non-terminal state for >{STUCK_AGE_HOURS:g}h, by state",
        ["state"],
        registry=reg,
    )

    # Granule state counts — seed every state so absent rows still emit 0
    # (otherwise Prometheus can't distinguish "0" from "series never existed").
    state_counts: dict[str, int] = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state != GranuleState.DELETED.value)
                .group_by(Granule.state)
            )
        ).all()
    }
    # deleted = cumulative delivered, from the persistent counter (avoids scanning
    # the huge terminal deleted rows). Still emitted as sathop_granules{state="deleted"}.
    state_counts["deleted"] = int(
        await s.scalar(select(func.coalesce(func.sum(Batch.delivered_count), 0))) or 0
    )
    for st in GranuleState:
        g_granules.labels(state=st.value).set(state_counts.get(st.value, 0))

    batch_counts: dict[str, int] = {
        status: count
        for status, count in (
            await s.execute(select(Batch.status, func.count(Batch.batch_id)).group_by(Batch.status))
        ).all()
    }
    for st, n in batch_counts.items():
        g_batches.labels(status=st).set(n)

    now = datetime.now(UTC)
    workers = (await s.execute(select(Worker))).scalars().all()
    active = [w for w in workers if w.removed_at is None]
    g_workers.labels(enabled="true").set(sum(1 for w in active if not w.operator_paused))
    g_workers.labels(enabled="false").set(sum(1 for w in active if w.operator_paused))
    for w in active:
        wt = telemetry.get_worker(w.worker_id) or w
        g_hb_worker.labels(worker_id=w.worker_id).set(_age_seconds(now, wt.last_seen))
        g_disk_used.labels(worker_id=w.worker_id).set(wt.disk_used_gb * GB)
        g_disk_total.labels(worker_id=w.worker_id).set(wt.disk_total_gb * GB)
        ratio = (wt.disk_used_gb / wt.disk_total_gb) if wt.disk_total_gb > 0 else 0.0
        g_disk_pct.labels(worker_id=w.worker_id).set(ratio)
        g_queue.labels(worker_id=w.worker_id, stage="pending_download").set(wt.queue_pending_download or 0)
        g_queue.labels(worker_id=w.worker_id, stage="downloading").set(wt.queue_downloading)
        g_queue.labels(worker_id=w.worker_id, stage="pending_processing").set(
            wt.queue_pending_processing or 0
        )
        g_queue.labels(worker_id=w.worker_id, stage="processing").set(wt.queue_processing)
        g_queue.labels(worker_id=w.worker_id, stage="pending_upload").set(wt.queue_pending_upload or 0)
        g_queue.labels(worker_id=w.worker_id, stage="uploading").set(wt.queue_uploading)
        g_egress.labels(worker_id=w.worker_id).set(wt.monthly_egress_gb * GB)

    receivers = (await s.execute(select(Receiver))).scalars().all()
    g_receivers.labels(enabled="true").set(sum(1 for r in receivers if r.enabled))
    g_receivers.labels(enabled="false").set(sum(1 for r in receivers if not r.enabled))
    for r in receivers:
        rt = telemetry.get_receiver(r.receiver_id) or r
        g_hb_receiver.labels(receiver_id=r.receiver_id).set(_age_seconds(now, rt.last_seen))
        g_recv_free.labels(receiver_id=r.receiver_id).set(rt.disk_free_gb * GB)
        g_recv_pulling.labels(receiver_id=r.receiver_id).set(rt.queue_pulling or 0)
        g_recv_bps.labels(receiver_id=r.receiver_id).set(rt.recent_pull_bps or 0)

    day_ago = now - timedelta(hours=24)
    if db.is_postgres():
        ev_counts = await event_store.count_by_level_since_db(s, day_ago)
    else:
        ev_counts = event_store.count_by_level_since(day_ago)
    for level in ("info", "warn", "error"):
        g_events24.labels(level=level).set(ev_counts.get(level, 0))

    stuck_threshold = now - timedelta(hours=STUCK_AGE_HOURS)
    stuck: dict[str, int] = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state.in_(list(NON_TERMINAL)))
                .where(Granule.updated_at < stuck_threshold)
                .where(not_in_paused_batch())  # paused-batch granules are held, not stuck
                .group_by(Granule.state)
            )
        ).all()
    }
    for st in NON_TERMINAL:
        g_stuck.labels(state=st).set(stuck.get(st, 0))

    return generate_latest(reg)


# Single-flight scrape cache (mirrors api/admin.py's overview cache). A scrape
# rebuilds the registry and runs two granule GROUP BYs on the one shared aiosqlite
# connection; without this, concurrent scrapes (Prometheus + a curl probe, or two
# Prometheus replicas) each re-run that work and serialize on the connection. The
# 1s window collapses a burst onto one computation while staying real-time enough
# for any sane scrape interval. Set TTL=0 to disable.
_METRICS_TTL = 1.0
_metrics_lock = asyncio.Lock()
_metrics_cache: tuple[float, bytes] | None = None


def reset_metrics_cache() -> None:
    """Drop the cached scrape — used by tests to avoid cross-test staleness."""
    global _metrics_cache
    _metrics_cache = None


async def _cached_collect(s: AsyncSession) -> bytes:
    global _metrics_cache
    if _METRICS_TTL > 0 and _metrics_cache is not None:
        ts, body = _metrics_cache
        if time.monotonic() - ts < _METRICS_TTL:
            return body
    async with _metrics_lock:
        if _METRICS_TTL > 0 and _metrics_cache is not None:
            ts, body = _metrics_cache
            if time.monotonic() - ts < _METRICS_TTL:
                return body
        body = await _collect(s)
        _metrics_cache = (time.monotonic(), body)
        return body


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(s: AsyncSession = Depends(session)) -> PlainTextResponse:
    body = await _cached_collect(s)
    return PlainTextResponse(content=body, media_type=CONTENT_TYPE_LATEST)
