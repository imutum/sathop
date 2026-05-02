<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, type EventRow } from "@/api";
import { fmtAge, levelLabel } from "@/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import SelectInput from "@/ui/SelectInput.vue";
import Segmented from "@/components/Segmented.vue";
import { Loader2Icon } from "lucide-vue-next";
import TextInput from "@/ui/TextInput.vue";
import { Icon } from "@/components/Icon";

type Level = "all" | "warn" | "error";
const LEVEL_FILTERS: { value: Level; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "warn", label: "警告" },
  { value: "error", label: "错误" },
];

const route = useRoute();
const router = useRouter();

const initLevel = (route.query.level as Level | undefined) ?? "all";
const filter = ref<Level>(
  (["all", "warn", "error"] as Level[]).includes(initLevel) ? initLevel : "all",
);
const search = ref((route.query.q as string | undefined) ?? "");
const batchFilter = ref((route.query.batch as string | undefined) ?? "");
// Server-side exact-match filter on Event.source — used by per-node drill-downs
// (worker / receiver cards link here with ?source=<id>). Reset rows when it
// changes so we re-fetch a clean page rather than mixing old global rows in.
const sourceFilter = ref((route.query.source as string | undefined) ?? "");
const rows = ref<EventRow[]>([]);
const expanded = ref<Set<number>>(new Set());
const loadingOlder = ref(false);
const hasMoreOlder = ref(true);

watch([filter, search, batchFilter, sourceFilter], ([f, s, b, src]) => {
  const next: Record<string, string> = {};
  if (f !== "all") next.level = f;
  if (s) next.q = s;
  if (b) next.batch = b;
  if (src) next.source = src;
  router.replace({ query: next });
});

watch(sourceFilter, () => {
  rows.value = [];
  hasMoreOlder.value = true;
});

const q = useQuery({
  queryKey: computed(() => ["events", { source: sourceFilter.value }]),
  queryFn: () => API.events(rows.value[0]?.id ?? 0, 200, undefined, sourceFilter.value || undefined),
});

watch(
  () => q.data.value,
  (data) => {
    if (!data || data.length === 0) return;
    const seen = new Set(rows.value.map((r) => r.id));
    const fresh = data.filter((r) => !seen.has(r.id));
    if (fresh.length === 0) return;
    rows.value = [...fresh, ...rows.value].slice(0, 500);
  },
);

async function loadOlder() {
  const oldest = rows.value[rows.value.length - 1]?.id;
  if (oldest === undefined || loadingOlder.value) return;
  loadingOlder.value = true;
  try {
    const older = await API.events(0, 200, oldest, sourceFilter.value || undefined);
    if (older.length === 0) {
      hasMoreOlder.value = false;
      return;
    }
    const seen = new Set(rows.value.map((r) => r.id));
    rows.value = [...rows.value, ...older.filter((r) => !seen.has(r.id))];
    if (older.length < 200) hasMoreOlder.value = false;
  } finally {
    loadingOlder.value = false;
  }
}

const batches = computed(() => {
  const s = new Set<string>();
  for (const r of rows.value) if (r.batch_id) s.add(r.batch_id);
  return [...s].sort();
});

const needle = computed(() => search.value.trim().toLowerCase());

const visible = computed(() =>
  rows.value.filter((r) => {
    if (filter.value !== "all" && r.level !== filter.value) return false;
    if (batchFilter.value && r.batch_id !== batchFilter.value) return false;
    if (needle.value) {
      const hay = `${r.source} ${r.message} ${r.granule_id ?? ""} ${r.batch_id ?? ""}`.toLowerCase();
      if (!hay.includes(needle.value)) return false;
    }
    return true;
  }),
);

function isLong(msg: string) {
  return msg.length > 160 || msg.includes("\n");
}

function toggle(id: number) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expanded.value = next;
}

function clearAll() {
  search.value = "";
  batchFilter.value = "";
  sourceFilter.value = "";
  filter.value = "all";
}

