<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { Icon } from "@/components/Icon";

defineProps<{ collapsed?: boolean }>();

const GITHUB_REPO = "imutum/sathop";
const RELEASES_URL = `https://github.com/${GITHUB_REPO}/releases`;
const LATEST_API = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`;

// `vX.Y.Z` ⇒ [X, Y, Z]; loose so a `0.2.5` (no v) or `v0.2.5-rc1` (with suffix)
// both parse to a sortable tuple. Pre-release suffix is stripped (treated as
// the same as the base release for comparison purposes — fine for an
// "update available" indicator that just nudges the operator to look).
function parseSemver(v: string): number[] {
  const m = v.trim().match(/v?(\d+)\.(\d+)\.(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0];
}

function compareSemver(a: string, b: string): number {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] - pb[i];
  }
  return 0;
}

const info = useQuery({
  queryKey: ["orchestrator-info"],
  queryFn: API.orchestratorInfo,
  staleTime: 60 * 60 * 1000,
});

// Direct fetch (not through `api()`) — GitHub's public Releases API doesn't
// want our Bearer header, and sending one would also leak the token if
// somehow the URL got rewritten. 30-min staleTime keeps us well under
// the 60-req/hr unauthenticated rate limit even with multiple tabs open.
async function fetchLatestRelease(): Promise<{ tag: string; htmlUrl: string }> {
  const r = await fetch(LATEST_API, { headers: { Accept: "application/vnd.github+json" } });
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  const j = (await r.json()) as { tag_name?: string; html_url?: string };
  return { tag: j.tag_name ?? "", htmlUrl: j.html_url ?? RELEASES_URL };
}

const latest = useQuery({
  queryKey: ["github-latest-release"],
  queryFn: fetchLatestRelease,
  staleTime: 30 * 60 * 1000,
  retry: 1,
});

const currentVersion = computed(() => info.data.value?.version ?? "");
const latestTag = computed(() => latest.data.value?.tag ?? "");

type Status = "loading" | "current" | "outdated" | "unknown";
const status = computed<Status>(() => {
  if (info.isPending.value || latest.isPending.value) return "loading";
  if (latest.isError.value || !latestTag.value || !currentVersion.value) return "unknown";
  return compareSemver(currentVersion.value, latestTag.value) >= 0 ? "current" : "outdated";
});

const statusLabel = computed(() => {
  switch (status.value) {
    case "current":
      return "已是最新版本";
    case "outdated":
      return `有新版本 ${latestTag.value} 可用`;
    case "loading":
      return "正在检查更新…";
    case "unknown":
      return latest.isError.value ? "无法访问 GitHub（网络或限流）" : "版本信息缺失";
  }
  return "";
});

const dotClass = computed(() => {
  switch (status.value) {
    case "current":
      return "bg-success";
    case "outdated":
      return "bg-warning animate-pulse-soft";
    case "loading":
      return "bg-muted-foreground animate-pulse-soft";
    case "unknown":
      return "bg-muted-foreground";
  }
  return "bg-muted-foreground";
});

const open = ref(false);
const root = ref<HTMLElement | null>(null);

function onDocClick(e: MouseEvent) {
  if (!open.value) return;
  if (root.value && e.target instanceof Node && !root.value.contains(e.target)) {
    open.value = false;
  }
}

onMounted(() => {
  document.addEventListener("click", onDocClick);
});
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocClick);
});

function refresh() {
  void info.refetch();
  void latest.refetch();
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      @click="open = !open"
      :title="collapsed ? `${currentVersion || '?'} · ${statusLabel}` : undefined"
      :class="[
        'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground',
        collapsed ? 'justify-center' : '',
      ]"
    >
      <span class="relative grid h-2 w-2 shrink-0 place-items-center">
        <span :class="['absolute inset-0 rounded-full', dotClass]" />
      </span>
      <span v-if="!collapsed" class="truncate font-mono">
        {{ currentVersion ? `v${currentVersion}` : "—" }}
      </span>
    </button>

    <!-- Floating panel: anchored above the button (sidebar footer is at the bottom). -->
    <div
      v-if="open"
      class="absolute bottom-full left-0 z-30 mb-2 w-64 rounded-lg border border-border bg-popover p-3 shadow-lg"
    >
      <div class="flex items-center justify-between">
        <div class="text-2xs font-medium uppercase tracking-brand text-muted-foreground">
          当前版本
        </div>
        <button
          type="button"
          @click="refresh"
          :disabled="info.isFetching.value || latest.isFetching.value"
          class="grid h-6 w-6 place-items-center rounded text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50"
          :title="'重新检查'"
          aria-label="重新检查"
        >
          <Icon name="refresh" :size="13" :class="info.isFetching.value || latest.isFetching.value ? 'animate-spin' : ''" />
        </button>
      </div>

      <div class="mt-2 flex items-baseline gap-2">
        <span class="font-mono text-2xl font-semibold text-foreground">
          {{ currentVersion ? `v${currentVersion}` : "—" }}
        </span>
        <span :class="['relative grid h-2.5 w-2.5 place-items-center', status === 'current' ? '' : '']">
          <span :class="['absolute inset-0 rounded-full', dotClass]" />
        </span>
      </div>

      <div class="mt-1 text-xs text-muted-foreground">{{ statusLabel }}</div>

      <div
        v-if="status === 'outdated'"
        class="mt-2 rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-2xs text-warning"
      >
        最新发布版本：<span class="font-mono">{{ latestTag }}</span>
      </div>

      <a
        :href="latest.data.value?.htmlUrl ?? RELEASES_URL"
        target="_blank"
        rel="noopener noreferrer"
        class="mt-3 flex items-center justify-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-2xs text-foreground transition hover:bg-muted"
      >
        <Icon name="github" :size="13" />
        查看发布
        <Icon name="external" :size="11" class="text-muted-foreground" />
      </a>
    </div>
  </div>
</template>
