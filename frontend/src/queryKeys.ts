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
  orchestratorInfo: ["orchestrator-info"],
  githubRelease: ["github-latest-release"],
} as const;

export const SCOPE_KEYS: Record<Scope, readonly (readonly string[])[]> = {
  batches: [K.batches, K.overview, K.batch, K.granules, K.inflight, K.stuck],
  workers: [K.workers, K.overview],
  receivers: [K.receivers, K.overview],
  events: [K.events, K.overview, K.batchEvents, K.granuleEvents],
  progress: [K.granuleProgress, K.batchProgressLatest],
  bundles: [K.bundles, K.bundleDetail],
  shared: [K.sharedFiles],
};
