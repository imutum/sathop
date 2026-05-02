// Fetch wrapper with Bearer auth + typed API endpoints.

import type {
  BatchSummary,
  BatchTiming,
  BundleDetail,
  BundleFileContent,
  BundleFileEntry,
  BundleSummary,
  EventRow,
  GranuleRow,
  InFlightRow,
  OrchestratorInfo,
  Overview,
  ProgressRow,
  ReceiverInfo,
  SharedFileInfo,
  StuckGranule,
  TimingRow,
  WorkerInfo,
} from "./apiTypes";

export { IN_FLIGHT_STATES, STATE_ORDER } from "./apiTypes";
export type {
  BatchSummary,
  BatchTiming,
  BundleDetail,
  BundleFileContent,
  BundleFileEntry,
  BundleMetaSpec,
  BundleSlotSpec,
  BundleSummary,
  Credential,
  EventRow,
  GranuleRow,
  GranuleState,
  InFlightRow,
  OrchestratorInfo,
  Overview,
  ProgressRow,
  ReceiverInfo,
  SharedFileInfo,
  StageStats,
  StuckGranule,
  TimingRow,
  TimingStage,
  WorkerInfo,
} from "./apiTypes";

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

function authHeaders(init?: HeadersInit, jsonBody = false): Headers {
  const headers = new Headers(init);
  headers.set("Authorization", `Bearer ${getToken()}`);
  if (jsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
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
    headers: authHeaders(init.headers, init.body !== undefined),
  });
  if (!r.ok) {
    if (r.status === 401) handleAuthFailure();
    throw await httpError(r);
  }
  return (await r.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, body: JSON.stringify(body) };
}

const getJson = <T>(path: string) => api<T>(path);
const postJson = <T>(path: string, body?: unknown) => api<T>(path, jsonInit("POST", body));
const putJson = <T>(path: string, body?: unknown) => api<T>(path, jsonInit("PUT", body));
const deleteJson = <T>(path: string) => api<T>(path, { method: "DELETE" });

const adminApi = {
  overview: () => getJson<Overview>("/api/admin/overview"),
  inFlight: (limit = 50) => getJson<InFlightRow[]>(`/api/admin/in-flight?limit=${limit}`),
  stuck: (limit = 50) => getJson<StuckGranule[]>(`/api/admin/stuck?limit=${limit}`),
  orchestratorInfo: () => getJson<OrchestratorInfo>("/api/admin/settings/info"),
};

