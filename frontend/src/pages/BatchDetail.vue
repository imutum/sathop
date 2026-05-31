<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, IN_FLIGHT_STATES, type GranuleRow, type GranuleState } from "@/api";
import { fmtAge, stateLabel } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { K } from "@/queryKeys";
import { useBatchDetailMutations } from "@/features/batch/useBatchMutations";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import CardSection from "@/components/CardSection.vue";
import CopyButton from "@/components/CopyButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import RowActions from "@/components/RowActions.vue";
import Segmented from "@/components/Segmented.vue";
import BatchEventLog from "@/features/batch/components/BatchEventLog.vue";
import BatchGranuleTable from "@/features/batch/components/BatchGranuleTable.vue";
import BatchProgress from "@/features/batch/components/BatchProgress.vue";
import BatchTimingCard from "@/features/batch/components/BatchTimingCard.vue";
import { errorTotal, inFlightTotal, isBatchClosed, totalCount } from "@/features/batch/summary";
import { stripBatchPrefix } from "@/lib/utils";
import { Icon } from "@/components/Icon";

// Filter chips 直接派生自 i18n.GRANULE_STATE_ZH，避免命名漂移。下载完/处理完/上传完
// 这 3 个中间状态 (downloaded/processed/uploaded) 在 UI 上对操作意义不大（很短暂），
// 故只保留 worker 视角下"驻留时间长 + 用户关心的" 8 个。
const FILTER_STATES: GranuleState[] = [
  "pending",
  "queued",
  "downloading",
  "processing",
  "uploaded",
  "acked",
  "deleted",
  "failed",
  "blacklisted",
];
const STATE_FILTERS: { value: GranuleState | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  ...FILTER_STATES.map((s) => ({ value: s, label: stateLabel(s) })),
];

const CANCELLABLE = new Set<GranuleState>(IN_FLIGHT_STATES);
const RETRYABLE = new Set<GranuleState>(["failed", "blacklisted"]);
const LOG_LEVEL_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "warn", label: "警告" },
  { value: "error", label: "错误" },
];

const route = useRoute();

const batchId = computed(() => (route.params.batchId as string) ?? "");
const { cancel, retry, retryAll, cancelAll, resetExhausted, deleteBatch, setPaused } =
  useBatchDetailMutations(batchId);
const highlight = computed(() => (route.query.granule as string | undefined) ?? null);

// Progress-first. A `?granule=` deep-link (from dashboard tables) opens the
// 数据粒 tab so the highlighted row is mounted and scroll-into-view works.
const tab = ref<string>(route.query.granule ? "granules" : "progress");

const filter = ref<GranuleState | "all">("all");
const PAGE_SIZE = 10;
const page = ref(0);
const logLevel = ref<"all" | "warn" | "error">("all");
const expanded = ref<string | null>(null);
const rowRefs = ref<Record<string, HTMLElement | null>>({});
let lastScrolled: string | null = null;

function setRowRef(id: string, el: Element | null) {
  rowRefs.value[id] = el as HTMLElement | null;
}

const batch = useQuery({
  queryKey: computed(() => [...K.batch, batchId.value]),
  queryFn: () => API.batch(batchId.value),
  enabled: computed(() => !!batchId.value),
});

watch(filter, () => { page.value = 0; });

// Detail-tab queries are gated on the active tab: nothing fetches until you
// open the tab (TanStack `enabled`). The default 进度 tab reads only the
// always-on `batch` summary, so a batch with many granules/events no longer
// pays for the granule page, the 200-row log, and the whole-batch progress map
// on open — that was the source of the jank.
const onGranules = computed(() => !!batchId.value && tab.value === "granules");
const onEvents = computed(() => !!batchId.value && tab.value === "events");

const granules = useQuery({
  queryKey: computed(() => [...K.granules, batchId.value, filter.value, page.value]),
  queryFn: () =>
    API.granules(
      batchId.value,
      filter.value === "all" ? undefined : filter.value,
      PAGE_SIZE,
      page.value * PAGE_SIZE,
    ),
  enabled: onGranules,
});

