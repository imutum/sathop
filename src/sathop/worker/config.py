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
    download_concurrency: int
    process_concurrency: int
    # Upload concurrency cap. LocalStorage uploads are essentially free
    # (host-local cp), but MinIO-over-WAN uploads can saturate the worker's
    # uplink and starve the receiver's pull bandwidth. Defaults to
    # process_concurrency so an unconfigured worker behaves identically to
    # before this knob existed.
    upload_concurrency: int

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

    # Local cache GC. 0 = disable. venv + bundle source dirs accumulate
    # per-version (~200-500 MB each for typical satellite bundles), so an
    # operator who keeps bumping versions during dev will fill the disk
    # within weeks. The GC loop walks venv_cache + bundle_cache periodically
    # and evicts the oldest (by ensure() last-used sidecar) until total
    # drops below the limit. Active bundles never evict — ensure() refreshes
    # their mtime on every lease.
    venv_cache_limit_gb: float
    gc_interval_sec: int

    # Self-signed TLS cert + key for the storage server. Generated on first
    # boot (see worker.tls) when SATHOP_PUBLIC_URL is https://; the cert
    # doubles as the ca_pem uploaded at register time. Operator can supply
    # their own publicly-trusted cert by pointing these at existing files.
    tls_cert_path: Path
    tls_key_path: Path

    @property
    def use_aria2(self) -> bool:
        return bool(self.aria2_rpc)

    @property
    def use_minio(self) -> bool:
        return bool(self.minio_access_key and self.minio_secret_key)


def load() -> Settings:
    orchestrator_url, token = resolve_orch()
    download_conc = max(1, int(os.getenv("SATHOP_DOWNLOAD_CONCURRENCY", "2")))
    process_conc = max(1, int(os.getenv("SATHOP_PROCESS_CONCURRENCY", str(os.cpu_count() or 1))))
    upload_conc = max(1, int(os.getenv("SATHOP_UPLOAD_CONCURRENCY", str(process_conc))))
    # In-flight ceiling = download_sem + process_sem (the two physical bottlenecks
    # in the pipeline). Lease capacity defaults to the same number — pulling more
    # would just queue work behind the semaphores, fragmenting visibility ("待下载
    # 10 / 下载中 2" pattern) and starving other workers in a multi-node setup.
    # Operator widens download_concurrency or process_concurrency to scale; no
    # separate "pipeline depth multiplier" knob to misconfigure.
    return Settings(
        worker_id=os.environ["SATHOP_WORKER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        capacity=max(1, int(os.getenv("SATHOP_CAPACITY", str(download_conc + process_conc)))),
        public_url=os.environ["SATHOP_PUBLIC_URL"].rstrip("/"),
        work_root=Path(os.getenv("SATHOP_WORK_ROOT", "/app/data/work")),
        bundle_cache=Path(os.getenv("SATHOP_BUNDLE_CACHE", "/app/data/bundles")),
        venv_cache=Path(os.getenv("SATHOP_VENV_CACHE", "/app/data/venvs")),
        shared_cache=Path(os.getenv("SATHOP_SHARED_CACHE", "/app/data/shared")),
        storage_root=Path(os.getenv("SATHOP_STORAGE_ROOT", "/app/data/storage")),
        storage_port=int(os.getenv("SATHOP_STORAGE_PORT", "9000")),
        progress_port=int(os.getenv("SATHOP_PROGRESS_PORT", "9002")),
        heartbeat_interval=int(os.getenv("SATHOP_HEARTBEAT", "15")),
        lease_poll_interval=int(os.getenv("SATHOP_LEASE_POLL", "10")),
        download_concurrency=download_conc,
        process_concurrency=process_conc,
        upload_concurrency=upload_conc,
        aria2_rpc=os.getenv("SATHOP_ARIA2_RPC", ""),
        aria2_secret=os.getenv("SATHOP_ARIA2_SECRET", ""),
        minio_access_key=os.getenv("SATHOP_MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.getenv("SATHOP_MINIO_SECRET_KEY", ""),
        minio_bucket=os.getenv("SATHOP_MINIO_BUCKET", "sathop"),
        disk_pause_pct=float(os.getenv("SATHOP_DISK_PAUSE_PCT", "0.85")),
        disk_resume_pct=float(os.getenv("SATHOP_DISK_RESUME_PCT", "0.70")),
        backpressure_interval=int(os.getenv("SATHOP_BACKPRESSURE_INTERVAL", "10")),
        venv_cache_limit_gb=float(os.getenv("SATHOP_VENV_CACHE_LIMIT_GB", "10")),
        gc_interval_sec=int(os.getenv("SATHOP_GC_INTERVAL", "3600")),
        tls_cert_path=Path(os.getenv("SATHOP_TLS_CERT", "/app/data/tls/cert.pem")),
        tls_key_path=Path(os.getenv("SATHOP_TLS_KEY", "/app/data/tls/key.pem")),
    )
