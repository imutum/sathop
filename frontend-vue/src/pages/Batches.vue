<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, type BatchSummary, type GranuleState } from "../api";
import { fmtAge, fmtDuration } from "../i18n";
import { useToast } from "../composables/useToast";
import ActionButton from "../ui/ActionButton.vue";
import Badge from "../ui/Badge.vue";
import Card from "../ui/Card.vue";
import CopyButton from "../ui/CopyButton.vue";
import EmptyState from "../ui/EmptyState.vue";
import PageHeader from "../ui/PageHeader.vue";
import ProgressBar from "../ui/ProgressBar.vue";
import Segmented from "../ui/Segmented.vue";
import TextInput from "../ui/TextInput.vue";
import CreateBatchModal from "./CreateBatchModal.vue";
import { Icon } from "../ui/Icon";

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const ERRORED: GranuleState[] = ["failed", "blacklisted"];
const IN_FLIGHT: GranuleState[] = [
  "pending",
  "downloading",
  "downloaded",
  "processing",
  "processed",
];

const total = (b: BatchSummary) =>
  Object.values(b.counts).reduce((a, c) => a + (c ?? 0), 0);
const done = (b: BatchSummary) => TERMINAL.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const errors = (b: BatchSummary) =>
  ERRORED.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const inFlight = (b: BatchSummary) =>
  IN_FLIGHT.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const isClosed = (b: BatchSummary) => {
  const t = total(b);
  const d = done(b);
  return t > 0 && d === t && errors(b) === 0;
};

const qc = useQueryClient();
const toast = useToast();
const route = useRoute();
const router = useRouter();

const initialBundle = (route.query.bundle as string | undefined) ?? null;
const showCreate = ref(!!initialBundle);
const pendingBundle = ref<string | null>(initialBundle);

if (initialBundle) {
  const next = { ...route.query };
  delete next.bundle;
  router.replace({ query: next });
}

const search = ref((route.query.q as string | undefined) ?? "");
const scope = ref<"active" | "all">(route.query.scope === "all" ? "all" : "active");

watch([search, scope], ([s, sc]) => {
  const next: Record<string, string> = { ...(route.query as Record<string, string>) };
  if (s) next.q = s;
  else delete next.q;
  if (sc === "all") next.scope = "all";
  else delete next.scope;
  router.replace({ query: next });
});

const batches = useQuery({ queryKey: ["batches"], queryFn: API.batches });
const all = computed(() => batches.data.value ?? []);
const needle = computed(() => search.value.trim().toLowerCase());

const visible = computed(() =>
  all.value
    .filter((b) => {
      if (scope.value === "active" && isClosed(b)) return false;
      if (needle.value) {
        const hay = `${b.name} ${b.batch_id} ${b.bundle_ref}`.toLowerCase();
        if (!hay.includes(needle.value)) return false;
      }
      return true;
    })
    .map((b) => {
      const t = total(b);
      const d = done(b);
      return {
        b,
        total: t,
        done: d,
        errors: errors(b),
        inFlight: inFlight(b),
        pct: t > 0 ? Math.round((d / t) * 100) : 0,
        bundleLink: bundleLink(b.bundle_ref),
      };
    }),
);

const allCount = computed(() => all.value.length);
const activeCount = computed(() => all.value.filter((b) => !isClosed(b)).length);

const retry = useMutation({
  mutationFn: (id: string) => API.retryFailed(id),
  onSuccess: (res) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
  },
  onError: (e: Error) => toast.error(`重试失败：${e.message}`),
});

const cancel = useMutation({
  mutationFn: (id: string) => API.cancelBatch(id),
  onSuccess: (res) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    toast.success(`已取消 ${res.cancelled} 条数据粒`);
  },
  onError: (e: Error) => toast.error(`取消失败：${e.message}`),
});

const remove = useMutation({
  mutationFn: ({ id, force }: { id: string; force: boolean }) => API.deleteBatch(id, force),
  onSuccess: (res) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
    toast.success(`已删除批次：${res.granules} 数据粒 / ${res.objects} 产物`);
  },
  onError: (e: Error, vars) => {
    if (
      /mid-flight/.test(e.message) &&
      confirm(`${e.message}\n\n强制删除会让正在处理的 worker 在下次状态汇报时收到 404。是否继续？`)
    ) {
      remove.mutate({ id: vars.id, force: true });
      return;
    }
    toast.error(`删除失败：${e.message}`);
  },
});

function bundleLink(ref: string): { name: string; version: string } | null {
  if (!ref.startsWith("orch:")) return null;
  const [name, version = ""] = ref.slice(5).split("@");
  return { name, version };
}

function confirmCancel(b: BatchSummary) {
  if (
    confirm(
      `取消批次 "${b.name}" 中尚未完成的 ${inFlight(b)} 条数据粒？\n\n已上传/已确认的不会被取消。`,
    )
  ) {
    cancel.mutate(b.batch_id);
  }
}

function confirmDelete(b: BatchSummary) {
  const t = total(b);
  const typed = prompt(
    `永久删除批次 "${b.name}" 及其 ${t} 条数据粒？\n\n` +
      `不可恢复 — 将清除该批次的全部 orchestrator 记录\n` +
      `（数据粒、产物、进度、阶段计时、事件）。\n\n` +
      `请输入批次名称 "${b.name}" 确认：`,
  );
  if (typed === b.name) remove.mutate({ id: b.batch_id, force: false });
  else if (typed !== null) toast.error("名称不匹配，未删除");
}

function closeCreate() {
  showCreate.value = false;
  pendingBundle.value = null;
}