const events = useQuery({
  queryKey: computed(() => [...K.batchEvents, batchId.value, logLevel.value]),
  queryFn: () =>
    API.batchEvents(batchId.value, logLevel.value === "all" ? undefined : logLevel.value, 200),
  enabled: onEvents,
});

const latestProgress = useQuery({
  queryKey: computed(() => [...K.batchProgressLatest, batchId.value]),
  queryFn: () => API.batchProgressLatest(batchId.value),
  enabled: onGranules,
});


const b = computed(() => batch.data.value);
const rows = computed(() => granules.data.value ?? []);
const batchEvents = computed(() => events.data.value ?? []);
const progressByGranule = computed(() => latestProgress.data.value ?? {});
const filteredTotal = computed(() => {
  if (!b.value) return 0;
  if (filter.value === "all") return totalCount(b.value.counts);
  return b.value.counts[filter.value as GranuleState] ?? 0;
});
const totalPages = computed(() => Math.max(1, Math.ceil(filteredTotal.value / PAGE_SIZE)));
const hasPrev = computed(() => page.value > 0);
const hasNext = computed(() => page.value < totalPages.value - 1);

const paused = computed(() => b.value?.status === "paused");
// Pause is batch-level flow control over *pending* work; offer it only while the
// batch still has work to gate (not fully delivered). A paused batch always
// offers 恢复 so it can never get stuck paused.
const closed = computed(() => (b.value ? isBatchClosed(b.value) : true));

const failedCount = computed(() => (b.value ? errorTotal(b.value) : 0));
// Server-authoritative; for batches with >200 granules the per-row sum from
// the granules query would underreport.
const exhaustedCount = computed(() => b.value?.objects_exhausted ?? 0);
// Cancellable in-flight (excludes uploaded — already off the worker): gates the
// 取消 action + cancel-all dialog.
const inflightCount = computed(() => (b.value ? inFlightTotal(b.value) : 0));
// Still-to-deliver (includes uploaded-awaiting-ack): matches the ETA's remaining
// denominator, so the 耗时 tab's "预计剩余 (N 条)" count agrees with the ETA value.
const remainingToDeliver = computed(() =>
  b.value ? inflightCount.value + (b.value.counts?.uploaded ?? 0) : 0,
);
const eventCountLabel = computed(() =>
  events.data.value ? `${events.data.value.length} 条` : "加载中",
);

const stateOptions = computed(() =>
  STATE_FILTERS.map((f) => {
    const count =
      f.value === "all"
        ? totalCount(b.value?.counts ?? {})
        : (b.value?.counts?.[f.value as GranuleState] ?? 0);
    return {
      value: f.value,
      label: f.label,
      count,
      dim: count === 0 && f.value !== "all",
    };
  }),
);

watch([highlight, rows], () => {
  void nextTick(() => {
    const id = highlight.value;
    if (!id || lastScrolled === id) return;
    const el = rowRefs.value[id];
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    lastScrolled = id;
  });
});

function toggleRow(id: string) {
  expanded.value = expanded.value === id ? null : id;
}

async function confirmCancel(g: GranuleRow) {
  const ok = await requestConfirm({
    title: "取消数据粒？",
    description: `将取消数据粒 ${stripBatchPrefix(g.granule_id, batchId.value)}。`,
    confirmText: "取消数据粒",
    tone: "danger",
  });
  if (ok) cancel.mutate(g.granule_id);
}

async function confirmCancelAll() {
  if (!b.value) return;
  const ok = await requestConfirm({
    title: `取消批次 "${b.value.name}"？`,
    description: `将取消尚未完成的 ${inflightCount.value} 条数据粒。\n\n待分发/待清理 状态的不会被取消（已经离开 worker）。`,
    confirmText: "取消批次",
    tone: "danger",
  });
  if (ok) cancelAll.mutate();
}

