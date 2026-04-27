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
