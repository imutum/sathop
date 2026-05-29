<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, type EventRow } from "@/api";
import { K } from "@/queryKeys";
import { fmtAge, levelLabel } from "@/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import SelectInput from "@/ui/SelectInput.vue";
import Segmented from "@/components/Segmented.vue";
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
const sourceFilter = ref((route.query.source as string | undefined) ?? "");
const rows = ref<EventRow[]>([]);
const expanded = ref<Set<number>>(new Set());
const loadingOlder = ref(false);
const hasMoreOlder = ref(true);

// 实时 / 历史 视图（持久化）。实时模式把最新事件放到底部并跟随滚动。
const MODE_OPTIONS: { value: "history" | "live"; label: string }[] = [
  { value: "history", label: "历史" },
  { value: "live", label: "实时" },
];
const LIVE_KEY = "sathop.events.live";
const mode = ref<"history" | "live">(localStorage.getItem(LIVE_KEY) === "1" ? "live" : "history");
const live = computed(() => mode.value === "live");
watch(mode, (m) => localStorage.setItem(LIVE_KEY, m === "live" ? "1" : "0"));

const scrollEl = ref<HTMLElement | null>(null);
const newCount = ref(0);

function atBottom(): boolean {
  const el = scrollEl.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 48;
}
function scrollToBottom(): void {
  const el = scrollEl.value;
  if (el) el.scrollTop = el.scrollHeight;
  newCount.value = 0;
}

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
  queryKey: computed(() => [...K.events, { source: sourceFilter.value }]),
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

const hasActiveFilters = computed(
  () => !!(search.value || batchFilter.value || sourceFilter.value || filter.value !== "all"),
);

// 实时模式按时间正序（最新在底部）；历史模式维持 newest-first。
const displayRows = computed(() => (live.value ? [...visible.value].reverse() : visible.value));

