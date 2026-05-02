<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, IN_FLIGHT_STATES, type GranuleRow, type GranuleState } from "@/api";
import { fmtAge, fmtDuration, stateLabel } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import CopyButton from "@/components/CopyButton.vue";
import Field from "@/components/Field.vue";
import PageHeader from "@/components/PageHeader.vue";
import Segmented from "@/components/Segmented.vue";
import BatchEventLog from "@/features/batch/components/BatchEventLog.vue";
import BatchGranuleTable from "@/features/batch/components/BatchGranuleTable.vue";
import BatchTimingCard from "@/features/batch/components/BatchTimingCard.vue";
import { Icon } from "@/components/Icon";

const STATE_FILTERS: { value: GranuleState | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待处理" },
  { value: "queued", label: "排队中" },
  { value: "downloading", label: "下载中" },
  { value: "processing", label: "处理中" },
  { value: "uploaded", label: "已上传" },
  { value: "acked", label: "已确认" },
  { value: "deleted", label: "已清理" },
  { value: "failed", label: "失败" },
  { value: "blacklisted", label: "已拉黑" },
];

const CANCELLABLE = new Set<GranuleState>(IN_FLIGHT_STATES);
const RETRYABLE = new Set<GranuleState>(["failed", "blacklisted"]);
const LOG_LEVEL_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "warn", label: "警告" },
  { value: "error", label: "错误" },
];

function stripBatchPrefix(gid: string, batchId: string) {
  return gid.startsWith(`${batchId}:`) ? gid.slice(batchId.length + 1) : gid;
}

function sumCounts(counts: Record<string, number | undefined>): number {
  return Object.values(counts).reduce<number>((sum, n) => sum + (n ?? 0), 0);
}

const route = useRoute();
const router = useRouter();
const qc = useQueryClient();
const toast = useToast();

const batchId = computed(() => (route.params.batchId as string) ?? "");
const highlight = computed(() => (route.query.granule as string | undefined) ?? null);

const filter = ref<GranuleState | "all">("all");
const logLevel = ref<"all" | "warn" | "error">("all");
const expanded = ref<string | null>(null);
const rowRefs = ref<Record<string, HTMLElement | null>>({});
let lastScrolled: string | null = null;

function setRowRef(id: string, el: Element | null) {
  rowRefs.value[id] = el as HTMLElement | null;
}

const batch = useQuery({
  queryKey: computed(() => ["batch", batchId.value]),
  queryFn: () => API.batch(batchId.value),
  enabled: computed(() => !!batchId.value),
});

const granules = useQuery({
  queryKey: computed(() => ["granules", batchId.value, filter.value]),
  queryFn: () => API.granules(batchId.value, filter.value === "all" ? undefined : filter.value),
  enabled: computed(() => !!batchId.value),
});

const events = useQuery({
  queryKey: computed(() => ["batch-events", batchId.value, logLevel.value]),
  queryFn: () =>
    API.batchEvents(batchId.value, logLevel.value === "all" ? undefined : logLevel.value, 200),
  enabled: computed(() => !!batchId.value),
});

const latestProgress = useQuery({
  queryKey: computed(() => ["batch-progress-latest", batchId.value]),
  queryFn: () => API.batchProgressLatest(batchId.value),
  enabled: computed(() => !!batchId.value),
});

function invalidate() {
  qc.invalidateQueries({ queryKey: ["granules", batchId.value] });
  qc.invalidateQueries({ queryKey: ["batch", batchId.value] });
  qc.invalidateQueries({ queryKey: ["batches"] });
}

const cancel = useMutation({
  mutationFn: (g: string) => API.cancelGranule(batchId.value, g),
  onSuccess: (_r, g) => {
    invalidate();
    toast.success(`已取消数据粒 ${g}`);
  },
  onError: (e: Error, g) => toast.error(`取消 ${g} 失败：${e.message}`),
});

const retry = useMutation({
  mutationFn: (g: string) => API.retryGranule(batchId.value, g),
  onSuccess: (_r, g) => {
    invalidate();
    toast.success(`已重试数据粒 ${g}`);
  },
  onError: (e: Error, g) => toast.error(`重试 ${g} 失败：${e.message}`),
});

const retryAll = useMutation({
  mutationFn: () => API.retryFailed(batchId.value),
  onSuccess: (res) => {
    invalidate();
    toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
  },
  onError: (e: Error) => toast.error(`重试失败：${e.message}`),
});

const cancelAll = useMutation({
  mutationFn: () => API.cancelBatch(batchId.value),
  onSuccess: (res) => {
    invalidate();
    toast.success(`已取消 ${res.cancelled} 条数据粒`);
  },
  onError: (e: Error) => toast.error(`取消失败：${e.message}`),
});

