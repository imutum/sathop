import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { K } from "@/queryKeys";
import { compareSemver } from "@/lib/semver";

// Single source of truth for "what's the latest released SatHop version, and is
// X behind it?". The GitHub query is keyed by K.githubRelease, so every caller
// — the sidebar orchestrator banner, the settings page, and N worker/receiver
// cards — shares ONE network request (TanStack dedupes by key). That's why
// per-node version checks don't multiply GitHub's rate limit.

export const GITHUB_REPO = "imutum/sathop";
export const RELEASES_URL = `https://github.com/${GITHUB_REPO}/releases`;
const LATEST_RELEASE_API = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`;
const TAGS_API = `https://api.github.com/repos/${GITHUB_REPO}/tags?per_page=1`;
const GH_HEADERS = { Accept: "application/vnd.github+json" } as const;

export type VersionStatus = "unchecked" | "loading" | "current" | "outdated" | "unknown";

async function fetchLatestRelease(): Promise<{ tag: string; htmlUrl: string }> {
  const releaseR = await fetch(LATEST_RELEASE_API, { headers: GH_HEADERS });
  if (releaseR.ok) {
    const j = (await releaseR.json()) as { tag_name?: string; html_url?: string };
    return { tag: j.tag_name ?? "", htmlUrl: j.html_url ?? RELEASES_URL };
  }
  if (releaseR.status !== 404) throw new Error(`GitHub ${releaseR.status}`);

  // No published release yet — fall back to the newest tag.
  const tagsR = await fetch(TAGS_API, { headers: GH_HEADERS });
  if (!tagsR.ok) throw new Error(`GitHub ${tagsR.status}`);
  const tags = (await tagsR.json()) as Array<{ name?: string }>;
  const name = Array.isArray(tags) && tags.length > 0 ? tags[0].name ?? "" : "";
  return {
    tag: name,
    htmlUrl: name ? `https://github.com/${GITHUB_REPO}/releases/tag/${name}` : RELEASES_URL,
  };
}

// The shared GitHub query. NEVER auto-fetches (`enabled: false`) — checking for
// a newer release is an explicit operator action (the refresh button in the
// sidebar VersionStatus / settings), not a background poll. `refetch()` is the
// only thing that hits GitHub. Keyed by K.githubRelease so the sidebar banner
// and settings page share one result once checked; per-node cards compare
// against the orchestrator version, not GitHub, so they never touch this query.
export function useLatestRelease() {
  return useQuery({
    queryKey: [...K.githubRelease],
    queryFn: fetchLatestRelease,
    enabled: false,
    staleTime: Infinity,
    retry: 1,
  });
}

// Compare a (reactive) current version against the latest release. `current`
// may be a ref, getter, or plain string so callers can pass `worker.version`
// or `() => info.data.value?.version` interchangeably.
export function useVersionCheck(current: MaybeRefOrGetter<string | undefined>) {
  const latest = useLatestRelease();
  const latestTag = computed(() => latest.data.value?.tag ?? "");
  const currentVersion = computed(() => toValue(current) ?? "");
  const htmlUrl = computed(() => latest.data.value?.htmlUrl ?? RELEASES_URL);

  const status = computed<VersionStatus>(() => {
    if (latest.isFetching.value) return "loading";
    if (!latest.isFetched.value) return "unchecked"; // never checked (no auto-poll)
    if (latest.isError.value || !latestTag.value || !currentVersion.value) return "unknown";
    return compareSemver(currentVersion.value, latestTag.value) >= 0 ? "current" : "outdated";
  });

  function refresh() {
    void latest.refetch();
  }

  return { latest, latestTag, currentVersion, htmlUrl, status, isFetching: latest.isFetching, refresh };
}