type HighlightSeg = { text: string; mark: boolean };
function highlight(text: string, n: string): HighlightSeg[] {
  if (!n) return [{ text, mark: false }];
  const idx = text.toLowerCase().indexOf(n);
  if (idx < 0) return [{ text, mark: false }];
  return [
    { text: text.slice(0, idx), mark: false },
    { text: text.slice(idx, idx + n.length), mark: true },
    { text: text.slice(idx + n.length), mark: false },
  ];
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="事件日志"
      description="所有 Orchestrator / Worker / Receiver 上报事件的合并视图"
    >
      <template #actions>
        <span class="rounded-full border border-border bg-muted px-3 py-1 text-2xs font-medium tabular-nums text-muted-foreground">
          <span class="text-foreground">{{ visible.length }}</span> / {{ rows.length }} 条
        </span>
      </template>
    </PageHeader>

    <Card>
      <div class="flex flex-wrap items-center gap-2 border-b border-border/60 px-5 py-3.5">
        <div class="min-w-[260px] flex-1">
          <TextInput
            v-model="search"
            placeholder="搜索：message / source / granule_id / batch_id"
            aria-label="搜索事件"
          >
            <template #leftIcon>
              <Icon name="search" :size="13" />
            </template>
          </TextInput>
        </div>
        <SelectInput
          v-model="batchFilter"
          aria-label="按批次过滤"
          class="h-8 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground outline-none transition hover:border-primary/40 focus:border-primary"
        >
          <option value="">所有批次</option>
          <option v-for="b in batches" :key="b" :value="b">{{ b }}</option>
        </SelectInput>
        <Segmented v-model="filter" :options="LEVEL_FILTERS" />
        <span
          v-if="sourceFilter"
          class="inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-2.5 text-xs text-primary"
          title="按事件源（worker / receiver ID）过滤 — 服务端精确匹配"
        >
          源: <span class="font-mono">{{ sourceFilter }}</span>
          <button
            type="button"
            @click="sourceFilter = ''"
            class="text-primary/70 transition hover:text-primary"
            title="移除源过滤"
            aria-label="移除源过滤"
          >
            ×
          </button>
        </span>
        <button
          v-if="search || batchFilter || sourceFilter || filter !== 'all'"
          @click="clearAll"
          class="h-8 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
        >
          清除
        </button>
      </div>

      <div class="max-h-[70vh] overflow-auto font-mono">
        <QueryState :query="q" :is-empty="() => rows.length === 0">
          <template #loading>
            <div class="space-y-2 p-5">
              <Skeleton v-for="n in 6" :key="n" class="h-7 w-full" />
            </div>
          </template>
          <template #error="{ error, retry: retryFetch }">
            <div class="p-5">
              <Alert variant="destructive">
                <AlertDescription class="flex items-center justify-between gap-3">
                  <span>加载事件失败：{{ error.message }}</span>
                  <Button size="sm" variant="outline" @click="retryFetch">重试</Button>
                </AlertDescription>
              </Alert>
            </div>
          </template>
          <template #empty>
            <EmptyState title="暂无事件" />
          </template>
          <template #default>
        <EmptyState
          v-if="visible.length === 0"
          title="当前筛选条件下没有匹配"
        />
        <ul v-else class="divide-y divide-border/50">
          <li
            v-for="e in visible"
            :key="e.id"
            class="flex items-start gap-3 px-5 py-2 text-[11.5px] transition hover:bg-muted/40"
          >
            <span class="w-20 shrink-0 text-muted-foreground">{{ fmtAge(e.ts) }}</span>
            <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
            <span class="w-32 shrink-0 truncate text-muted-foreground" :title="e.source">{{ e.source }}</span>
            <span
              :class="
                isLong(e.message) && !expanded.has(e.id)
                  ? 'flex-1 cursor-pointer truncate hover:text-foreground'
                  : 'flex-1 break-all whitespace-pre-wrap'
              "
              :title="isLong(e.message) && !expanded.has(e.id) ? '点击展开完整消息' : undefined"
              @click="isLong(e.message) && toggle(e.id)"
            >
              <template v-for="(seg, i) in highlight(e.message, needle)" :key="i">
                <mark v-if="seg.mark" class="rounded bg-warning/30 px-0.5 text-warning">{{ seg.text }}</mark>
                <template v-else>{{ seg.text }}</template>
              </template>
              <button
                v-if="isLong(e.message)"
                type="button"
                @click.stop="toggle(e.id)"
                class="ml-2 text-[10px] text-muted-foreground hover:text-primary"
              >
                {{ expanded.has(e.id) ? "收起" : "展开" }}
              </button>
            </span>
            <template v-if="e.granule_id">
              <RouterLink
                v-if="e.batch_id"
                :to="`/batches/${e.batch_id}?granule=${encodeURIComponent(e.granule_id)}`"
                class="shrink-0 truncate text-muted-foreground transition hover:text-primary"
                :title="`跳转到 ${e.batch_id} 中的 ${e.granule_id}`"
              >
                {{ e.granule_id }}
              </RouterLink>
              <span v-else class="shrink-0 truncate text-muted-foreground">{{ e.granule_id }}</span>
            </template>
          </li>
        </ul>
        <div
          v-if="rows.length > 0"
          class="flex items-center justify-center border-t border-border/60 px-5 py-3"
        >
          <button
            v-if="hasMoreOlder"
            type="button"
            @click="loadOlder"
            :disabled="loadingOlder"
            class="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-[11.5px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Loader2Icon v-if="loadingOlder" class="size-3 animate-spin" />
            {{ loadingOlder ? "加载中…" : "加载更早事件" }}
          </button>
          <span v-else class="text-2xs text-muted-foreground">已加载到最早事件</span>
        </div>
          </template>
        </QueryState>
      </div>
    </Card>
  </div>
</template>
