<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, type GranuleRow, type GranuleState } from "../api";
import { fmtAge, fmtDuration, levelLabel, stateLabel } from "../i18n";
import { useToast } from "../composables/useToast";
import ActionButton from "../ui/ActionButton.vue";
import Badge from "../ui/Badge.vue";
import Card from "../ui/Card.vue";
import CopyButton from "../ui/CopyButton.vue";
import EmptyState from "../ui/EmptyState.vue";
import Field from "../ui/Field.vue";
import PageHeader from "../ui/PageHeader.vue";
import Segmented from "../ui/Segmented.vue";
import BatchTimingCard from "./BatchTimingCard.vue";
import ErrorCell from "./ErrorCell.vue";
import GranuleEvents from "./GranuleEvents.vue";
import LatestProgressLine from "./LatestProgressLine.vue";
import ProgressTimeline from "./ProgressTimeline.vue";
import StageTimingStrip from "./StageTimingStrip.vue";
import { Icon } from "../ui/Icon";

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

const CANCELLABLE = new Set<GranuleState>([
  "pending",
  "queued",
  "downloading",
  "downloaded",
  "processing",
  "processed",
]);
const RETRYABLE = new Set<GranuleState>(["failed", "blacklisted"]);
const INFLIGHT_STATES: GranuleState[] = [
  "pending",
  "queued",
  "downloading",
  "downloaded",
  "processing",
  "processed",
];

function stripBatchPrefix(gid: string, batchId: string) {
  return gid.startsWith(`${batchId}:`) ? gid.slice(batchId.length + 1) : gid;
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
  onError: (e: Error) => {
    if (
      /mid-flight/.test(e.message) &&
      confirm(
        `批次仍有 worker 在处理。\n\n${e.message}\n\n强制删除会让正在处理的 worker 在下次状态汇报时收到 404。是否继续？`,
      )
    ) {
      deleteBatch.mutate(true);
      return;
    }
    toast.error(`删除失败：${e.message}`);
  },
});

const b = computed(() => batch.data.value);
const rows = computed(() => granules.data.value ?? []);
const failedCount = computed(
  () => (b.value?.counts?.failed ?? 0) + (b.value?.counts?.blacklisted ?? 0),
);
// Server-authoritative; for batches with >200 granules the per-row sum from
// the granules query would underreport.
const exhaustedCount = computed(() => b.value?.objects_exhausted ?? 0);
const inflightCount = computed(() =>
  INFLIGHT_STATES.reduce((s, k) => s + (b.value?.counts?.[k] ?? 0), 0),
);

