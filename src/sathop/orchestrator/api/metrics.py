"""Prometheus `/api/metrics` endpoint.

Scrape-driven gauges, rebuilt into a fresh `CollectorRegistry` on a cache miss.
Concurrent scrapes share a snapshot for up to five seconds per process.
Auth: same token as the rest of `/api/*`, also accepts `?token=` so
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
from ..read_cache import AsyncTTLCache

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


async def _collect_pipeline(s: AsyncSession, registry: CollectorRegistry, now: datetime) -> None:
    granules = Gauge("sathop_granules", "Granule count by state", ["state"], registry=registry)
    batches = Gauge("sathop_batches", "Batch count by status", ["status"], registry=registry)
    stuck = Gauge(
        "sathop_granules_stuck",
        f"Granules in a non-terminal state for >{STUCK_AGE_HOURS:g}h, by state",
        ["state"],
        registry=registry,
    )

    state_counts = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state != GranuleState.DELETED.value)
                .group_by(Granule.state)
            )
        ).all()
    }
    # Deleted rows may have been pruned; the batch counter retains the total.
    state_counts["deleted"] = int(
        await s.scalar(select(func.coalesce(func.sum(Batch.delivered_count), 0))) or 0
    )
    # Emit zeroes too, so Prometheus can distinguish zero from a missing series.
    for state in GranuleState:
        granules.labels(state=state.value).set(state_counts.get(state.value, 0))

    batch_counts = (
        await s.execute(select(Batch.status, func.count(Batch.batch_id)).group_by(Batch.status))
    ).all()
    for status, count in batch_counts:
        batches.labels(status=status).set(count)

    stuck_counts = {
        state: count
        for state, count in (
            await s.execute(
                select(Granule.state, func.count(Granule.granule_id))
                .where(Granule.state.in_(NON_TERMINAL))
                .where(Granule.updated_at < now - timedelta(hours=STUCK_AGE_HOURS))
                .where(not_in_paused_batch())  # Paused granules are held, not stuck.
                .group_by(Granule.state)
            )
        ).all()
    }
    for state in NON_TERMINAL:
        stuck.labels(state=state).set(stuck_counts.get(state, 0))


async def _collect_workers(s: AsyncSession, registry: CollectorRegistry, now: datetime) -> None:
    count = Gauge("sathop_workers", "Worker count by enabled flag", ["enabled"], registry=registry)
    heartbeat_age = Gauge(
        "sathop_worker_heartbeat_age_seconds",
        "Seconds since last worker heartbeat",
        ["worker_id"],
        registry=registry,
    )
    disk_used = Gauge(
        "sathop_worker_disk_used_bytes", "Worker disk used bytes", ["worker_id"], registry=registry
    )
    disk_total = Gauge(
        "sathop_worker_disk_total_bytes", "Worker disk total bytes", ["worker_id"], registry=registry
    )
    disk_ratio = Gauge(
        "sathop_worker_disk_used_ratio", "Worker disk used / total ratio", ["worker_id"], registry=registry
    )
    queue = Gauge(
        "sathop_worker_queue", "Worker in-flight items by stage", ["worker_id", "stage"], registry=registry
    )
    egress = Gauge(
        "sathop_worker_egress_bytes_monthly", "Worker monthly egress bytes", ["worker_id"], registry=registry
    )
    workers = (await s.scalars(select(Worker).where(Worker.removed_at.is_(None)))).all()
    paused = sum(bool(worker.operator_paused) for worker in workers)
    count.labels(enabled="true").set(len(workers) - paused)
    count.labels(enabled="false").set(paused)
    for worker in workers:
        # SQLite uses in-memory telemetry; PostgreSQL persists heartbeat fields.
        sample = telemetry.get_worker(worker.worker_id) or worker
        heartbeat_age.labels(worker_id=worker.worker_id).set(_age_seconds(now, sample.last_seen))
        disk_used.labels(worker_id=worker.worker_id).set(sample.disk_used_gb * GB)
        disk_total.labels(worker_id=worker.worker_id).set(sample.disk_total_gb * GB)
        ratio = sample.disk_used_gb / sample.disk_total_gb if sample.disk_total_gb > 0 else 0.0
        disk_ratio.labels(worker_id=worker.worker_id).set(ratio)
        queues = {
            "pending_download": sample.queue_pending_download or 0,
            "downloading": sample.queue_downloading,
            "pending_processing": sample.queue_pending_processing or 0,
            "processing": sample.queue_processing,
            "pending_upload": sample.queue_pending_upload or 0,
            "uploading": sample.queue_uploading,
        }
        for stage, queued in queues.items():
            queue.labels(worker_id=worker.worker_id, stage=stage).set(queued)
        egress.labels(worker_id=worker.worker_id).set(sample.monthly_egress_gb * GB)


async def _collect_receivers(s: AsyncSession, registry: CollectorRegistry, now: datetime) -> None:
    count = Gauge("sathop_receivers", "Receiver count by enabled flag", ["enabled"], registry=registry)
    heartbeat_age = Gauge(
        "sathop_receiver_heartbeat_age_seconds",
        "Seconds since last receiver heartbeat",
        ["receiver_id"],
        registry=registry,
    )
    disk_free = Gauge(
        "sathop_receiver_disk_free_bytes", "Receiver free disk bytes", ["receiver_id"], registry=registry
    )
    pulling = Gauge(
        "sathop_receiver_queue_pulling", "Receiver in-flight pull count", ["receiver_id"], registry=registry
    )
    throughput = Gauge(
        "sathop_receiver_throughput_bytes_per_second",
        "Receiver pull throughput (rolling ~60s) in bytes/sec",
        ["receiver_id"],
        registry=registry,
    )
    receivers = (await s.scalars(select(Receiver))).all()
    enabled = sum(receiver.enabled for receiver in receivers)
    count.labels(enabled="true").set(enabled)
    count.labels(enabled="false").set(len(receivers) - enabled)
    for receiver in receivers:
        sample = telemetry.get_receiver(receiver.receiver_id) or receiver
        heartbeat_age.labels(receiver_id=receiver.receiver_id).set(_age_seconds(now, sample.last_seen))
        disk_free.labels(receiver_id=receiver.receiver_id).set(sample.disk_free_gb * GB)
        pulling.labels(receiver_id=receiver.receiver_id).set(sample.queue_pulling or 0)
        throughput.labels(receiver_id=receiver.receiver_id).set(sample.recent_pull_bps or 0)


async def _collect_events(s: AsyncSession, registry: CollectorRegistry, now: datetime) -> None:
    events = Gauge("sathop_events_24h", "Event count in the last 24h by level", ["level"], registry=registry)
    day_ago = now - timedelta(hours=24)
    counts = (
        await event_store.count_by_level_since_db(s, day_ago)
        if db.is_postgres()
        else event_store.count_by_level_since(day_ago)
    )
    for level in ("info", "warn", "error"):
        events.labels(level=level).set(counts.get(level, 0))


async def _collect(s: AsyncSession) -> bytes:
    registry = CollectorRegistry()
    now = datetime.now(UTC)
    await _collect_pipeline(s, registry, now)
    await _collect_workers(s, registry, now)
    await _collect_receivers(s, registry, now)
    await _collect_events(s, registry, now)
    return generate_latest(registry)


# Bound grouped scans to once per 5s per process, even with multiple scrapers.
_metrics_cache = AsyncTTLCache[bytes](ttl_seconds=5.0)


def reset_metrics_cache() -> None:
    """Drop the cached scrape — used by tests to avoid cross-test staleness."""
    _metrics_cache.clear()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(s: AsyncSession = Depends(session)) -> PlainTextResponse:
    body = await _metrics_cache.get(lambda: _collect(s))
    return PlainTextResponse(content=body, media_type=CONTENT_TYPE_LATEST)