const nodeApi = {
  workers: () => getJson<WorkerInfo[]>("/api/workers"),
  setWorkerCapacity: (workerId: string, desiredCapacity: number | null) =>
    putJson<{ ok: boolean; desired_capacity: number | null }>(
      `/api/workers/${encodeURIComponent(workerId)}/capacity`,
      { desired_capacity: desiredCapacity },
    ),
  setWorkerEnabled: (workerId: string, enabled: boolean) =>
    putJson<{ ok: boolean; enabled: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}/enabled`,
      { enabled },
    ),
  forgetWorker: (workerId: string) =>
    deleteJson<{ ok: boolean }>(`/api/workers/${encodeURIComponent(workerId)}`),
  receivers: () => getJson<ReceiverInfo[]>("/api/receivers"),
  setReceiverEnabled: (receiverId: string, enabled: boolean) =>
    putJson<{ ok: boolean; enabled: boolean }>(
      `/api/receivers/${encodeURIComponent(receiverId)}/enabled`,
      { enabled },
    ),
  forgetReceiver: (receiverId: string) =>
    deleteJson<{ ok: boolean }>(`/api/receivers/${encodeURIComponent(receiverId)}`),
};

const batchApi = {
  batches: () => getJson<BatchSummary[]>("/api/batches"),
  createBatch: (body: unknown) =>
    postJson<BatchSummary>("/api/batches", body),
  batch: (id: string) => getJson<BatchSummary>(`/api/batches/${id}`),
  granules: (batchId: string, state?: string, limit = 200) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (state) qs.set("state", state);
    return getJson<GranuleRow[]>(`/api/batches/${batchId}/granules?${qs}`);
  },
  events: (sinceId = 0, limit = 100, beforeId?: number, source?: string) => {
    const qs = new URLSearchParams({ since_id: String(sinceId), limit: String(limit) });
    if (beforeId !== undefined) qs.set("before_id", String(beforeId));
    if (source) qs.set("source", source);
    return getJson<EventRow[]>(`/api/events?${qs}`);
  },
  batchEvents: (batchId: string, level?: "warn" | "error", limit = 200) => {
    const qs = new URLSearchParams({ batch_id: batchId, limit: String(limit) });
    if (level) qs.set("level", level);
    return getJson<EventRow[]>(`/api/events?${qs}`);
  },
  granuleEvents: (granuleId: string, limit = 50) => {
    const qs = new URLSearchParams({ granule_id: granuleId, limit: String(limit) });
    return getJson<EventRow[]>(`/api/events?${qs}`);
  },
  retryFailed: (batchId: string) =>
    postJson<{ reset: number }>(`/api/batches/${batchId}/retry-failed`),
  resetExhaustedObjects: (batchId: string) =>
    postJson<{ reset: number }>(`/api/batches/${batchId}/reset-exhausted-objects`),
  cancelBatch: (batchId: string) =>
    postJson<{ cancelled: number }>(`/api/batches/${batchId}/cancel`),
  deleteBatch: (batchId: string, force = false) =>
    deleteJson<{
      ok: boolean;
      granules: number;
      objects: number;
      progress: number;
      stage_timings: number;
      events: number;
    }>(`/api/batches/${batchId}${force ? "?force=true" : ""}`),
  cancelGranule: (batchId: string, granuleId: string) =>
    postJson<{ state: string }>(`/api/batches/${batchId}/granules/${granuleId}/cancel`),
  retryGranule: (batchId: string, granuleId: string) =>
    postJson<{ state: string }>(`/api/batches/${batchId}/granules/${granuleId}/retry`),
};

const bundleApi = {
  bundles: () => getJson<BundleSummary[]>("/api/bundles"),
  bundleDetail: (name: string, version: string) =>
    getJson<BundleDetail>(`/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`),
  uploadBundle: async (zipFile: File, description?: string): Promise<BundleDetail> => {
    const fd = new FormData();
    fd.append("file", zipFile, zipFile.name);
    const qs = description ? `?description=${encodeURIComponent(description)}` : "";
    const r = await fetch(`/api/bundles${qs}`, {
      method: "POST",
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok) throw await httpError(r);
    return (await r.json()) as BundleDetail;
  },
  bundleFiles: (name: string, version: string) =>
    getJson<BundleFileEntry[]>(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/files`,
    ),
  bundleFile: (name: string, version: string, path: string) =>
    getJson<BundleFileContent>(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/files/${
        path.split("/").map(encodeURIComponent).join("/")
      }`,
    ),
  downloadBundle: async (name: string, version: string): Promise<void> => {
    const url = `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}/download`;
    const r = await fetch(url, { headers: authHeaders() });
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
    await deleteJson<{ ok: boolean }>(
      `/api/bundles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`,
    );
  },
};

const sharedApi = {
  sharedFiles: () => getJson<SharedFileInfo[]>("/api/shared"),
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
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok) throw await httpError(r);
    return (await r.json()) as SharedFileInfo;
  },
  deleteSharedFile: (name: string) =>
    deleteJson<{ ok: boolean }>(`/api/shared/${encodeURIComponent(name)}`).then(() => undefined),
};

const progressApi = {
  granuleProgress: (granuleId: string, limit = 200) =>
    getJson<ProgressRow[]>(
      `/api/granules/${encodeURIComponent(granuleId)}/progress?limit=${limit}`,
    ),
  batchProgressLatest: (batchId: string) =>
    getJson<Record<string, ProgressRow>>(`/api/batches/${batchId}/progress/latest`),
  granuleTiming: (granuleId: string) =>
    getJson<TimingRow[]>(`/api/granules/${encodeURIComponent(granuleId)}/timing`),
  batchTiming: (batchId: string) =>
    getJson<BatchTiming>(`/api/batches/${encodeURIComponent(batchId)}/timing`),
};

export const API = {
  ...adminApi,
  ...nodeApi,
  ...batchApi,
  ...bundleApi,
  ...sharedApi,
  ...progressApi,
};
