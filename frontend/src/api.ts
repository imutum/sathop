// Typed API endpoint catalog.

import {
  authHeaders,
  deleteJson,
  getJson,
  httpError,
  postJson,
  putJson,
} from "./apiClient";
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

export { getToken, setToken, suspendAuthRecovery } from "./apiClient";
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

const adminApi = {
  overview: () => getJson<Overview>("/api/admin/overview"),
  inFlight: (limit = 50) => getJson<InFlightRow[]>(`/api/admin/in-flight?limit=${limit}`),
  stuck: (limit = 50) => getJson<StuckGranule[]>(`/api/admin/stuck?limit=${limit}`),
  orchestratorInfo: () => getJson<OrchestratorInfo>("/api/admin/settings/info"),
  // Upgrade to a specific release: the orchestrator writes .pending-version and
  // self-restarts; the entrypoint installs that version's self-contained bundle
  // (backend + matching frontend) on the next boot. Restart = same-version.
  upgradeOrchestrator: (version: string) =>
    postJson<{ ok: boolean; version: string }>("/api/admin/upgrade", { version }),
  restartOrchestrator: () => postJson<{ ok: boolean }>("/api/admin/restart"),
  // Newest release, resolved server-side (one IP, optional token, 5-min cache)
  // so the browser never hits the rate-limited api.github.com directly.
  latestVersion: () =>
    getJson<{ tag: string; html_url: string; current: string; channel?: string; error?: string }>(
      "/api/admin/latest-version",
    ),
};

const nodeApi = {
  workers: () => getJson<WorkerInfo[]>("/api/workers"),
  setWorkerConcurrency: (
    workerId: string,
    body: { download_concurrency: number | null; process_concurrency: number | null },
  ) =>
    putJson<{ ok: boolean; download_concurrency: number | null; process_concurrency: number | null }>(
      `/api/workers/${encodeURIComponent(workerId)}/concurrency`,
      body,
    ),
  setWorkersConcurrency: (
    workerIds: string[],
    body: { download_concurrency: number | null; process_concurrency: number | null },
  ) =>
    putJson<{ ok: boolean; applied: string[] }>("/api/workers/concurrency", {
      worker_ids: workerIds,
      ...body,
    }),
  removeWorker: (workerId: string, force = false) =>
    deleteJson<{ ok: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}${force ? "?force=true" : ""}`,
    ),
  // Physical delete of an already-removed (history) worker. Backend 409s unless
  // removed_at is set, so the UI only offers it on the history tab.
  purgeWorker: (workerId: string) =>
    deleteJson<{ ok: boolean; purged: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}?purge=true`,
    ),
  // version set ⇒ coordinated upgrade (worker stamps its own .pending-version,
  // drains, entrypoint installs that release); null/omitted ⇒ same-version restart.
  updateWorker: (workerId: string, version?: string | null) =>
    postJson<{ ok: boolean; version: string | null }>(
      `/api/workers/${encodeURIComponent(workerId)}/update`,
      { version: version ?? null },
    ),
  setWorkerPaused: (workerId: string, operator_paused: boolean) =>
    putJson<{ ok: boolean; operator_paused: boolean }>(
      `/api/workers/${encodeURIComponent(workerId)}/pause`,
      { operator_paused },
    ),
  revokeWorkerLeases: (workerId: string) =>
    postJson<{ ok: boolean; revoked: number }>(
      `/api/workers/${encodeURIComponent(workerId)}/revoke-all`,
    ),
  workerGc: (workerId: string) =>
    postJson<{ ok: boolean }>(`/api/workers/${encodeURIComponent(workerId)}/gc`),
  receivers: () => getJson<ReceiverInfo[]>("/api/receivers"),
  setReceiverEnabled: (receiverId: string, enabled: boolean) =>
    putJson<{ ok: boolean; enabled: boolean }>(
      `/api/receivers/${encodeURIComponent(receiverId)}/enabled`,
      { enabled },
    ),
  forgetReceiver: (receiverId: string) =>
    deleteJson<{ ok: boolean }>(`/api/receivers/${encodeURIComponent(receiverId)}`),
  restartReceiver: (receiverId: string) =>
    postJson<{ ok: boolean }>(`/api/receivers/${encodeURIComponent(receiverId)}/restart`),
};

const batchApi = {
  batches: () => getJson<BatchSummary[]>("/api/batches"),
  createBatch: (body: unknown) =>
    postJson<BatchSummary>("/api/batches", body),
  batch: (id: string) => getJson<BatchSummary>(`/api/batches/${id}`),
  granules: (batchId: string, state?: string, limit = 100, offset = 0) => {
    const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
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
