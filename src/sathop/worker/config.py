import os
from dataclasses import dataclass
from pathlib import Path

from sathop.shared.config import resolve_orch


@dataclass(frozen=True)
class Settings:
    worker_id: str
    orchestrator_url: str
    token: str
    capacity: int
    public_url: str
    work_root: Path
    bundle_cache: Path
    venv_cache: Path
    shared_cache: Path
    storage_root: Path
    storage_port: int
    progress_port: int
    heartbeat_interval: int
    lease_poll_interval: int

    # Production-mode toggles. Empty = MVP fallback (httpx / local FS static server).
    aria2_rpc: str
    aria2_secret: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str

    # Backpressure: pause new leases above disk_pause_pct, resume below disk_resume_pct.
    disk_pause_pct: float
    disk_resume_pct: float
    backpressure_interval: int

    @property
    def use_aria2(self) -> bool:
        return bool(self.aria2_rpc)

    @property
    def use_minio(self) -> bool:
        return bool(self.minio_access_key and self.minio_secret_key)


def load() -> Settings:
    orchestrator_url, token = resolve_orch()
    return Settings(
        worker_id=os.environ["SATHOP_WORKER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        capacity=int(os.getenv("SATHOP_CAPACITY", "20")),
        public_url=os.environ["SATHOP_PUBLIC_URL"].rstrip("/"),
        work_root=Path(os.getenv("SATHOP_WORK_ROOT", "./data/work")),
        bundle_cache=Path(os.getenv("SATHOP_BUNDLE_CACHE", "./data/bundles")),
        venv_cache=Path(os.getenv("SATHOP_VENV_CACHE", "./data/venvs")),
        shared_cache=Path(os.getenv("SATHOP_SHARED_CACHE", "./data/shared")),
        storage_root=Path(os.getenv("SATHOP_STORAGE_ROOT", "./data/storage")),
        storage_port=int(os.getenv("SATHOP_STORAGE_PORT", "9000")),
        progress_port=int(os.getenv("SATHOP_PROGRESS_PORT", "9002")),
        heartbeat_interval=int(os.getenv("SATHOP_HEARTBEAT", "15")),
        lease_poll_interval=int(os.getenv("SATHOP_LEASE_POLL", "10")),
        aria2_rpc=os.getenv("SATHOP_ARIA2_RPC", ""),
        aria2_secret=os.getenv("SATHOP_ARIA2_SECRET", ""),
        minio_access_key=os.getenv("SATHOP_MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.getenv("SATHOP_MINIO_SECRET_KEY", ""),
        minio_bucket=os.getenv("SATHOP_MINIO_BUCKET", "sathop"),
        disk_pause_pct=float(os.getenv("SATHOP_DISK_PAUSE_PCT", "0.85")),
        disk_resume_pct=float(os.getenv("SATHOP_DISK_RESUME_PCT", "0.70")),
        backpressure_interval=int(os.getenv("SATHOP_BACKPRESSURE_INTERVAL", "10")),
    )