const stateOptions = computed(() =>
  STATE_FILTERS.map((f) => {
    const count =
      f.value === "all"
        ? Object.values(b.value?.counts ?? {}).reduce((s, n) => s + (n ?? 0), 0)
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

function confirmCancel(g: GranuleRow) {
  if (confirm(`取消数据粒 ${stripBatchPrefix(g.granule_id, batchId.value)}？`)) {
    cancel.mutate(g.granule_id);
  }
}

function confirmCancelAll() {
  if (
    b.value &&
    confirm(
      `取消批次 "${b.value.name}" 中尚未完成的 ${inflightCount.value} 条数据粒？\n\n已上传/已确认的不会被取消。`,
    )
  ) {
    cancelAll.mutate();
  }
}

function confirmDelete() {
  if (!b.value) return;
  const name = b.value.name;
  const total = Object.values(b.value.counts ?? {}).reduce((s, n) => s + (n ?? 0), 0);
  const typed = prompt(
    `永久删除批次 "${name}" 及其 ${total} 条数据粒？\n\n` +
      `此操作不可恢复，将清除该批次在 orchestrator 上的全部记录\n` +
      `（数据粒、产物、进度、阶段计时、事件）。worker 已上传的产物文件不在清理范围内。\n\n` +
      `请输入批次名称 "${name}" 确认：`,
  );
  if (typed === name) deleteBatch.mutate(false);
  else if (typed !== null) toast.error("名称不匹配，未删除");
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <RouterLink
        to="/batches"
        class="inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-text"
      >
        <Icon name="arrowLeft" :size="12" />
        批次列表
      </RouterLink>
      <div class="mt-2">
        <PageHeader :title="b?.name ?? batchId">
          <template #description>
            <span class="inline-flex items-center font-mono text-[11.5px] text-muted">
              {{ batchId }}
              <CopyButton :value="batchId" title="复制批次 ID" />
            </span>
          </template>
          <template v-if="b" #actions>
            <ActionButton
              v-if="failedCount > 0"
              size="sm"
              :pending="retryAll.isPending.value"
              pending-label="重试中…"
              @click="retryAll.mutate()"
            >
              重试失败 ({{ failedCount }})
            </ActionButton>
            <ActionButton
              v-if="exhaustedCount > 0"
              size="sm"
              :pending="resetExhausted.isPending.value"
              pending-label="重置中…"
              @click="resetExhausted.mutate()"
              title="清零所有已放弃产物的拉取失败计数 — 下次 receiver poll 重新派发"
            >
              重置已放弃 ({{ exhaustedCount }})
            </ActionButton>
            <ActionButton
              v-if="inflightCount > 0"
              tone="danger"
              size="sm"
              :pending="cancelAll.isPending.value"
              pending-label="取消中…"
              @click="confirmCancelAll"
            >
              取消 ({{ inflightCount }})
            </ActionButton>
            <ActionButton
              tone="danger"
              size="sm"
              :pending="deleteBatch.isPending.value"
              pending-label="删除中…"
              @click="confirmDelete"
              title="永久删除该批次及其全部数据粒、产物、进度、事件"
            >
              删除
            </ActionButton>
          </template>
        </PageHeader>
      </div>
    </div>

    <Card v-if="b" :padded="false">
      <div class="grid grid-cols-2 gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-4">
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

    <Card
      title="数据粒"
      description="按状态筛选 · 点击行展开阶段计时 / 进度时间线 / 该粒事件"
      :padded="false"
    >
      <template #action>
        <Segmented v-model="filter" size="sm" :options="stateOptions" />
      </template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-subtle/50 th-row">
            <tr>
              <th class="px-5 py-3">数据粒</th>
              <th class="px-2 py-3">状态</th>
              <th class="px-2 py-3">重试</th>
              <th class="px-2 py-3">领取方</th>
              <th class="px-2 py-3">更新</th>
              <th class="px-2 py-3">错误</th>
              <th class="px-5 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="g in rows" :key="g.granule_id">
              <tr
                :ref="(el) => setRowRef(g.granule_id, el as Element | null)"
                :class="[
                  'border-t border-border/60 align-top transition hover:bg-subtle/40',
                  g.granule_id === highlight ? 'bg-accent-soft/40' : '',
                ]"
              >
                <td class="px-5 py-2.5 font-mono text-[11.5px]">
                  <button
                    @click="toggleRow(g.granule_id)"
                    class="mr-1 inline-block w-3 text-muted hover:text-text"
                    :title="expanded === g.granule_id ? '收起进度' : '展开进度'"
                  >
                    {{ expanded === g.granule_id ? "▾" : "▸" }}
                  </button>
                  {{ stripBatchPrefix(g.granule_id, batchId) }}
                  <LatestProgressLine
                    v-if="latestProgress.data.value?.[g.granule_id]"
                    :row="latestProgress.data.value[g.granule_id]"
                  />
                </td>
                <td class="px-2 py-2.5">
                  <div class="flex flex-wrap items-center gap-1">
                    <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
                    <span
                      v-if="g.objects_exhausted > 0"
                      :title="`${g.objects_exhausted} 个产物超出 receiver 拉取重试上限，已停止派发`"
                    >
                      <Badge tone="error">{{ g.objects_exhausted }} 已放弃</Badge>
                    </span>
                  </div>
                </td>
                <td class="px-2 py-2.5 text-[11.5px] tabular-nums">{{ g.retry_count }}</td>
                <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted">
                  <RouterLink
                    v-if="g.leased_by"
                    :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                    class="transition hover:text-accent"
                    title="跳转到该 worker 卡片"
                  >
                    {{ g.leased_by }}
                  </RouterLink>
                  <template v-else>—</template>
                </td>
                <td class="px-2 py-2.5 text-[11.5px] text-muted">{{ fmtAge(g.updated_at) }}</td>
                <td class="max-w-[320px] px-2 py-2.5 font-mono text-[11.5px] text-danger">
                  <ErrorCell :error="g.error" />
                </td>
                <td class="space-x-1 whitespace-nowrap px-5 py-2.5 text-right">
                  <ActionButton
                    v-if="CANCELLABLE.has(g.state)"
                    tone="danger"
                    size="sm"
                    :pending="cancel.isPending.value && cancel.variables.value === g.granule_id"
                    pending-label="取消"
                    @click="confirmCancel(g)"
                  >
                    取消
                  </ActionButton>
                  <ActionButton
                    v-if="RETRYABLE.has(g.state)"
                    size="sm"
                    :pending="retry.isPending.value && retry.variables.value === g.granule_id"
                    pending-label="重试"
                    @click="retry.mutate(g.granule_id)"
                  >
                    重试
                  </ActionButton>
                </td>
              </tr>
              <tr v-if="expanded === g.granule_id" class="bg-subtle/40">
                <td colspan="7" class="space-y-3 px-5 py-3">
                  <StageTimingStrip :granule-id="g.granule_id" />
                  <ProgressTimeline :granule-id="g.granule_id" />
                  <GranuleEvents :granule-id="g.granule_id" :batch-id="batchId" />
                </td>
              </tr>
            </template>
            <tr v-if="rows.length === 0">
              <td colspan="7"><EmptyState title="该筛选条件下没有数据粒" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <BatchTimingCard
      :batch-id="batchId"
      :remaining="inflightCount"
      :eta-seconds="b?.eta_seconds ?? null"
    />

    <Card
      title="日志"
      description="按级别筛选 · 仅本批次的事件"
      :padded="false"
    >
      <template #action>
        <div class="flex items-center gap-3">
          <span class="text-[11px] text-muted tabular-nums">
            {{ events.data.value ? `${events.data.value.length} 条` : "加载中" }}
          </span>
          <Segmented
            v-model="logLevel"
            size="sm"
            :options="[
              { value: 'all', label: '全部' },
              { value: 'warn', label: '警告' },
              { value: 'error', label: '错误' },
            ]"
          />
        </div>
      </template>
      <div class="max-h-[50vh] overflow-auto font-mono">
        <EmptyState v-if="(events.data.value ?? []).length === 0" title="暂无该批次的事件" />
        <ul v-else class="divide-y divide-border/50">
          <li
            v-for="e in events.data.value ?? []"
            :key="e.id"
            class="flex items-start gap-3 px-5 py-2 text-[11.5px] transition hover:bg-subtle/40"
          >
            <span class="w-20 shrink-0 text-muted">{{ fmtAge(e.ts) }}</span>
            <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
            <span class="w-24 shrink-0 truncate text-muted">{{ e.source }}</span>
            <span
              v-if="e.granule_id"
              class="w-40 shrink-0 truncate text-muted"
              :title="e.granule_id"
            >
              {{ stripBatchPrefix(e.granule_id, batchId) }}
            </span>
            <span v-else class="w-40 shrink-0 text-muted">—</span>
            <span class="flex-1 break-all">{{ e.message }}</span>
          </li>
        </ul>
      </div>
    </Card>
  </div>
</template>
