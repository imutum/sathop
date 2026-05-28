<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, IN_FLIGHT_STATES, type GranuleRow, type GranuleState } from "@/api";
import { fmtAge, fmtDuration, stateLabel } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { K } from "@/queryKeys";
import { useBatchDetailMutations } from "@/features/batch/useBatchMutations";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import CardSection from "@/components/CardSection.vue";
import CopyButton from "@/components/CopyButton.vue";
import Field from "@/components/Field.vue";
import PageHeader from "@/components/PageHeader.vue";
import RowActions from "@/components/RowActions.vue";
import Segmented from "@/components/Segmented.vue";
import BatchEventLog from "@/features/batch/components/BatchEventLog.vue";
import BatchGranuleTable from "@/features/batch/components/BatchGranuleTable.vue";
import BatchTimingCard from "@/features/batch/components/BatchTimingCard.vue";
import { errorTotal, inFlightTotal, totalCount } from "@/features/batch/summary";
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
const { cancel, retry, retryAll, cancelAll, resetExhausted, deleteBatch } =
  useBatchDetailMutations(batchId);
const highlight = computed(() => (route.query.granule as string | undefined) ?? null);

const filter = ref<GranuleState | "all">("all");
const PAGE_SIZE = 100;
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

const granules = useQuery({
  queryKey: computed(() => [...K.granules, batchId.value, filter.value, page.value]),
  queryFn: () =>
    API.granules(
      batchId.value,
      filter.value === "all" ? undefined : filter.value,
      PAGE_SIZE,
      page.value * PAGE_SIZE,
    ),
  enabled: computed(() => !!batchId.value),
});

const events = useQuery({
  queryKey: computed(() => [...K.batchEvents, batchId.value, logLevel.value]),
  queryFn: () =>
    API.batchEvents(batchId.value, logLevel.value === "all" ? undefined : logLevel.value, 200),
  enabled: computed(() => !!batchId.value),
});

const latestProgress = useQuery({
  queryKey: computed(() => [...K.batchProgressLatest, batchId.value]),
  queryFn: () => API.batchProgressLatest(batchId.value),
  enabled: computed(() => !!batchId.value),
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

const failedCount = computed(() => (b.value ? errorTotal(b.value) : 0));
// Server-authoritative; for batches with >200 granules the per-row sum from
// the granules query would underreport.
const exhaustedCount = computed(() => b.value?.objects_exhausted ?? 0);
const inflightCount = computed(() => (b.value ? inFlightTotal(b.value) : 0));
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
                  v-if="failedCount > 0"
                  size="sm"
                  :pending="retryAll.isPending.value"
                  pending-label="重试中…"
                  @click="retryAll.mutate()"
                >
                  重试失败 ({{ failedCount }})
                </Button>
                <Button
                  v-if="inflightCount > 0"
                  variant="destructive"
                  size="sm"
                  :pending="cancelAll.isPending.value"
                  pending-label="取消中…"
                  @click="confirmCancelAll"
                >
                  取消 ({{ inflightCount }})
                </Button>
              </template>
              <DropdownMenuItem
                v-if="exhaustedCount > 0"
                :disabled="resetExhausted.isPending.value"
                title="清零所有已放弃产物的拉取失败计数 — 下次 receiver poll 重新派发"
                @select="resetExhausted.mutate()"
              >
                重置已放弃产物 ({{ exhaustedCount }})
              </DropdownMenuItem>
              <DropdownMenuSeparator v-if="exhaustedCount > 0" />
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

    <Card v-if="b">
      <div class="grid grid-cols-2 gap-x-6 gap-y-4 px-6 py-4 sm:grid-cols-4">
        <Field label="处理包" mono>{{ b.bundle_ref }}</Field>
        <Field label="目标接收端">
          <Badge tone="info">{{ b.target_receiver_id ?? "任意" }}</Badge>
        </Field>
        <Field label="创建时间">
          <span class="text-xs">{{ fmtAge(b.created_at) }}</span>
        </Field>
        <Field
          v-if="b.eta_realtime != null || b.eta_seconds != null"
          label="预计剩余"
          :hint="b.eta_realtime != null ? '按最近 1 分钟吞吐' : '按历史平均吞吐'"
        >
          <span class="text-xs tabular-nums">≈ {{ fmtDuration((b.eta_realtime ?? b.eta_seconds!) * 1000) }}</span>
        </Field>
        <Field v-else label="状态">
          <span class="text-xs">{{ b.status }}</span>
        </Field>
      </div>
      <div class="flex flex-wrap gap-1.5 border-t border-border/60 px-5 py-3">
        <Badge v-for="(n, state) in b.counts" :key="state" :tone="state" dot>
          {{ stateLabel(state as GranuleState) }}
          <span class="ml-1 tabular-nums">{{ n }}</span>
        </Badge>
      </div>
    </Card>

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

    <BatchTimingCard
      :batch-id="batchId"
      :remaining="inflightCount"
      :eta-seconds="b?.eta_seconds ?? null"
      :eta-realtime="b?.eta_realtime ?? null"
    />

    <CardSection
      title="日志"
      description="按级别筛选 · 仅本批次的事件"
      :padded="false"
    >
      <template #meta>
        <Badge variant="info" class="tabular-nums">{{ eventCountLabel }}</Badge>
        <Segmented
          v-model="logLevel"
          size="sm"
          :options="LOG_LEVEL_OPTIONS"
        />
      </template>
      <BatchEventLog :events="batchEvents" :batch-id="batchId" />
    </CardSection>
  </div>
</template>
