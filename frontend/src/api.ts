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
  desired_capacity: number | null;
};

export type ReceiverInfo = {
  receiver_id: string;
  version: string;
  platform: "linux" | "windows";
  last_seen: string;
  disk_free_gb: number;
  enabled: boolean;
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
};

export type BundleDetail = BundleSummary & {
  manifest: {
    name: string;
    version: string;
    inputs?: Record<string, unknown>;
    execution: { entrypoint: string; timeout_sec?: number; env?: Record<string, string> };
    outputs: { watch_dir: string; extensions?: string[]; object_key_template?: string };
    requirements?: { python?: string; pip?: string[]; apt?: string[]; credentials?: string[] };
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

export type BatchTiming = Record<TimingStage, StageStats>;

export type OrchestratorInfo = {
  version: string;
  python_version: string;
  platform: string;
  db_path: string;
  retain_events_days: number;
  retain_deleted_days: number;
  retention_sweep_sec: number;
  max_inflight_per_worker: number;
  dev_mode: boolean;
};

function getToken(): string {
  return localStorage.getItem("sathop.token") ?? "";
}

export function setToken(t: string): void {
  localStorage.setItem("sathop.token", t);
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
    const body = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 200)}`);
  }
  return (await r.json()) as T;
}

export const API = {
  overview: () => api<Overview>("/api/admin/overview"),
  inFlight: (limit = 50) => api<InFlightRow[]>(`/api/admin/in-flight?limit=${limit}`),
  workers: () => api<WorkerInfo[]>("/api/workers"),
  setWorkerCapacity: (workerId: string, desiredCapacity: number | null) =>
    api<{ ok: boolean; desired_capacity: number | null }>(
      `/api/workers/${encodeURIComponent(workerId)}/capacity`,
      { method: "PUT", body: JSON.stringify({ desired_capacity: desiredCapacity }) },
    ),
  receivers: () => api<ReceiverInfo[]>("/api/receivers"),
  batches: () => api<BatchSummary[]>("/api/batches"),
  createBatch: (body: unknown) =>
    api<BatchSummary>("/api/batches", { method: "POST", body: JSON.stringify(body) }),
  batch: (id: string) => api<BatchSummary>(`/api/batches/${id}`),
  granules: (batchId: string, state?: string, limit = 200) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (state) qs.set("state", state);
    return api<GranuleRow[]>(`/api/batches/${batchId}/granules?${qs}`);
  },
  events: (sinceId = 0, limit = 100) =>
    api<EventRow[]>(`/api/events?since_id=${sinceId}&limit=${limit}`),
  batchEvents: (batchId: string, level?: "warn" | "error", limit = 200) => {
    const qs = new URLSearchParams({ batch_id: batchId, limit: String(limit) });
    if (level) qs.set("level", level);
    return api<EventRow[]>(`/api/events?${qs}`);
  },
  retryFailed: (batchId: string) =>
    api<{ reset: number }>(`/api/batches/${batchId}/retry-failed`, { method: "POST" }),
  cancelBatch: (batchId: string) =>
    api<{ cancelled: number }>(`/api/batches/${batchId}/cancel`, { method: "POST" }),
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
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 400)}`);
    }
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
  deleteBundle: (name: string, version: string) =>
    fetch(`/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${getToken()}` },
    }).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    }),
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
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 400)}`);
    }
    return (await r.json()) as SharedFileInfo;
  },
  deleteSharedFile: (name: string) =>
    fetch(`/api/shared/${encodeURIComponent(name)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${getToken()}` },
    }).then(async (r) => {
      if (!r.ok) {
        const body = await r.text();
        throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 400)}`);
      }
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
