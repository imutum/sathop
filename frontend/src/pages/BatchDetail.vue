<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { refDebounced } from "@vueuse/core";
import { useQuery } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, IN_FLIGHT_STATES, STATE_ORDER, type GranuleRow, type GranuleState } from "@/api";
import { fmtAge, stateLabel } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
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
import TextInput from "@/ui/TextInput.vue";
import BatchOperations from "@/features/batch/components/BatchOperations.vue";
import { operationStatus } from "@/features/batch/operationStatus";
import BatchEventLog from "@/features/batch/components/BatchEventLog.vue";
import BatchGranuleTable from "@/features/batch/components/BatchGranuleTable.vue";
import BatchProgress from "@/features/batch/components/BatchProgress.vue";
import BatchTimingCard from "@/features/batch/components/BatchTimingCard.vue";
import { inFlightTotal, isBatchClosed, totalCount } from "@/features/batch/summary";
import { stripBatchPrefix } from "@/lib/utils";
import { Icon } from "@/components/Icon";

const FILTER_STATES: GranuleState[] = [...STATE_ORDER, "failed", "blacklisted"];
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
const toast = useToast();
const downloadingReport = ref(false);

const batchId = computed(() => (route.params.batchId as string) ?? "");
const { cancel, retry, retryAll, cancelAll, resetExhausted, deleteBatch, setPaused } =
  useBatchDetailMutations(batchId);
const highlight = computed(() => (route.query.granule as string | undefined) ?? null);

// Progress-first. A `?granule=` deep-link (from dashboard tables) opens the
// 数据粒 tab so the highlighted row is mounted and scroll-into-view works.
const tab = ref<string>(route.query.granule ? "granules" : "progress");

const filter = ref<GranuleState | "all">("all");
const search = ref(typeof route.query.granule === "string" ? route.query.granule : "");
const searchTerm = refDebounced(search, 250);
const PAGE_SIZE = 20;
const page = ref(0);
const logLevel = ref<"all" | "warn" | "error">("all");
const expanded = ref<string | null>(null);
const rowRefs = ref<Record<string, HTMLElement | null>>({});
let lastScrolled: string | null = null;

function setRowRef(id: string, el: Element | { $el?: Element } | null) {
  const node = el && "$el" in el ? el.$el : el;
  rowRefs.value[id] = node instanceof HTMLElement ? node : null;
}

const batch = useQuery({
  queryKey: computed(() => [...K.batch, batchId.value]),
  queryFn: () => API.batch(batchId.value),
  enabled: computed(() => !!batchId.value),
});

watch([filter, searchTerm], () => { page.value = 0; expanded.value = null; });
watch(batchId, () => {
  page.value = 0;
  filter.value = "all";
  search.value = highlight.value ?? "";
  expanded.value = null;
  lastScrolled = null;
  tab.value = highlight.value ? "granules" : "progress";
});
watch(highlight, (id) => {
  if (id) { search.value = id; filter.value = "all"; tab.value = "granules"; }
});

// Detail-tab queries are gated on the active tab: nothing fetches until you
// open the tab (TanStack `enabled`). The default 进度 tab reads only the
// always-on `batch` summary, so a batch with many granules/events no longer
// pays for the granule page, the 200-row log, and the whole-batch progress map
// on open — that was the source of the jank.
const onGranules = computed(() => !!batchId.value && tab.value === "granules");
const onEvents = computed(() => !!batchId.value && tab.value === "events");

