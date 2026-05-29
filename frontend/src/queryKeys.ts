import type { Scope } from "./apiTypes";

export const K = {
  overview: ["overview"],
  workers: ["workers"],
  receivers: ["receivers"],
  inflight: ["in-flight"],
  stuck: ["stuck"],
  batches: ["batches"],
  batch: ["batch"],
  granules: ["granules"],
  batchEvents: ["batch-events"],
  batchProgressLatest: ["batch-progress-latest"],
  batchTiming: ["batch-timing"],
  events: ["events"],
  granuleEvents: ["granule-events"],
  granuleProgress: ["granule-progress"],
  granuleTiming: ["granule-timing"],
  bundles: ["bundles"],
  bundleDetail: ["bundle-detail"],
  bundleFiles: ["bundle-files"],
  bundleFile: ["bundle-file"],
  sharedFiles: ["shared-files"],
  orchInfo: ["orch-info"],
  githubRelease: ["github-latest-release"],
} as const;

// SSE-driven invalidation: each backend `scope` nudge invalidates the keys
// listed here (see useLiveStream). Keys NOT mentioned anywhere below — namely
// K.inflight and K.stuck — intentionally have no SSE scope: they are expensive
// scan queries that ride the 60s refetchInterval safety net only (Dashboard
// further gates them behind `enabled`). The orchInfo / githubRelease version
// keys are pulled on demand with their own long staleTime, also by design.
export const SCOPE_KEYS: Record<Scope, readonly (readonly string[])[]> = {
  batches: [K.batches, K.overview, K.batch, K.granules],
  workers: [K.workers, K.overview],
  receivers: [K.receivers],
  events: [K.events, K.batchEvents, K.granuleEvents],
  progress: [K.granuleProgress, K.batchProgressLatest],
  bundles: [K.bundles, K.bundleDetail],
  shared: [K.sharedFiles],
};

// Compile-time guard: adding a new Scope without wiring its keys here is a type
// error, so SSE nudges can never silently fail to refresh a page.
const _exhaustive: Record<Scope, readonly (readonly string[])[]> = SCOPE_KEYS;
void _exhaustive;
