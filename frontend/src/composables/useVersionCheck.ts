import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";
import { compareSemver } from "@/lib/semver";

// Single source of truth for "what's the latest released SatHop version, and is
// X behind it?". Resolved via the orchestrator (GET /api/admin/latest-version),
// NOT the browser hitting api.github.com directly — that was anonymous and
// rate-limited 60/h per client IP, which a shared NAT exhausts (then the upgrade
// button silently never appears). The orchestrator fetches once (one IP, optional
// SATHOP_GIT_TOKEN, 5-min cache). Keyed by K.githubRelease so the sidebar banner,
// settings page, and N node cards share ONE request (TanStack dedupes by key).

export const GITHUB_REPO = "imutum/sathop";
export const RELEASES_URL = `https://github.com/${GITHUB_REPO}/releases`;

export type VersionStatus = "unchecked" | "loading" | "current" | "outdated" | "unknown";

// Set by refresh() so the very next fetch hits the orchestrator with ?force=true
// (skip + reset its hourly GitHub cache); consumed on read so any later auto-refetch
// stays cached. Module-scoped because there is one logical latest-release query
// shared across all components (TanStack dedupes by key), so the flag must too.
let forceNextFetch = false;

async function fetchLatestRelease(): Promise<{ tag: string; htmlUrl: string; channel: string }> {
  const force = forceNextFetch;
  forceNextFetch = false;
  const j = await API.latestVersion(force);
  // A stale serve (GitHub unreachable, last-known-good returned) carries BOTH a valid
  // tag AND error — that's the point of serve-stale, so use the tag and don't throw.
  // Only a hard failure (error with no usable tag) surfaces as a query error.
  if (j.error && !j.tag) throw new Error(j.error);
  return { tag: j.tag ?? "", htmlUrl: j.html_url ?? RELEASES_URL, channel: j.channel ?? "stable" };
}

// The shared latest-version query. Fetches once on mount (NOT a background poll —
// no refetchInterval); the orchestrator caches one GitHub hit per clock-hour, so the
// upgrade button appears without a manual click while GitHub stays well under its
// rate limit. `refresh()` forces a fresh GitHub fetch (bypassing both caches). Per-node
// cards compare against the orchestrator version, not this, so they never refetch it.
export function useLatestRelease() {
  return useQuery({
    queryKey: [...K.githubRelease],
    queryFn: fetchLatestRelease,
    staleTime: 60 * 60 * 1000,
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
    if (!latest.isFetched.value) return "unchecked"; // never checked (no auto-poll)
    if (latest.isError.value || !latestTag.value || !currentVersion.value) return "unknown";
    return compareSemver(currentVersion.value, latestTag.value) >= 0 ? "current" : "outdated";
  });

  // Manual re-check: force the next fetch to bypass the orchestrator's hourly cache,
  // then refetch (which also bypasses TanStack's staleTime).
  function refresh() {
    forceNextFetch = true;
    void latest.refetch();
  }

  return { latest, latestTag, channel, currentVersion, htmlUrl, status, isFetching: latest.isFetching, refresh };
}
