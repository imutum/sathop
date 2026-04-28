// Shared types (mirror sathop_shared.protocol) + fetch wrapper with Bearer auth.

export type GranuleState =
  | "pending"
  | "downloading"
  | "downloaded"
  | "processing"
  | "processed"
  | "uploaded"
  | "acked"
  | "deleted"
  | "failed"
  | "blacklisted";

export type BatchSummary = {
  batch_id: string;
  name: string;
  bundle_ref: string;
  target_receiver_id: string | null;
  status: string;
  created_at: string;
  counts: Partial<Record<GranuleState, number>>;
  // Authoritative count of stuck-delivery objects in this batch (failed_pulls
  // ≥ max). Surfaces in the listing without paging through granules.
  objects_exhausted: number;
  // Estimated seconds-to-completion for in-flight granules; null when too
  // little data to extrapolate (need ≥3 closed upload stages + at least one
  // in-flight granule).
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
  // In-flight pulls + recent (~60s) pull throughput in bytes/sec, both
  // reported by receiver heartbeat. Default 0 for receivers running an
  // older protocol that don't send these fields yet.
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
  // Number of this granule's objects whose receiver pulls hit max_pull_failures.
  // > 0 means delivery is stuck — orchestrator stopped offering them.
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
  // Outer envelope: max(finished_at) - min(started_at) across every stage row
  // in the batch. Independent of per-row durations (workers run granules in
  // parallel, so sum >> wall on a healthy cluster).
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

function getToken(): string {
  return localStorage.getItem("sathop.token") ?? "";
}

export function setToken(t: string): void {
  localStorage.setItem("sathop.token", t);
}

// Recover from a stale token (e.g. admin set SATHOP_TOKEN after the user
// auto-skipped login in OPEN mode). All /api/* share require_token, so a 401
// on any endpoint means the cached token is no longer good — drop it and
// reload so the auth gate can probe again or prompt for a new one.
// Disabled during login probes so a wrong-typed token shows an inline error
// instead of looping the page.
let recoverOn401 = true;
export function suspendAuthRecovery<T>(fn: () => Promise<T>): Promise<T> {
  recoverOn401 = false;
  return fn().finally(() => {
    recoverOn401 = true;
  });
}

function handleAuthFailure(): void {
  if (!recoverOn401) return;
  if (!localStorage.getItem("sathop.token")) return;
  // Latch off so parallel queries that all 401 don't each trigger reload().
  recoverOn401 = false;
  localStorage.removeItem("sathop.token");
  window.location.reload();
}

// Unwrap FastAPI's `{"detail": "..."}` envelope so toast messages stay clean
// ("bundle is referenced by …" instead of `409 Conflict: {"detail":"…"}`).
// Falls back to the raw body for non-JSON errors (HTML proxy pages, etc.).
export async function httpError(r: Response, bodyLimit = 400): Promise<Error> {
  const body = await r.text();
  let msg = body.trim();
  try {
    const j = JSON.parse(body);
    const d = j?.detail;
    if (typeof d === "string") msg = d;
    else if (Array.isArray(d) && d.length) msg = d.map((x) => x?.msg ?? JSON.stringify(x)).join("; ");
  } catch {
    // not JSON
  }
  if (!msg) return new Error(`${r.status} ${r.statusText}`);
  return new Error(msg.length > bodyLimit ? msg.slice(0, bodyLimit) + "…" : msg);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers ?? {}),
    },
  });
  if (!r.ok) {
    if (r.status === 401) handleAuthFailure();
    throw await httpError(r);
  }
  return (await r.json()) as T;
}

