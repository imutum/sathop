import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";
import { compareSemver } from "@/lib/semver";

// All consumers share one server-resolved release query and its hourly cache.

export const GITHUB_REPO = "imutum/sathop";
export const RELEASES_URL = `https://github.com/${GITHUB_REPO}/releases`;

export type VersionStatus = "unchecked" | "loading" | "current" | "outdated" | "stale" | "unknown";

// Share the one-shot cache bypass with the query shared across components.
let forceNextFetch = false;

async function fetchLatestRelease() {
  const force = forceNextFetch;
  forceNextFetch = false;
  const j = await API.latestVersion(force);
  // Keep a last-known tag on upstream failure, but mark it stale below.
  if (j.error && !j.tag) throw new Error(j.error);
  return {
    tag: j.tag ?? "",
    htmlUrl: j.html_url ?? RELEASES_URL,
    channel: j.channel ?? "stable",
    stale: Boolean(j.stale || j.error),
  };
}

// No background polling; explicit refresh bypasses the server cache.
export function useLatestRelease() {
  return useQuery({
    queryKey: [...K.githubRelease],
    queryFn: fetchLatestRelease,
    staleTime: 60 * 60 * 1000,
    refetchInterval: false,
    retry: 1,
  });
}

// Compare a (reactive) current version against the latest release. `current`
// may be a ref, getter, or plain string so callers can pass `worker.version`
// or `() => info.data.value?.version` interchangeably.
export function useVersionCheck(current: MaybeRefOrGetter<string | undefined>) {
  const latest = useLatestRelease();
  const latestTag = computed(() => latest.data.value?.tag ?? "");
  const channel = computed(() => latest.data.value?.channel ?? "stable");
  const currentVersion = computed(() => toValue(current) ?? "");
  const htmlUrl = computed(() => latest.data.value?.htmlUrl ?? RELEASES_URL);

  const status = computed<VersionStatus>(() => {
    if (latest.isFetching.value) return "loading";
    if (!latest.isFetched.value) return "unchecked";
    if (!latestTag.value || !currentVersion.value) return "unknown";
    if (latest.isError.value || latest.data.value?.stale) return "stale";
    return compareSemver(currentVersion.value, latestTag.value) >= 0 ? "current" : "outdated";
  });

  const statusLabel = computed(() => {
    const labels: Record<VersionStatus, string> = {
      unchecked: "尚未检查更新",
      loading: "正在检查更新…",
      current: "当前已是最新版本",
      outdated: `新版本 ${latestTag.value} 可用`,
      stale: `更新检查未完成，上次记录为 ${latestTag.value}`,
      unknown: "暂时无法检查更新",
    };
    return labels[status.value];
  });
  const dotClass = computed(() => {
    if (status.value === "current") return "bg-success";
    if (status.value === "outdated" || status.value === "stale") return "bg-warning";
    return "bg-muted-foreground";
  });

  // Manual re-check: force the next fetch to bypass the orchestrator's hourly cache,
  // then refetch (which also bypasses TanStack's staleTime).
  function refresh() {
    forceNextFetch = true;
    void latest.refetch();
  }

  return {
    latest, latestTag, channel, currentVersion, htmlUrl,
    status, statusLabel, dotClass, isFetching: latest.isFetching, refresh,
  };
}
