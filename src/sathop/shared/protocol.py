from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class GranuleState(str, Enum):
    PENDING = "pending"
    # Lease succeeded but the worker is still waiting on its local download
    # semaphore (SATHOP_DOWNLOAD_CONCURRENCY). Distinct from DOWNLOADING so the
    # UI doesn't show 40 "downloading" rows when only 1 byte is actually moving.
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    UPLOADED = "uploaded"
    ACKED = "acked"
    DELETED = "deleted"
    FAILED = "failed"
    BLACKLISTED = "blacklisted"


# Worker holds an active lease in any of these — the row will be reclaimed by
# the lease sweeper if the lease expires.
LEASED_STATES: tuple[str, ...] = (
    GranuleState.QUEUED.value,
    GranuleState.DOWNLOADING.value,
    GranuleState.DOWNLOADED.value,
    GranuleState.PROCESSING.value,
    GranuleState.PROCESSED.value,
)

# Worker pipeline still has work to do (LEASED_STATES + PENDING). Excludes
# UPLOADED (worker done, waiting on receiver) and terminal/error states.
# Frontend mirrors this in `frontend/src/api.ts` (IN_FLIGHT_STATES).
IN_FLIGHT_STATES: tuple[str, ...] = (GranuleState.PENDING.value, *LEASED_STATES)

# Everything that isn't terminal (DELETED) or errored (FAILED, BLACKLISTED).
# Used for stuck-granule queries and Prometheus non-terminal counts.
NON_TERMINAL_STATES: tuple[str, ...] = (
    *IN_FLIGHT_STATES,
    GranuleState.UPLOADED.value,
    GranuleState.ACKED.value,
)


class WorkerRegister(BaseModel):
    worker_id: str
    version: str = ""
    capacity: int = 20
    public_url: str | None = None


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
    # None ⇒ no override; worker clamps env capacity by this if set.
    desired_capacity: int | None = None


class WorkerHeartbeat(BaseModel):
    worker_id: str
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    monthly_egress_gb: float = 0.0
    # Granules leased + handler running but blocked on the download semaphore
    # (i.e. state=queued in the orchestrator's view).
    queue_queued: int = 0
    queue_downloading: int = 0
    queue_processing: int = 0
    queue_uploading: int = 0
    # True while the worker is gating off new leases for any reason (currently
    # disk-watermark backpressure). Surfaces to operators so an "online but
    # idle" worker doesn't look like the orchestrator is starving it.
    paused: bool = False


class ReceiverRegister(BaseModel):
    receiver_id: str
    version: str = ""
    platform: Literal["linux", "windows"] = "linux"


class ReceiverHeartbeat(BaseModel):
    receiver_id: str
    disk_free_gb: float = 0.0
    # Number of pulls currently in flight (mirrors worker.queue_*). Lets
    # operators tell "idle" from "actively pulling" without watching logs.
    queue_pulling: int = 0
    # Bytes pulled in the recent rolling window (~60s) reported by the receiver
    # — divide by the window for MB/s. Persisted as the latest sample, not a
    # counter; next heartbeat overwrites.
    recent_pull_bps: int = 0


class InputSpec(BaseModel):
    """One input file the worker must fetch before running the bundle."""

    url: str
    filename: str
    product: str
    size: int | None = None
    checksum: str | None = None
    credential: str | None = None


class GranuleCreate(BaseModel):
    granule_id: str
    inputs: list[InputSpec]
    meta: dict = Field(default_factory=dict)


class BatchCreate(BaseModel):
    batch_id: str
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
    # Wall-clock-extrapolated remaining seconds; None when sample <3 uploads
    # or no in-flight granules.
    eta_seconds: int | None = None


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


class UploadedObject(BaseModel):
    object_key: str
    presigned_url: str
    sha256: str
    size: int


class UploadReport(BaseModel):
    granule_id: str
    worker_id: str
    objects: list[UploadedObject]


class ProcessFailure(BaseModel):
    granule_id: str
    worker_id: str
    error: str
    exit_code: int | None = None


class StateUpdate(BaseModel):
    """Worker-reported phase boundary for a leased granule. The endpoint accepts
    forward transitions through `downloading → downloaded → processing →
    processed`; `queued` is written by lease and `uploaded` by the upload
    endpoint."""

    granule_id: str
    worker_id: str
    state: GranuleState


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