export const API = {
  overview: () => api<Overview>("/api/admin/overview"),
  inFlight: (limit = 50) => api<InFlightRow[]>(`/api/admin/in-flight?limit=${limit}`),
  stuck: (limit = 50) => api<StuckGranule[]>(`/api/admin/stuck?limit=${limit}`),
  workers: () => api<WorkerInfo[]>("/api/workers"),
  setWorkerCapacity: (workerId: string, desiredCapacity: number | null) =>
    api<{ ok: boolean; desired_capacity: number | null }>(
      `/api/workers/${encodeURIComponent(workerId)}/capacity`,
      { method: "PUT", body: JSON.stringify({ desired_capacity: desiredCapacity }) },
    ),
  setWorkerEnabled: (workerId: string, enabled: boolean) =>
    api<{ ok: boolean; enabled: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}/enabled`,
      { method: "PUT", body: JSON.stringify({ enabled }) },
    ),
  forgetWorker: (workerId: string) =>
    api<{ ok: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}`,
      { method: "DELETE" },
    ),
  receivers: () => api<ReceiverInfo[]>("/api/receivers"),
  setReceiverEnabled: (receiverId: string, enabled: boolean) =>
    api<{ ok: boolean; enabled: boolean }>(
      `/api/receivers/${encodeURIComponent(receiverId)}/enabled`,
      { method: "PUT", body: JSON.stringify({ enabled }) },
    ),
  forgetReceiver: (receiverId: string) =>
    api<{ ok: boolean }>(
      `/api/receivers/${encodeURIComponent(receiverId)}`,
      { method: "DELETE" },
    ),
  batches: () => api<BatchSummary[]>("/api/batches"),
  createBatch: (body: unknown) =>
    api<BatchSummary>("/api/batches", { method: "POST", body: JSON.stringify(body) }),
  batch: (id: string) => api<BatchSummary>(`/api/batches/${id}`),
  granules: (batchId: string, state?: string, limit = 200) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (state) qs.set("state", state);
    return api<GranuleRow[]>(`/api/batches/${batchId}/granules?${qs}`);
  },
  events: (sinceId = 0, limit = 100, beforeId?: number, source?: string) => {
    const qs = new URLSearchParams({ since_id: String(sinceId), limit: String(limit) });
    if (beforeId !== undefined) qs.set("before_id", String(beforeId));
    if (source) qs.set("source", source);
    return api<EventRow[]>(`/api/events?${qs}`);
  },
  batchEvents: (batchId: string, level?: "warn" | "error", limit = 200) => {
    const qs = new URLSearchParams({ batch_id: batchId, limit: String(limit) });
    if (level) qs.set("level", level);
    return api<EventRow[]>(`/api/events?${qs}`);
  },
  granuleEvents: (granuleId: string, limit = 50) => {
    const qs = new URLSearchParams({ granule_id: granuleId, limit: String(limit) });
    return api<EventRow[]>(`/api/events?${qs}`);
  },
  retryFailed: (batchId: string) =>
    api<{ reset: number }>(`/api/batches/${batchId}/retry-failed`, { method: "POST" }),
  resetExhaustedObjects: (batchId: string) =>
    api<{ reset: number }>(`/api/batches/${batchId}/reset-exhausted-objects`, { method: "POST" }),
  cancelBatch: (batchId: string) =>
    api<{ cancelled: number }>(`/api/batches/${batchId}/cancel`, { method: "POST" }),
  deleteBatch: (batchId: string, force = false) =>
    api<{
      ok: boolean;
      granules: number;
      objects: number;
      progress: number;
      stage_timings: number;
      events: number;
    }>(`/api/batches/${batchId}${force ? "?force=true" : ""}`, { method: "DELETE" }),
  cancelGranule: (batchId: string, granuleId: string) =>
    api<{ state: string }>(`/api/batches/${batchId}/granules/${granuleId}/cancel`, { method: "POST" }),
  retryGranule: (batchId: string, granuleId: string) =>
    api<{ state: string }>(`/api/batches/${batchId}/granules/${granuleId}/retry`, { method: "POST" }),
  orchestratorInfo: () => api<OrchestratorInfo>("/api/admin/settings/info"),
  bundles: () => api<BundleSummary[]>("/api/bundles"),
  bundleDetail: (name: string, version: string) =>
    api<BundleDetail>(`/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`),
  uploadBundle: async (zipFile: File, description?: string): Promise<BundleDetail> => {
    const fd = new FormData();
    fd.append("file", zipFile, zipFile.name);
    const qs = description ? `?description=${encodeURIComponent(description)}` : "";
    const r = await fetch(`/api/bundles${qs}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },  // no Content-Type: browser sets multipart boundary
      body: fd,
    });
    if (!r.ok) throw await httpError(r);
    return (await r.json()) as BundleDetail;
  },
  bundleFiles: (name: string, version: string) =>
    api<BundleFileEntry[]>(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/files`,
    ),
  bundleFile: (name: string, version: string, path: string) =>
    api<BundleFileContent>(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/files/${
        path.split("/").map(encodeURIComponent).join("/")
      }`,
    ),
  downloadBundle: async (name: string, version: string): Promise<void> => {
    const url = `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/download`;
    const r = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!r.ok) throw await httpError(r);
    const blob = await r.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `${name}-${version}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  },
  deleteBundle: async (name: string, version: string): Promise<void> => {
    const r = await fetch(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`,
      { method: "DELETE", headers: { Authorization: `Bearer ${getToken()}` } },
    );
    if (!r.ok) throw await httpError(r);
  },
  sharedFiles: () => api<SharedFileInfo[]>("/api/shared"),
  uploadSharedFile: async (
    name: string,
    file: File,
    description?: string,
  ): Promise<SharedFileInfo> => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const qs = description ? `?description=${encodeURIComponent(description)}` : "";
    const r = await fetch(`/api/shared/${encodeURIComponent(name)}${qs}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    });
    if (!r.ok) throw await httpError(r);
    return (await r.json()) as SharedFileInfo;
  },
  deleteSharedFile: (name: string) =>
    fetch(`/api/shared/${encodeURIComponent(name)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${getToken()}` },
    }).then(async (r) => {
      if (!r.ok) throw await httpError(r);
    }),
  granuleProgress: (granuleId: string, limit = 200) =>
    api<ProgressRow[]>(
      `/api/granules/${encodeURIComponent(granuleId)}/progress?limit=${limit}`,
    ),
  batchProgressLatest: (batchId: string) =>
    api<Record<string, ProgressRow>>(`/api/batches/${batchId}/progress/latest`),
  granuleTiming: (granuleId: string) =>
    api<TimingRow[]>(`/api/granules/${encodeURIComponent(granuleId)}/timing`),
  batchTiming: (batchId: string) =>
    api<BatchTiming>(`/api/batches/${encodeURIComponent(batchId)}/timing`),
};