const granules = useQuery({
  queryKey: computed(() => [...K.granules, batchId.value, filter.value, searchTerm.value, page.value]),
  queryFn: () =>
    API.granulePage(
      batchId.value,
      filter.value === "all" ? undefined : filter.value,
      searchTerm.value,
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
const rows = computed(() => granules.data.value?.items ?? []);
const batchEvents = computed(() => events.data.value ?? []);
const progressByGranule = computed(() => latestProgress.data.value ?? {});
const filteredTotal = computed(() => granules.data.value?.total ?? 0);
const archivedDelivered = computed(() => granules.data.value?.archived_delivered ?? 0);
const totalPages = computed(() => Math.max(1, Math.ceil(filteredTotal.value / PAGE_SIZE)));
watch(() => granules.data.value, (data) => {
  if (data && page.value >= totalPages.value) page.value = totalPages.value - 1;
});
const hasPrev = computed(() => page.value > 0);
const hasNext = computed(() => page.value < totalPages.value - 1);

const paused = computed(() => b.value?.status === "paused");
// Pause is batch-level flow control over *pending* work; offer it only while the
// batch still has work to gate (not fully delivered). A paused batch always
// offers 恢复 so it can never get stuck paused.
const closed = computed(() => (b.value ? isBatchClosed(b.value) : true));

const failedCount = computed(() => b.value?.counts.failed ?? 0);
const stoppedCount = computed(() => b.value?.counts.blacklisted ?? 0);
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

function inspectState(state: GranuleState) {
  search.value = "";
  filter.value = state;
  page.value = 0;
  tab.value = "granules";
}

async function downloadReport() {
  downloadingReport.value = true;
  try {
    await API.downloadDeliveryReport(batchId.value);
    toast.success("交付报告已导出");
  } catch (e) {
    toast.error(`导出失败：${(e as Error).message}`);
  } finally { downloadingReport.value = false; }
}

async function confirmRetryStopped() {
  const ok = await requestConfirm({
    title: "重新处理已停止的数据粒？",
    description: `将重新处理 ${stoppedCount.value} 条已停止和 ${failedCount.value} 条失败数据粒。已停止中可能包含主动取消的任务，这会重新下载和处理它们。请先在数据粒列表核对范围。`,
    confirmText: "重新处理", tone: "danger",
  });
  if (ok) retryAll.mutate(true);
}

async function confirmResetExhausted() {
  const ok = await requestConfirm({
    title: "恢复产物交付？",
    description: `将重新尝试拉取 ${exhaustedCount.value} 个产物。请先确认接收端在线、磁盘空间充足，并已修复源产物或网络问题。`,
    confirmText: "恢复交付",
  });
  if (ok) resetExhausted.mutate();
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
    description: `将取消尚未完成的 ${inflightCount.value} 条数据粒。\n\n待交付、待清理及已完成的数据粒不受影响。`,
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
      `将删除 ${total} 条数据粒并清除运行明细。已确认的交付台账继续保留。\n` +
      "已上传的产物文件不会删除。此操作不可恢复。",
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
                <Button size="sm" variant="outline" as-child><RouterLink :to="{ path: '/deliveries', query: { batch: batchId } }">查看交付台账</RouterLink></Button>
                <Button size="sm" variant="outline" :pending="downloadingReport" pending-label="导出中…" @click="downloadReport">
                  <Icon name="download" :size="13" />
                  导出交付报告
                </Button>
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
                  @click="retryAll.mutate(false)"
                >
                  重试失败 ({{ failedCount }})
                </Button>
              </template>
              <!-- 批次级的整体动作。逐粒取消/重试在「数据粒」页签的行内（原子层）。 -->
              <DropdownMenuItem v-if="stoppedCount > 0" :disabled="retryAll.isPending.value" @select="confirmRetryStopped">
                重新处理已停止数据粒…
              </DropdownMenuItem>
              <DropdownMenuItem
                v-if="inflightCount > 0"
                :disabled="cancelAll.isPending.value"
                class="text-danger focus:bg-danger/10 focus:text-danger"
                title="取消尚未上传完成的数据粒；待交付和已交付的数据粒不受影响"
                @select="confirmCancelAll"
              >
                取消在途数据粒 ({{ inflightCount }})
              </DropdownMenuItem>
              <DropdownMenuItem
                v-if="exhaustedCount > 0"
                :disabled="resetExhausted.isPending.value"
                title="重置拉取失败次数，等待接收端重新拉取"
                @select="confirmResetExhausted"
              >
                恢复产物交付 ({{ exhaustedCount }})
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
      <span>任务包 <span class="font-mono text-foreground">{{ b.bundle_ref }}</span></span>
      <span aria-hidden>·</span>
      <span>接收端 <span class="text-foreground">{{ b.target_receiver_id ?? "自动分配" }}</span></span>
      <span aria-hidden>·</span>
      <span>创建 {{ fmtAge(b.created_at) }}</span>
      <span aria-hidden>·</span>
      <span class="inline-flex items-center gap-1.5">
        状态
        <Badge v-if="paused" tone="warn">已暂停</Badge>
        <span v-else class="text-foreground">{{ operationStatus(b).label }}</span>
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
        <BatchOperations class="mb-4" :summary="b" :restoring="resetExhausted.isPending.value" @inspect="inspectState" @restore="confirmResetExhausted" />
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
          description="按 ID 或状态筛选，查看处理进度与错误详情"
          :padded="false"
        >
          <div class="space-y-3 border-b border-border/60 px-5 py-4">
            <div class="max-w-full overflow-x-auto pb-1">
              <Segmented v-model="filter" size="sm" :options="stateOptions" class="whitespace-nowrap" aria-label="数据粒状态筛选" />
            </div>
            <div class="flex items-center gap-2">
              <TextInput v-model="search" class="w-full sm:max-w-sm" maxlength="200" placeholder="搜索数据粒 ID" aria-label="搜索数据粒 ID">
                <template #leftIcon><Icon name="search" :size="13" /></template>
              </TextInput>
              <Button v-if="search" size="sm" variant="ghost" @click="search = ''">清除</Button>
            </div>
            <p class="text-xs text-muted-foreground">状态数量为累计统计，下方仅分页显示仍保留的明细。<span v-if="archivedDelivered">已有 {{ archivedDelivered.toLocaleString() }} 条已交付明细按保留策略清理，仅保留累计数量。</span></p>
          </div>
          <div v-if="granules.isPending.value" class="space-y-3 p-5" aria-label="正在加载数据粒">
            <Skeleton v-for="n in 3" :key="n" class="h-12 w-full" />
          </div>
          <Alert v-else-if="granules.error.value" variant="destructive" class="m-5">
            <AlertDescription class="flex items-center justify-between gap-3">
              <span>加载数据粒失败：{{ granules.error.value.message }}</span>
              <Button size="sm" variant="outline" @click="granules.refetch()">重试</Button>
            </AlertDescription>
          </Alert>
          <BatchGranuleTable
            v-else
            :rows="rows"
            :batch-id="batchId"
            :highlight="highlight"
            :expanded="expanded"
            :latest-progress="progressByGranule"
            :cancellable="CANCELLABLE"
            :retryable="RETRYABLE"
            :cancelling-id="cancel.isPending.value ? cancel.variables.value : undefined"
            :retrying-id="retry.isPending.value ? retry.variables.value : undefined"
            @row-ref="setRowRef"
            @toggle="toggleRow"
            @cancel="confirmCancel"
            @retry="(id) => retry.mutate(id)"
          />
          <div
            v-if="granules.data.value && !granules.error.value"
            class="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 px-5 py-3 text-cell"
          >
            <span class="tabular-nums text-muted-foreground">
              {{ filteredTotal ? page * PAGE_SIZE + 1 : 0 }}–{{ Math.min((page + 1) * PAGE_SIZE, filteredTotal) }} / {{ filteredTotal }} 条明细
            </span>
            <div class="flex items-center gap-2">
              <Button size="sm" variant="outline" :disabled="!hasPrev || granules.isFetching.value" @click="page--">上一页</Button>
              <span class="tabular-nums text-muted-foreground">{{ page + 1 }} / {{ totalPages }}</span>
              <Button size="sm" variant="outline" :disabled="!hasNext || granules.isFetching.value" @click="page++">下一页</Button>
            </div>
          </div>
        </CardSection>
      </TabsContent>

      <TabsContent value="events">
        <CardSection title="日志" description="查看本批次事件，可按级别筛选" :padded="false">
          <template #meta>
            <Badge variant="info" class="tabular-nums">{{ eventCountLabel }}</Badge>
            <Segmented v-model="logLevel" size="sm" :options="LOG_LEVEL_OPTIONS" />
          </template>
          <div v-if="events.isPending.value" class="p-5"><Skeleton class="h-24 w-full" /></div>
          <Alert v-else-if="events.error.value" variant="destructive" class="m-5">
            <AlertDescription class="flex items-center justify-between gap-3">
              <span>加载日志失败：{{ events.error.value.message }}</span>
              <Button size="sm" variant="outline" @click="events.refetch()">重试</Button>
            </AlertDescription>
          </Alert>
          <BatchEventLog v-else :events="batchEvents" :batch-id="batchId" />
        </CardSection>
      </TabsContent>

      <TabsContent value="timing">
        <BatchTimingCard
          :batch-id="batchId"
          :remaining="remainingToDeliver"
          :eta-realtime="paused ? null : b?.eta_realtime ?? null"
        />
      </TabsContent>
    </Tabs>
  </div>
</template>
