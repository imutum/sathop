from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from sathop.shared.safe_path import is_safe_name
from sathop.shared.state_machine import GranuleState  # noqa: F401  — re-export for callers


class WorkerRegister(BaseModel):
    worker_id: str
    version: str = ""
    capacity: int = 20
    public_url: str | None = None
    # Self-signed root CA (PEM) the worker is fronted by — uploaded so the
    # orchestrator can hand it to receivers via /api/receivers/ca-bundle. None
    # for workers behind a publicly-trusted cert (Let's Encrypt) or plain HTTP.
    ca_pem: str | None = None


class Credential(BaseModel):
    """Named credential set carried on each batch. Bundles declare which names
    they need in `manifest.requirements.credentials`; individual `InputSpec`s
    pick one by name for their download.

    Schemes:
      - basic:  HTTP Basic Auth via `username`/`password`
      - bearer: `Authorization: Bearer <token>` header via `token`
                (NASA LADSWeb EDL App Token, GitHub PAT, etc.)
    """

    name: str
    scheme: Literal["basic", "bearer"] = "basic"
    username: str | None = None
    password: str | None = None
    token: str | None = None


class WorkerRegisterResponse(BaseModel):
    ok: bool = True


class WorkerHeartbeatResponse(BaseModel):
    ok: bool = True
    # Operator overrides pushed from the worker row; None = use worker env default.
    download_concurrency: int | None = None
    process_concurrency: int | None = None
    revoked_granule_ids: list[str] = Field(default_factory=list)
    update_requested: bool = False
    operator_paused: bool = False
    gc_requested: bool = False
    removed: bool = False


class WorkerHeartbeat(BaseModel):
    worker_id: str
    # Carried on every heartbeat so the orchestrator can spot version flapping
    # — two containers with the same worker_id sharing the volume (orphan from a
    # botched compose redeploy) cause subtle bugs (concurrent .part writes,
    # mixed TLS trust modes); a flapping `version` field is the cheapest signal.
    version: str = ""
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    monthly_egress_gb: float = 0.0
    # Granules leased + handler running but blocked on the download semaphore
    # (i.e. state=queued in the orchestrator's view).
    # 6 个 worker-side 阶段 — UI 平铺显示，分别对应：
    #   待下载: lease 后等 download_sem
    #   下载中: 在拉源数据
    #   待处理: 下完了等 process_sem（CPU 槽位）
    #   处理中: run_bundle 在跑
    #   待上传: 处理完了等 upload_sem（带宽/MinIO 槽位）
    #   上传中: 产物上传本机存储 / MinIO
    # 全局/批次阶段（待分配/待分发/待清理/已完成/待重试）由 DB GranuleState
    # 直接 query，不在 heartbeat 里冗余。
    queue_pending_download: int = 0
    queue_downloading: int = 0
    queue_pending_processing: int = 0
    queue_processing: int = 0
    queue_pending_upload: int = 0
    queue_uploading: int = 0
    # Live applied concurrency the worker is currently running with, so the
    # orchestrator/UI see ground truth instead of reverse-engineering from queue
    # peaks. Default 0 so old/edge payloads still parse.
    download_concurrency: int = 0
    process_concurrency: int = 0
    # True while the worker is gating off new leases for any reason (currently
    # disk-watermark backpressure). Surfaces to operators so an "online but
    # idle" worker doesn't look like the orchestrator is starving it.
    paused: bool = False
    # Granule IDs the worker currently has an active asyncio handler task for.
    # Orchestrator diff-checks against DB (state in LEASED_STATES, leased_by =
    # this worker) and returns any stragglers as `revoked_granule_ids` so the
    # worker can cancel ghost work after a batch/granule cancel.
    active_granule_ids: list[str] = Field(default_factory=list)


class ReceiverRegister(BaseModel):
    receiver_id: str
    version: str = ""
    platform: Literal["linux", "windows"] = "linux"


class ReceiverHeartbeat(BaseModel):
    receiver_id: str
    # Carried on every heartbeat so the orchestrator can spot version flapping
    # — see WorkerHeartbeat.version note. Same orphan-container scenario.
    version: str = ""
    disk_free_gb: float = 0.0
    # Number of pulls currently in flight (mirrors worker.queue_*). Lets
    # operators tell "idle" from "actively pulling" without watching logs.
    queue_pulling: int = 0
    # Bytes pulled in the recent rolling window (~60s) reported by the receiver
    # — divide by the window for MB/s. Persisted as the latest sample, not a
    # counter; next heartbeat overwrites.
    recent_pull_bps: int = 0


class ReceiverHeartbeatResponse(BaseModel):
    ok: bool = True
    # One-shot restart signal — see WorkerHeartbeatResponse.restart_requested.
    restart_requested: bool = False


class InputSpec(BaseModel):
    """One input file the worker must fetch before running the bundle."""

    url: str
    filename: str
    product: str
    size: int | None = None
    checksum: str | None = None
    credential: str | None = None

    @field_validator("filename")
    @classmethod
    def _no_path_traversal(cls, v: str) -> str:
        if not is_safe_name(v):
            raise ValueError(f"filename must be a single safe segment (no '/', '\\', '..'); got {v!r}")
        return v


