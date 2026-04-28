import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import Header, HTTPException, Query, status


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("SATHOP_HOST", "0.0.0.0")
    port: int = int(os.getenv("SATHOP_PORT", "8000"))
    dev: bool = os.getenv("SATHOP_DEV", "0") == "1"
    db_path: Path = Path(os.getenv("SATHOP_DB", "./data/orchestrator.db"))
    token: str = os.getenv("SATHOP_TOKEN", "")
    bundle_storage: Path = Path(os.getenv("SATHOP_BUNDLES", "./data/bundles"))
    shared_storage: Path = Path(os.getenv("SATHOP_SHARED", "./data/shared"))
    retain_events_days: int = int(os.getenv("SATHOP_RETAIN_EVENTS_DAYS", "30"))
    retain_deleted_days: int = int(os.getenv("SATHOP_RETAIN_DELETED_DAYS", "7"))
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
