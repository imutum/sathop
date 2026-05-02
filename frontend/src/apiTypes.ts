// Shared types that mirror the backend protocol models.

export type GranuleState =
  | "pending"
  | "queued"
  | "downloading"
  | "downloaded"
  | "processing"
  | "processed"
  | "uploaded"
  | "acked"
  | "deleted"
  | "failed"
  | "blacklisted";

// Worker pipeline still has work to do; mirrors `IN_FLIGHT_STATES` in
// shared/protocol.py. Used for batch progress, ETA, and cancel/reset gates.
export const IN_FLIGHT_STATES: GranuleState[] = [
  "pending",
  "queued",
  "downloading",
  "downloaded",
  "processing",
  "processed",
];

// Happy-path state sequence used for chart ordering and dashboard rollups.
export const STATE_ORDER: GranuleState[] = [
  ...IN_FLIGHT_STATES,
  "uploaded",
  "acked",
  "deleted",
];

export type BatchSummary = {
  batch_id: string;
  name: string;
  bundle_ref: string;
  target_receiver_id: string | null;
  status: string;
  created_at: string;
  counts: Partial<Record<GranuleState, number>>;
  objects_exhausted: number;
  eta_seconds: number | null;
};

export type WorkerInfo = {
  worker_id: string;
  version: string;
  capacity: number;
  public_url: string | null;
  last_seen: string;
  disk_used_gb: number;
  disk_total_gb: number;
  cpu_percent: number;
  mem_percent: number;
  monthly_egress_gb: number;
  queue_queued: number;
  queue_downloading: number;
  queue_processing: number;
  queue_uploading: number;
  enabled: boolean;
  paused: boolean;
  desired_capacity: number | null;
};

export type ReceiverInfo = {
  receiver_id: string;
  version: string;
  platform: "linux" | "windows";
  last_seen: string;
  disk_free_gb: number;
  enabled: boolean;
  queue_pulling: number;
  recent_pull_bps: number;
};

export type EventRow = {
  id: number;
  ts: string;
  level: "info" | "warn" | "error";
  source: string;
  granule_id: string | null;
  batch_id: string | null;
  message: string;
};

export type GranuleRow = {
  granule_id: string;
  batch_id: string;
  state: GranuleState;
  retry_count: number;
  leased_by: string | null;
  error: string | null;
  updated_at: string;
  objects_exhausted: number;
};

export type Overview = {
  state_counts: Partial<Record<GranuleState, number>>;
  stuck_over_hours: number;
  stuck_by_state: Partial<Record<GranuleState, number>>;
  last_events: EventRow[];
};

export type InFlightRow = {
  granule_id: string;
  batch_id: string;
  state: GranuleState;
  leased_by: string | null;
  retry_count: number;
  updated_at: string;
};

export type Credential = {
  name: string;
  scheme: "basic" | "bearer";
  username?: string | null;
  password?: string | null;
  token?: string | null;
};

export type BundleSummary = {
  name: string;
  version: string;
  sha256: string;
  size: number;
  description: string | null;
  uploaded_at: string;
  in_use_count: number;
};

export type BundleSlotSpec = {
  name: string;
  product: string;
  filename_pattern?: string;
  credential?: string;
};

export type BundleMetaSpec = { name: string; pattern?: string };

export type BundleDetail = BundleSummary & {
  manifest: {
    name: string;
    version: string;
    inputs?: { slots?: BundleSlotSpec[]; meta?: BundleMetaSpec[] } & Record<string, unknown>;
    execution: { entrypoint: string; timeout_sec?: number; env?: Record<string, string> };
    outputs: { watch_dir: string; extensions?: string[]; object_key_template?: string };
    requirements?: { python?: string; pip?: string[]; apt?: string[]; credentials?: string[] };
    shared_files?: string[];
    [k: string]: unknown;
  };
};

export type BundleFileEntry = {
  path: string;
  size: number;
};

export type BundleFileContent = {
  path: string;
  size: number;
  truncated: boolean;
  binary: boolean;
  content: string;
};

export type SharedFileInfo = {
  name: string;
  sha256: string;
  size: number;
  description: string | null;
  uploaded_at: string;
};

export type ProgressRow = {
  id: number;
  granule_id: string;
  batch_id: string;
  ts: string;
  step: string;
  pct: number | null;
  detail: string | null;
};

export type TimingStage = "download" | "process" | "upload";

export type TimingRow = {
  id: number;
  stage: TimingStage;
  started_at: string;
  finished_at: string;
  duration_ms: number;
};

export type StageStats = {
  count: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
};

export type BatchTiming = {
  stages: Record<TimingStage, StageStats>;
  wall_ms: number;
  first_started_at: string | null;
  last_finished_at: string | null;
};

export type OrchestratorInfo = {
  version: string;
  python_version: string;
  platform: string;
  db_path: string;
  retain_events_days: number;
  retain_deleted_days: number;
  retention_sweep_sec: number;
  max_inflight_per_worker: number;
  max_retries: number;
  max_pull_failures: number;
  stuck_age_hours: number;
  dev_mode: boolean;
  auth_open: boolean;
};

export type StuckGranule = {
  granule_id: string;
  batch_id: string;
  state: GranuleState;
  leased_by: string | null;
  retry_count: number;
  error: string | null;
  updated_at: string;
  age_hours: number;
};
