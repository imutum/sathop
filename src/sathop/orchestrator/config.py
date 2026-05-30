import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import Header, HTTPException, Query, status


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("SATHOP_HOST", "0.0.0.0")
    port: int = int(os.getenv("SATHOP_PORT", "8000"))
    dev: bool = os.getenv("SATHOP_DEV", "0") == "1"
    db_path: Path = Path(os.getenv("SATHOP_DB", "/app/data/orchestrator.db"))
    token: str = os.getenv("SATHOP_TOKEN", "")
    # Multi-process scaling (route A). redis_url empty → single-process,
    # all ephemeral state (pubsub/events/telemetry/progress) stays in-memory.
    # Set it + orch_workers>1 to run N uvicorn workers sharing one Redis bus.
    redis_url: str = os.getenv("SATHOP_REDIS_URL", "")
    orch_workers: int = max(1, int(os.getenv("SATHOP_ORCH_WORKERS", "1")))
    bundle_storage: Path = Path(os.getenv("SATHOP_BUNDLES", "/app/data/bundles"))
    shared_storage: Path = Path(os.getenv("SATHOP_SHARED", "/app/data/shared"))
    retain_events_days: int = int(os.getenv("SATHOP_RETAIN_EVENTS_DAYS", "30"))
    # Cumulative delivered is now a persistent counter, so deleted rows are pure
    # storage and safe to prune sooner (operators can still override / set 0).
    retain_deleted_days: int = int(os.getenv("SATHOP_RETAIN_DELETED_DAYS", "1"))
    retention_sweep_sec: int = int(os.getenv("SATHOP_RETENTION_SWEEP_SEC", "3600"))
    max_inflight_per_worker: int = int(os.getenv("SATHOP_MAX_INFLIGHT_PER_WORKER", "0"))
    # Auto-blacklist threshold: a granule that has failed this many times stops
    # being retried by the lease loop. Operator can still hit "重试" to reset.
    max_retries: int = max(1, int(os.getenv("SATHOP_MAX_RETRIES", "3")))
    # Receivers stop being offered an object after this many pull failures.
    # Otherwise a worker that vanishes (presigned URL unreachable) would have
    # its objects polled forever by every receiver. Operator can still ack
    # success=true to retire an object early; no auto-recovery once exhausted.
    max_pull_failures: int = max(1, int(os.getenv("SATHOP_MAX_PULL_FAILURES", "5")))
    min_worker_version: str = os.getenv("SATHOP_MIN_WORKER_VERSION", "")
    # "Stuck" alarm threshold (hours): a non-terminal granule with no state
    # progress for this long is flagged on the dashboard + /metrics + reconcile.
    # Float so it can be tightened below an hour for live monitoring. This is a
    # coarse "something's wrong" alarm — live bottleneck reading is done off the
    # per-stage WIP numbers, not this threshold.
    stuck_age_hours: float = float(os.getenv("SATHOP_STUCK_AGE_HOURS", "6"))
    # acked→deleted backstop: how long a worker's heartbeat may lapse before the
    # orchestrator treats it as gone and self-confirms the deletion of any ACKED
    # granule it still owns (the worker janitor would otherwise do it). Must comfortably
    # exceed a normal restart/deploy window so a worker mid-restart keeps its own
    # cleanup right. 0 = judge liveness by removed_at / row existence only (most
    # conservative — a stale-but-registered worker still counts as live).
    acked_orphan_grace_sec: int = int(os.getenv("SATHOP_ACKED_ORPHAN_GRACE_SEC", "600"))


settings = Settings()


async def require_token(authorization: str = Header(default="")) -> None:
    if not settings.token:
        return
    if authorization != f"Bearer {settings.token}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


async def require_token_or_query(
    authorization: str = Header(default=""),
    token: str = Query(default=""),
) -> None:
    if not settings.token:
        return
    if authorization == f"Bearer {settings.token}" or token == settings.token:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
