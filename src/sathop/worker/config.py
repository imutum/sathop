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
    pipeline_pressure_mult: int

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
    cpus = os.cpu_count() or 1
    mult_default = max(1, int(os.getenv("SATHOP_PIPELINE_PRESSURE_MULT", "3")))
    # Default capacity matches worker's internal pipeline ceiling
    # (process_concurrency × pipeline_pressure_mult). The old fixed 20 made
    # 8-vCPU workers request 20 leases at once, but the process semaphore
    # then only ran 8 in parallel — the surplus 12 sat queued, and on a
    # batch cancel the operator had to wait for ghost work on all 20 to
    # clear. Aligning capacity with ceiling keeps the queue tight.
    return Settings(
        worker_id=os.environ["SATHOP_WORKER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        capacity=max(1, int(os.getenv("SATHOP_CAPACITY", str(cpus * mult_default)))),
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
        download_concurrency=max(1, int(os.getenv("SATHOP_DOWNLOAD_CONCURRENCY", "2"))),
        # process 是 CPU 密集型 — 默认 = vCPU 数。让多个粒并行 process 只会
        # 线性拉长每个粒的耗时（实测 6 并发下单粒 6 min，限到 vCPU 后 ~1 min）。
        process_concurrency=max(1, int(os.getenv("SATHOP_PROCESS_CONCURRENCY", str(os.cpu_count() or 1)))),
        # in-flight 上限相对 process_concurrency 的倍数。orchestrator 可通过
        # PUT /workers/{id}/pipeline-mult 下发覆盖（worker 取 min(env, desired)）。
        pipeline_pressure_mult=max(1, int(os.getenv("SATHOP_PIPELINE_PRESSURE_MULT", "3"))),
        aria2_rpc=os.getenv("SATHOP_ARIA2_RPC", ""),
        aria2_secret=os.getenv("SATHOP_ARIA2_SECRET", ""),
        minio_access_key=os.getenv("SATHOP_MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.getenv("SATHOP_MINIO_SECRET_KEY", ""),
        minio_bucket=os.getenv("SATHOP_MINIO_BUCKET", "sathop"),
        disk_pause_pct=float(os.getenv("SATHOP_DISK_PAUSE_PCT", "0.85")),
        disk_resume_pct=float(os.getenv("SATHOP_DISK_RESUME_PCT", "0.70")),
        backpressure_interval=int(os.getenv("SATHOP_BACKPRESSURE_INTERVAL", "10")),
        tls_cert_path=Path(os.getenv("SATHOP_TLS_CERT", "./data/tls/cert.pem")),
        tls_key_path=Path(os.getenv("SATHOP_TLS_KEY", "./data/tls/key.pem")),
    )