const resetExhausted = useMutation({
  mutationFn: () => API.resetExhaustedObjects(batchId.value),
  onSuccess: (res) => {
    invalidate();
    if (res.reset > 0) toast.success(`已重置 ${res.reset} 个产物的重试计数，下个 receiver poll 周期会重新派发`);
    else toast.info("当前批次没有已放弃的产物");
  },
  onError: (e: Error) => toast.error(`重置失败：${e.message}`),
});

const deleteBatch = useMutation({
  mutationFn: (force: boolean) => API.deleteBatch(batchId.value, force),
  onSuccess: (res) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
    toast.success(
      `已删除批次：${res.granules} 数据粒 / ${res.objects} 产物 / ${res.events} 事件`,
    );
    void router.push("/batches");
  },
  onError: async (e: Error) => {
    if (
      /mid-flight/.test(e.message) &&
      (await requestConfirm({
        title: "强制删除批次？",
        description:
          `批次仍有 worker 在处理。\n\n${e.message}\n\n` +
          "强制删除会让正在处理的 worker 在下次状态汇报时收到 404。",
        confirmText: "强制删除",
        tone: "danger",
      }))
    ) {
      deleteBatch.mutate(true);
      return;
    }
    toast.error(`删除失败：${e.message}`);
  },
});

const b = computed(() => batch.data.value);
const rows = computed(() => granules.data.value ?? []);
const batchEvents = computed(() => events.data.value ?? []);
const progressByGranule = computed(() => latestProgress.data.value ?? {});
const failedCount = computed(
  () => (b.value?.counts?.failed ?? 0) + (b.value?.counts?.blacklisted ?? 0),
);
// Server-authoritative; for batches with >200 granules the per-row sum from
// the granules query would underreport.
const exhaustedCount = computed(() => b.value?.objects_exhausted ?? 0);
const inflightCount = computed(() =>
  IN_FLIGHT_STATES.reduce((s, k) => s + (b.value?.counts?.[k] ?? 0), 0),
);
const eventCountLabel = computed(() =>
  events.data.value ? `${events.data.value.length} 条` : "加载中",
);

const stateOptions = computed(() =>
  STATE_FILTERS.map((f) => {
    const count =
      f.value === "all"
        ? sumCounts(b.value?.counts ?? {})
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
    description: `将取消尚未完成的 ${inflightCount.value} 条数据粒。\n\n已上传/已确认的不会被取消。`,
    confirmText: "取消批次",
    tone: "danger",
  });
  if (ok) cancelAll.mutate();
}

async function confirmDelete() {
  if (!b.value) return;
  const name = b.value.name;
  const total = sumCounts(b.value.counts ?? {});
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
        class="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
      >
        <Icon name="arrowLeft" :size="12" />
        批次列表
      </RouterLink>
      <div class="mt-2">
        <PageHeader :title="b?.name ?? batchId">
          <template #description>
            <span class="inline-flex items-center font-mono text-[11.5px] text-muted-foreground">
              {{ batchId }}
              <CopyButton :value="batchId" title="复制批次 ID" />
            </span>
          </template>
          <template v-if="b" #actions>
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
              v-if="exhaustedCount > 0"
              size="sm"
              :pending="resetExhausted.isPending.value"
              pending-label="重置中…"
              @click="resetExhausted.mutate()"
              title="清零所有已放弃产物的拉取失败计数 — 下次 receiver poll 重新派发"
            >
              重置已放弃 ({{ exhaustedCount }})
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
            <Button
              variant="destructive"
              size="sm"
              :pending="deleteBatch.isPending.value"
              pending-label="删除中…"
              @click="confirmDelete"
              title="永久删除该批次及其全部数据粒、产物、进度、事件"
            >
              删除
            </Button>
          </template>
        </PageHeader>
      </div>
    </div>

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
          v-if="b.eta_seconds != null"
          label="预计剩余"
          hint="按当前吞吐外推"
        >
          <span class="text-xs tabular-nums">≈ {{ fmtDuration(b.eta_seconds * 1000) }}</span>
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

    <Card>
      <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
        <div class="space-y-1.5">
          <CardTitle>数据粒</CardTitle>
          <CardDescription>按状态筛选 · 点击行展开阶段计时 / 进度时间线 / 该粒事件</CardDescription>
        </div>
        <Segmented v-model="filter" size="sm" :options="stateOptions" />
      </CardHeader>
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
    </Card>

    <BatchTimingCard
      :batch-id="batchId"
      :remaining="inflightCount"
      :eta-seconds="b?.eta_seconds ?? null"
    />

    <Card>
      <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
        <div class="space-y-1.5">
          <CardTitle>日志</CardTitle>
          <CardDescription>按级别筛选 · 仅本批次的事件</CardDescription>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-[11px] text-muted-foreground tabular-nums">
            {{ eventCountLabel }}
          </span>
          <Segmented
            v-model="logLevel"
            size="sm"
            :options="LOG_LEVEL_OPTIONS"
          />
        </div>
      </CardHeader>
      <BatchEventLog :events="batchEvents" :batch-id="batchId" />
    </Card>
  </div>
</template>