// 新事件 prepend 到 rows。实时模式下：用户在底部则跟随，否则累计"N 条新"提示。
// （实时模式隐藏"加载更早"，所以 rows 增长仅来自新事件 prepend。）
watch(
  () => rows.value.length,
  (len, prev) => {
    if (!live.value) return;
    const added = len - (prev ?? len);
    if (added <= 0) return;
    if (atBottom()) void nextTick(scrollToBottom);
    else newCount.value += added;
  },
);
watch(mode, (m) => {
  if (m === "live") void nextTick(scrollToBottom);
});

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
        <Badge variant="info" class="tabular-nums">
          <span class="text-foreground">{{ visible.length }}</span>
          <span class="text-muted-foreground/80">/ {{ rows.length }} 条</span>
        </Badge>
      </template>
    </PageHeader>

    <Card>
      <div class="flex flex-wrap items-center gap-2 border-b border-border/60 px-5 py-3">
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
          class="h-8 w-full rounded-lg border border-border bg-background px-2.5 text-xs text-foreground outline-none transition-colors hover:border-primary/40 focus:border-primary sm:w-48"
        >
          <option value="">所有批次</option>
          <option v-for="b in batches" :key="b" :value="b">{{ b }}</option>
        </SelectInput>
        <Segmented v-model="filter" :options="LEVEL_FILTERS" />
        <Segmented v-model="mode" :options="MODE_OPTIONS" aria-label="实时或历史视图" />
        <Badge
          v-if="sourceFilter"
          variant="outline"
          class="border-primary/40 bg-primary/10 text-primary"
        >
          <span class="opacity-70">源</span>
          <span class="font-mono">{{ sourceFilter }}</span>
          <button
            type="button"
            @click="sourceFilter = ''"
            class="-mr-1 grid h-4 w-4 place-items-center rounded text-primary/70 transition-colors hover:bg-primary/15 hover:text-primary"
            aria-label="移除源过滤"
          >
            <Icon name="x" :size="10" :stroke-width="2.4" />
          </button>
        </Badge>
        <Popover>
          <PopoverTrigger as-child>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              title="事件等级与展开规则说明"
              aria-label="事件等级与展开规则说明"
            >
              <Icon name="help" :size="14" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" class="w-72 text-cell">
            <div class="mb-2 text-mini font-medium tracking-label text-muted-foreground">等级图例</div>
            <ul class="space-y-1.5 text-muted-foreground">
              <li class="flex items-center gap-2">
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/70" aria-hidden />
                <span><span class="text-foreground">信息</span> · 例行状态推进</span>
              </li>
              <li class="flex items-center gap-2">
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
                <span><span class="text-foreground">警告</span> · 值得关注但未失败</span>
              </li>
              <li class="flex items-center gap-2">
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-danger" aria-hidden />
                <span><span class="text-foreground">错误</span> · 处理失败 / 异常</span>
              </li>
            </ul>
            <div class="mt-3 border-t border-border/60 pt-2 text-2xs text-muted-foreground">
              长消息可点击展开
            </div>
          </PopoverContent>
        </Popover>
        <Button
          v-if="hasActiveFilters"
          type="button"
          variant="ghost"
          size="sm"
          class="text-muted-foreground hover:text-foreground"
          @click="clearAll"
        >
          清除筛选
        </Button>
      </div>

      <div ref="scrollEl" class="relative max-h-[70vh] overflow-auto font-mono">
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
            <EmptyState title="暂无事件" illustration="inbox" />
          </template>
          <template #default>
            <EmptyState
              v-if="visible.length === 0"
              title="当前筛选条件下没有匹配"
            />
            <ul v-else class="divide-y divide-border/50">
              <li
                v-for="e in displayRows"
                :key="e.id"
                class="flex flex-wrap items-start gap-x-3 gap-y-1 px-5 py-2 text-cell transition-colors hover:bg-muted/40"
              >
                <span class="w-20 shrink-0 text-muted-foreground">{{ fmtAge(e.ts) }}</span>
                <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
                <span class="min-w-0 shrink truncate text-muted-foreground md:w-32 md:shrink-0" :title="e.source">{{ e.source }}</span>
                <span
                  :class="
                    isLong(e.message) && !expanded.has(e.id)
                      ? 'min-w-0 basis-full cursor-pointer truncate hover:text-foreground md:basis-0 md:flex-1'
                      : 'min-w-0 basis-full break-words whitespace-pre-wrap md:basis-0 md:flex-1'
                  "
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
                    class="ml-2 text-3xs text-muted-foreground hover:text-primary"
                  >
                    {{ expanded.has(e.id) ? "收起" : "展开" }}
                  </button>
                </span>
                <template v-if="e.granule_id">
                  <RouterLink
                    v-if="e.batch_id"
                    :to="`/batches/${e.batch_id}?granule=${encodeURIComponent(e.granule_id)}`"
                    class="min-w-0 max-w-full shrink truncate text-muted-foreground transition-colors hover:text-primary md:shrink-0"
                  >
                    {{ e.granule_id }}
                  </RouterLink>
                  <span v-else class="min-w-0 max-w-full shrink truncate text-muted-foreground md:shrink-0">{{ e.granule_id }}</span>
                </template>
              </li>
            </ul>
            <div
              v-if="rows.length > 0 && !live"
              class="flex items-center justify-center border-t border-border/60 px-5 py-3"
            >
              <Button
                v-if="hasMoreOlder"
                type="button"
                variant="outline"
                size="sm"
                :pending="loadingOlder"
                pending-label="加载中…"
                @click="loadOlder"
              >
                加载更早事件
              </Button>
              <span v-else class="text-2xs text-muted-foreground">已加载到最早事件</span>
            </div>
          </template>
        </QueryState>

        <!-- 实时模式：用户上滚后新事件落底时的跳转提示 -->
        <div
          v-if="live && newCount > 0"
          class="pointer-events-none sticky bottom-3 z-10 flex justify-center"
        >
          <button
            type="button"
            @click="scrollToBottom"
            class="pointer-events-auto inline-flex items-center gap-1 rounded-full border border-border bg-background/95 px-3 py-1 text-2xs font-medium text-foreground shadow-pop backdrop-blur transition-colors hover:border-primary/40 hover:text-primary"
          >
            ↓ {{ newCount }} 条新事件
          </button>
        </div>
      </div>
    </Card>
  </div>
</template>