function onCreated() {
  closeCreate();
  qc.invalidateQueries({ queryKey: ["batches"] });
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="批次"
      description="管线提交单元 · 一个批次承载一组数据粒、统一的任务包与凭证"
    >
      <template #actions>
        <ActionButton tone="primary" @click="showCreate = true">
          <Icon name="plus" :size="13" />
          新建任务
        </ActionButton>
      </template>
    </PageHeader>

    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <div class="w-72">
          <TextInput
            v-model="search"
            placeholder="搜索：名称 / ID / 任务包"
            aria-label="搜索批次"
          >
            <template #leftIcon>
              <Icon name="search" :size="13" />
            </template>
          </TextInput>
        </div>
        <Segmented
          v-model="scope"
          :options="[
            { value: 'active', label: '进行中', count: activeCount },
            { value: 'all', label: '全部', count: allCount },
          ]"
        />
      </div>
      <div class="text-xs text-muted tabular-nums">
        显示 <span class="font-medium text-text">{{ visible.length }}</span> / {{ allCount }}
      </div>
    </div>

    <CreateBatchModal
      v-if="showCreate"
      :initial-bundle="pendingBundle ?? undefined"
      @close="closeCreate"
      @created="onCreated"
    />

    <Card :padded="false">
      <EmptyState
        v-if="visible.length === 0"
        :title="all.length === 0 ? '还没有任何批次' : '当前筛选条件下没有匹配'"
        :description="all.length === 0 ? '通过页面右上角“新建任务”创建第一个批次。' : undefined"
      >
        <template v-if="all.length === 0" #action>
          <ActionButton tone="primary" @click="showCreate = true">
            <Icon name="plus" :size="13" />
            新建任务
          </ActionButton>
        </template>
      </EmptyState>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[820px] text-sm">
          <thead class="bg-subtle/50 th-row">
            <tr>
              <th class="px-5 py-3">批次</th>
              <th class="px-2 py-3">处理包</th>
              <th class="px-2 py-3">目标接收端</th>
              <th class="px-2 py-3">进度</th>
              <th class="px-2 py-3">创建时间</th>
              <th class="px-5 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in visible"
              :key="r.b.batch_id"
              class="border-t border-border/60 transition hover:bg-subtle/40"
            >
              <td class="px-5 py-3.5">
                <RouterLink :to="`/batches/${r.b.batch_id}`" class="block">
                  <div class="font-medium text-text transition hover:text-accent">{{ r.b.name }}</div>
                  <div class="mt-0.5 inline-flex items-center font-mono text-[11px] text-muted">
                    {{ r.b.batch_id }}
                    <CopyButton :value="r.b.batch_id" title="复制批次 ID" />
                  </div>
                </RouterLink>
              </td>
              <td class="px-2 py-3.5 font-mono text-[11.5px] text-muted">
                <RouterLink
                  v-if="r.bundleLink"
                  :to="{
                    path: '/bundles',
                    query: { name: r.bundleLink.name, version: r.bundleLink.version },
                  }"
                  class="transition hover:text-accent"
                  title="在任务包页查看"
                >
                  {{ r.b.bundle_ref }}
                </RouterLink>
                <template v-else>{{ r.b.bundle_ref }}</template>
              </td>
              <td class="px-2 py-3.5">
                <Badge tone="info">{{ r.b.target_receiver_id ?? "任意" }}</Badge>
              </td>
              <td class="w-[280px] px-2 py-3.5">
                <div class="mb-1 flex items-center justify-between text-[11.5px]">
                  <span class="tabular-nums">
                    <span class="font-medium text-text">{{ r.done }}</span>
                    <span class="text-muted"> / {{ r.total }}</span>
                    <span class="ml-1 text-muted">({{ r.pct }}%)</span>
                  </span>
                  <span class="flex items-center gap-2">
                    <span
                      v-if="r.b.eta_seconds != null"
                      class="text-muted tabular-nums"
                      :title="`按当前吞吐外推剩余 ${r.inFlight} 条`"
                    >
                      ≈ {{ fmtDuration(r.b.eta_seconds * 1000) }}
                    </span>
                    <span v-if="r.errors > 0" class="text-danger">失败 {{ r.errors }}</span>
                    <span
                      v-if="r.b.objects_exhausted > 0"
                      class="text-danger"
                      title="该批次有产物已超 receiver 拉取重试上限，停止派发"
                    >
                      已放弃 {{ r.b.objects_exhausted }}
                    </span>
                  </span>
                </div>
                <ProgressBar
                  :value="r.done"
                  :max="r.total"
                  :tone="r.errors > 0 || r.b.objects_exhausted > 0 ? 'warn' : 'good'"
                />
              </td>
              <td class="px-2 py-3.5 text-[11.5px] text-muted">{{ fmtAge(r.b.created_at) }}</td>
              <td class="space-x-1.5 whitespace-nowrap px-5 py-3.5 text-right">
                <ActionButton
                  v-if="r.errors > 0"
                  size="sm"
                  :pending="retry.isPending.value && retry.variables.value === r.b.batch_id"
                  pending-label="重试中…"
                  @click="retry.mutate(r.b.batch_id)"
                >
                  重试失败 ({{ r.errors }})
                </ActionButton>
                <ActionButton
                  v-if="r.inFlight > 0"
                  tone="danger"
                  size="sm"
                  :pending="cancel.isPending.value && cancel.variables.value === r.b.batch_id"
                  pending-label="取消中…"
                  @click="confirmCancel(r.b)"
                >
                  取消 ({{ r.inFlight }})
                </ActionButton>
                <ActionButton
                  tone="danger"
                  size="sm"
                  :pending="
                    remove.isPending.value && remove.variables.value?.id === r.b.batch_id
                  "
                  pending-label="删除中…"
                  @click="confirmDelete(r.b)"
                  title="永久删除该批次及其所有数据粒、产物、进度、事件"
                >
                  删除
                </ActionButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