class GranuleCreate(BaseModel):
    granule_id: str
    inputs: list[InputSpec]
    meta: dict = Field(default_factory=dict)


class BatchCreate(BaseModel):
    # 可选：None ⇒ orchestrator 自动生成 8 字符 URL-safe 随机 ID。Web UI 走这条
    # 路径（用户只填 name 展示名）；CLI 或脚本仍可显式指定 ID 做幂等创建。
    batch_id: str | None = None
    name: str
    bundle_ref: str
    target_receiver_id: str | None = None
    granules: list[GranuleCreate] = Field(default_factory=list)
    # Per-batch env overrides merged over bundle's execution.env. Lets one bundle
    # power multiple task flows (e.g. same resampler with SATHOP_FACTOR=2 vs 4).
    execution_env: dict[str, str] = Field(default_factory=dict)
    # Per-batch credentials, keyed by name. `InputSpec.credential` + bundle
    # `requirements.credentials` pick from this map. Carried on every lease
    # item — no central registry, no hot-rotation path; rotate by creating a
    # new batch.
    credentials: dict[str, Credential] = Field(default_factory=dict)


class BatchSummary(BaseModel):
    batch_id: str
    name: str
    bundle_ref: str
    target_receiver_id: str | None
    status: str
    created_at: datetime
    counts: dict[str, int]
    # Count of this batch's still-pending objects whose receiver pulls hit
    # max_pull_failures. Computed authoritatively by the orchestrator (one
    # query, all granules) so a >200-granule batch's stuck-delivery signal
    # surfaces in the listing without relying on the client-side granule page.
    objects_exhausted: int = 0
    # Wall-clock-extrapolated remaining seconds; None when sample <3 deliveries
    # or nothing left to deliver. Both ETAs count down to delivery (acked), the
    # batch's "done" definition — remaining includes the uploaded-but-not-yet-
    # delivered backlog.
    eta_seconds: int | None = None
    eta_realtime: int | None = None
    # Recent delivery throughput (granules acked per minute, rolling window).
    # 0.0 when nothing delivered recently (a stalled-delivery signal); None on
    # a freshly-created batch with no data yet.
    throughput_per_min: float | None = None


class GranuleBulkAdd(BaseModel):
    granules: list[GranuleCreate]


class GranuleRow(BaseModel):
    """Operator-facing snapshot of one granule. Returned by the listing endpoint
    that powers the Web UI's batch-detail page."""

    granule_id: str
    batch_id: str
    state: str
    retry_count: int
    leased_by: str | None
    error: str | None
    # Bundle subprocess output tails captured on the failing attempt; None on
    # success or for granules that haven't failed yet. Lets the UI surface
    # bundle prints/tracebacks without operators ssh'ing into a worker.
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    updated_at: datetime
    # Count of this granule's objects that have hit max_pull_failures and are
    # no longer offered to receivers. Lets the UI flag granules stuck in
    # UPLOADED whose downstream delivery has effectively given up.
    objects_exhausted: int = 0


class LeaseRequest(BaseModel):
    worker_id: str
    capacity: int


class LeaseItem(BaseModel):
    granule_id: str
    batch_id: str
    bundle_ref: str
    inputs: list[InputSpec]
    meta: dict
    execution_env: dict[str, str] = Field(default_factory=dict)
    # Per-batch credential map — worker uses this (only) to authenticate
    # downloads keyed by `InputSpec.credential`.
    credentials: dict[str, Credential] = Field(default_factory=dict)


class LeaseResponse(BaseModel):
    items: list[LeaseItem]
    lease_expires_at: datetime


class PullItem(BaseModel):
    granule_id: str
    batch_id: str
    object_id: int
    object_key: str
    presigned_url: str
    sha256: str
    size: int


class PullRequest(BaseModel):
    receiver_id: str
    limit: int = 20


class PullResponse(BaseModel):
    items: list[PullItem]


class AckReport(BaseModel):
    receiver_id: str
    object_id: int
    sha256: str
    success: bool
    error: str | None = None


class DeletableGranule(BaseModel):
    granule_id: str
    object_keys: list[str]


class BundleSummary(BaseModel):
    name: str
    version: str
    sha256: str
    size: int
    description: str | None = None
    uploaded_at: datetime
    # How many batches reference this bundle. Orchestrator computes; worker doesn't read.
    # Lets the registry UI show "safe to delete?" at a glance.
    in_use_count: int = 0


class BundleDetail(BundleSummary):
    """Full entry including the parsed manifest — drives the UI's bundle page."""

    manifest: dict


class ProgressEvent(BaseModel):
    """Bundle-reported checkpoint. Bundle POSTs this to the URL in
    $SATHOP_PROGRESS_URL whenever it finishes a logical step (read, resample,
    write, ...). `ts` is orchestrator-assigned if omitted."""

    step: str
    pct: float | None = None
    detail: str | None = None
    ts: datetime | None = None
    batch_id: str | None = None