async function confirmDelete() {
  if (!b.value) return;
  const name = b.value.name;
  const total = totalCount(b.value.counts);
  const ok = await requestConfirm({
    title: `永久删除批次 "${name}"？`,
    description:
      `将删除 ${total} 条数据粒，并清除该批次在 orchestrator 上的全部记录\n` +
      "（数据粒、产物、进度、阶段计时、事件）。worker 已上传的产物文件不在清理范围内。",
    confirmText: "永久删除",
    tone: "danger",
    requireText: name,
    inputLabel: `请输入批次名称 "${name}" 确认`,
  });
  if (ok) deleteBatch.mutate(false);
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <RouterLink
        to="/batches"
        class="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Icon name="arrowLeft" :size="12" />
        返回批次列表
      </RouterLink>
      <div class="mt-2">
        <PageHeader :title="b?.name ?? batchId">
          <template #description>
            <span class="inline-flex items-center font-mono text-cell text-muted-foreground">
              {{ batchId }}
              <CopyButton :value="batchId" title="复制批次 ID" />
            </span>
          </template>
          <template v-if="b" #actions>
            <RowActions align="end">
              <template #primary>
                <Button
                  v-if="paused"
                  size="sm"
                  :pending="setPaused.isPending.value"
                  pending-label="恢复中…"
                  @click="setPaused.mutate(false)"
                >
                  <Icon name="play" :size="13" />
                  恢复
                </Button>
                <Button
                  v-else-if="!closed"
                  size="sm"
                  variant="outline"
                  :pending="setPaused.isPending.value"
                  pending-label="暂停中…"
                  title="暂停后不再分发该批次的新数据粒，在途的继续完成；可随时恢复"
                  @click="setPaused.mutate(true)"
                >
                  <Icon name="pause" :size="13" />
                  暂停
                </Button>
                <Button
                  v-if="failedCount > 0"
                  size="sm"
                  :pending="retryAll.isPending.value"
                  pending-label="重试中…"
                  @click="retryAll.mutate()"
                >
                  重试失败 ({{ failedCount }})
                </Button>
              </template>
              <!-- 批次级的整体动作。逐粒取消/重试在「数据粒」页签的行内（原子层）。 -->
              <DropdownMenuItem
                v-if="inflightCount > 0"
                :disabled="cancelAll.isPending.value"
                class="text-danger focus:bg-danger/10 focus:text-danger"
                title="把在途数据粒批量取消（逐粒拉黑）——这是原子层的批量操作，不同于暂停"
                @select="confirmCancelAll"
              >
                取消在途数据粒 ({{ inflightCount }})
              </DropdownMenuItem>
              <DropdownMenuItem
                v-if="exhaustedCount > 0"
                :disabled="resetExhausted.isPending.value"
                title="清零所有已放弃产物的拉取失败计数 — 下次 receiver poll 重新派发"
                @select="resetExhausted.mutate()"
              >
                重置已放弃产物 ({{ exhaustedCount }})
              </DropdownMenuItem>
              <DropdownMenuSeparator v-if="inflightCount > 0 || exhaustedCount > 0" />
              <DropdownMenuItem
                :disabled="deleteBatch.isPending.value"
                class="text-danger focus:bg-danger/10 focus:text-danger"
                @select="confirmDelete"
              >
                永久删除批次…
              </DropdownMenuItem>
            </RowActions>
          </template>
        </PageHeader>
      </div>
    </div>

    <Alert
      v-if="batch.error.value && !b"
      variant="destructive"
    >
      <AlertDescription class="flex items-center justify-between gap-3">
        <span>加载批次失败：{{ batch.error.value.message }}</span>
        <Button size="sm" variant="outline" @click="batch.refetch()">重试</Button>
      </AlertDescription>
    </Alert>

    <Card v-else-if="!b">
      <div class="space-y-3 p-6">
        <Skeleton class="h-5 w-1/3" />
        <Skeleton class="h-4 w-1/4" />
        <Skeleton class="h-4 w-1/2" />
      </div>
    </Card>

    <div
      v-if="b"
      class="flex flex-wrap items-center gap-x-4 gap-y-1 text-cell text-muted-foreground"
    >
      <span>处理包 <span class="font-mono text-foreground">{{ b.bundle_ref }}</span></span>
      <span aria-hidden>·</span>
      <span>接收端 <span class="text-foreground">{{ b.target_receiver_id ?? "任意" }}</span></span>
      <span aria-hidden>·</span>
      <span>创建 {{ fmtAge(b.created_at) }}</span>
      <span aria-hidden>·</span>
      <span class="inline-flex items-center gap-1.5">
        状态
        <Badge v-if="paused" tone="warn">已暂停</Badge>
        <span v-else class="text-foreground">运行中</span>
      </span>
    </div>

    <Tabs v-if="b" v-model="tab">
      <TabsList>
        <TabsTrigger value="progress">进度</TabsTrigger>
        <TabsTrigger value="granules">数据粒</TabsTrigger>
        <TabsTrigger value="events">日志</TabsTrigger>
        <TabsTrigger value="timing">耗时</TabsTrigger>
      </TabsList>

      <!-- 进度：默认页签。只读常驻的 batch 摘要——各阶段实时 WIP（卡点定位）+ 交付吞吐/ETA。 -->
      <TabsContent value="progress">
        <Card>
          <div class="p-5 sm:p-6">
            <BatchProgress :summary="b" />
          </div>
        </Card>
      </TabsContent>

      <!-- 以下三个页签懒加载：reka-ui 非激活页不挂载，其查询 enabled 也门控在对应 tab。 -->
      <TabsContent value="granules">
        <CardSection
          title="数据粒"
          description="按状态筛选 · 点击行展开阶段计时 / 进度时间线 / 该粒事件"
          :padded="false"
        >
          <template #meta>
            <Segmented v-model="filter" size="sm" :options="stateOptions" />
          </template>
          <BatchGranuleTable
            :rows="rows"
            :batch-id="batchId"
            :highlight="highlight"
            :expanded="expanded"
            :latest-progress="progressByGranule"
            :cancellable="CANCELLABLE"
            :retryable="RETRYABLE"
            :cancelling-id="cancel.variables.value"
            :retrying-id="retry.variables.value"
            @row-ref="setRowRef"
            @toggle="toggleRow"
            @cancel="confirmCancel"
            @retry="(id) => retry.mutate(id)"
          />
          <div
            v-if="totalPages > 1"
            class="flex items-center justify-between border-t border-border/60 px-5 py-3 text-cell"
          >
            <span class="tabular-nums text-muted-foreground">
              {{ page * PAGE_SIZE + 1 }}–{{ Math.min((page + 1) * PAGE_SIZE, filteredTotal) }} / {{ filteredTotal }}
            </span>
            <div class="flex items-center gap-2">
              <Button size="sm" variant="outline" :disabled="!hasPrev" @click="page--">上一页</Button>
              <span class="tabular-nums text-muted-foreground">{{ page + 1 }} / {{ totalPages }}</span>
              <Button size="sm" variant="outline" :disabled="!hasNext" @click="page++">下一页</Button>
            </div>
          </div>
        </CardSection>
      </TabsContent>

      <TabsContent value="events">
        <CardSection title="日志" description="按级别筛选 · 仅本批次的事件" :padded="false">
          <template #meta>
            <Badge variant="info" class="tabular-nums">{{ eventCountLabel }}</Badge>
            <Segmented v-model="logLevel" size="sm" :options="LOG_LEVEL_OPTIONS" />
          </template>
          <BatchEventLog :events="batchEvents" :batch-id="batchId" />
        </CardSection>
      </TabsContent>

      <TabsContent value="timing">
        <BatchTimingCard
          :batch-id="batchId"
          :remaining="remainingToDeliver"
          :eta-realtime="b?.eta_realtime ?? null"
        />
      </TabsContent>
    </Tabs>
  </div>
</template>
