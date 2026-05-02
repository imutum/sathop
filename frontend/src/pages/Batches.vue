<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";
import { API, IN_FLIGHT_STATES, type BatchSummary, type GranuleState } from "@/api";
import { fmtAge, fmtDuration } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import CopyButton from "@/components/CopyButton.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import QueryState from "@/components/QueryState.vue";
import Segmented from "@/components/Segmented.vue";
import TextInput from "@/ui/TextInput.vue";
import CreateBatchModal from "@/features/batch/components/CreateBatchModal.vue";
import { Icon } from "@/components/Icon";

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const ERRORED: GranuleState[] = ["failed", "blacklisted"];

type BatchListRow = {
  b: BatchSummary;
  total: number;
  done: number;
  errors: number;
  inFlight: number;
  pct: number;
  bundleLink: { name: string; version: string } | null;
};

const batchTotal = (b: BatchSummary) =>
  Object.values(b.counts).reduce((a, c) => a + (c ?? 0), 0);
const completedTotal = (b: BatchSummary) => TERMINAL.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const errorTotal = (b: BatchSummary) =>
  ERRORED.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const inFlightTotal = (b: BatchSummary) =>
  IN_FLIGHT_STATES.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
const isClosed = (b: BatchSummary) => {
  const t = batchTotal(b);
  const d = completedTotal(b);
  return t > 0 && d === t && errorTotal(b) === 0;
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

function matchesSearch(b: BatchSummary) {
  if (!needle.value) return true;
  return `${b.name} ${b.batch_id} ${b.bundle_ref}`.toLowerCase().includes(needle.value);
}

function toBatchListRow(b: BatchSummary): BatchListRow {
  const t = batchTotal(b);
  const d = completedTotal(b);
  return {
    b,
    total: t,
    done: d,
    errors: errorTotal(b),
    inFlight: inFlightTotal(b),
    pct: t > 0 ? Math.round((d / t) * 100) : 0,
    bundleLink: bundleLink(b.bundle_ref),
  };
}

const visible = computed(() =>
  all.value
    .filter((b) => {
      if (scope.value === "active" && isClosed(b)) return false;
      return matchesSearch(b);
    })
    .map(toBatchListRow),
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
  onError: async (e: Error, vars) => {
    if (
      /mid-flight/.test(e.message) &&
      (await requestConfirm({
        title: "强制删除批次？",
        description: `${e.message}\n\n强制删除会让正在处理的 worker 在下次状态汇报时收到 404。`,
        confirmText: "强制删除",
        tone: "danger",
      }))
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

async function confirmCancel(b: BatchSummary) {
  const ok = await requestConfirm({
    title: `取消批次 "${b.name}"？`,
    description: `将取消尚未完成的 ${inFlightTotal(b)} 条数据粒。\n\n已上传/已确认的不会被取消。`,
    confirmText: "取消批次",
    tone: "danger",
  });
  if (ok) cancel.mutate(b.batch_id);
}

async function confirmDelete(b: BatchSummary) {
  const t = batchTotal(b);
  const ok = await requestConfirm({
    title: `永久删除批次 "${b.name}"？`,
    description:
      `将删除 ${t} 条数据粒，并清除该批次的全部 orchestrator 记录\n` +
      `（数据粒、产物、进度、阶段计时、事件）。此操作不可恢复。`,
    confirmText: "永久删除",
    tone: "danger",
    requireText: b.name,
    inputLabel: `请输入批次名称 "${b.name}" 确认`,
  });
  if (ok) remove.mutate({ id: b.batch_id, force: false });
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
        <Button variant="default" @click="showCreate = true">
          <Icon name="plus" :size="13" />
          新建任务
        </Button>
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
      <div class="text-xs text-muted-foreground tabular-nums">
        显示 <span class="font-medium text-foreground">{{ visible.length }}</span> / {{ allCount }}
      </div>
    </div>

    <CreateBatchModal
      v-if="showCreate"
      :initial-bundle="pendingBundle ?? undefined"
      @close="closeCreate"
      @created="onCreated"
    />

    <Card>
      <QueryState :query="batches">
        <template #loading>
          <div class="space-y-2 p-5">
            <Skeleton v-for="n in 5" :key="n" class="h-14 w-full" />
          </div>
        </template>
        <template #error="{ error, retry: retryFetch }">
          <div class="p-5">
            <Alert variant="destructive">
              <AlertDescription class="flex items-center justify-between gap-3">
                <span>加载批次失败：{{ error.message }}</span>
                <Button size="sm" variant="outline" @click="retryFetch">重试</Button>
              </AlertDescription>
            </Alert>
          </div>
        </template>
        <template #empty>
          <EmptyState
            title="还没有任何批次"
            description="通过页面右上角“新建任务”创建第一个批次。"
          >
            <template #action>
              <Button variant="default" @click="showCreate = true">
                <Icon name="plus" :size="13" />
                新建任务
              </Button>
            </template>
          </EmptyState>
        </template>
        <template #default>
          <EmptyState
            v-if="visible.length === 0"
            title="当前筛选条件下没有匹配"
          />
          <template v-else>
          <!-- Narrow: card list. min-w-[820px] table needs lg+ to feel right. -->
          <ul class="divide-y divide-border/60 lg:hidden">
            <li v-for="r in visible" :key="r.b.batch_id" class="space-y-3 p-4">
              <div class="flex items-start justify-between gap-3">
                <RouterLink :to="`/batches/${r.b.batch_id}`" class="min-w-0 flex-1">
                  <div class="truncate font-medium text-foreground transition hover:text-primary">
                    {{ r.b.name }}
                  </div>
                  <div class="mt-0.5 inline-flex items-center font-mono text-[11px] text-muted-foreground">
                    {{ r.b.batch_id }}
                    <CopyButton :value="r.b.batch_id" title="复制批次 ID" />
                  </div>
                </RouterLink>
                <Badge tone="info" class="shrink-0">{{ r.b.target_receiver_id ?? "任意" }}</Badge>
              </div>
              <RouterLink
                v-if="r.bundleLink"
                :to="{
                  path: '/bundles',
                  query: { name: r.bundleLink.name, version: r.bundleLink.version },
                }"
                class="block truncate font-mono text-[11px] text-muted-foreground transition hover:text-primary"
                title="在任务包页查看"
              >
                {{ r.b.bundle_ref }}
              </RouterLink>
              <div v-else class="truncate font-mono text-[11px] text-muted-foreground">
                {{ r.b.bundle_ref }}
              </div>
              <div>
                <div class="mb-1 flex flex-wrap items-center justify-between gap-2 text-[11.5px]">
                  <span class="tabular-nums">
                    <span class="font-medium text-foreground">{{ r.done }}</span>
                    <span class="text-muted-foreground"> / {{ r.total }}</span>
                    <span class="ml-1 text-muted-foreground">({{ r.pct }}%)</span>
                  </span>
                  <span class="flex items-center gap-2">
                    <span
                      v-if="r.b.eta_seconds != null"
                      class="text-muted-foreground tabular-nums"
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
              </div>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="text-[11px] text-muted-foreground">{{ fmtAge(r.b.created_at) }}</span>
                <div class="flex flex-wrap gap-1.5">
                  <Button
                    v-if="r.errors > 0"
                    size="sm"
                    :pending="retry.isPending.value && retry.variables.value === r.b.batch_id"
                    pending-label="重试中…"
                    @click="retry.mutate(r.b.batch_id)"
                  >
                    重试失败 ({{ r.errors }})
                  </Button>
                  <Button
                    v-if="r.inFlight > 0"
                    variant="destructive"
                    size="sm"
                    :pending="cancel.isPending.value && cancel.variables.value === r.b.batch_id"
                    pending-label="取消中…"
                    @click="confirmCancel(r.b)"
                  >
                    取消 ({{ r.inFlight }})
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    :pending="
                      remove.isPending.value && remove.variables.value?.id === r.b.batch_id
                    "
                    pending-label="删除中…"
                    @click="confirmDelete(r.b)"
                    title="永久删除该批次及其所有数据粒、产物、进度、事件"
                  >
                    删除
                  </Button>
                </div>
              </div>
            </li>
          </ul>
          <!-- lg+ : original table. -->
          <div class="hidden overflow-x-auto lg:block">
        <table class="w-full min-w-[820px] text-sm">
          <thead class="bg-muted/50 th-row">
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
              class="border-t border-border/60 transition hover:bg-muted/40"
            >
              <td class="px-5 py-3.5">
                <RouterLink :to="`/batches/${r.b.batch_id}`" class="block">
                  <div class="font-medium text-foreground transition hover:text-primary">{{ r.b.name }}</div>
                  <div class="mt-0.5 inline-flex items-center font-mono text-[11px] text-muted-foreground">
                    {{ r.b.batch_id }}
                    <CopyButton :value="r.b.batch_id" title="复制批次 ID" />
                  </div>
                </RouterLink>
              </td>
              <td class="px-2 py-3.5 font-mono text-[11.5px] text-muted-foreground">
                <RouterLink
                  v-if="r.bundleLink"
                  :to="{
                    path: '/bundles',
                    query: { name: r.bundleLink.name, version: r.bundleLink.version },
                  }"
                  class="transition hover:text-primary"
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
                    <span class="font-medium text-foreground">{{ r.done }}</span>
                    <span class="text-muted-foreground"> / {{ r.total }}</span>
                    <span class="ml-1 text-muted-foreground">({{ r.pct }}%)</span>
                  </span>
                  <span class="flex items-center gap-2">
                    <span
                      v-if="r.b.eta_seconds != null"
                      class="text-muted-foreground tabular-nums"
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
              <td class="px-2 py-3.5 text-[11.5px] text-muted-foreground">{{ fmtAge(r.b.created_at) }}</td>
              <td class="space-x-1.5 whitespace-nowrap px-5 py-3.5 text-right">
                <Button
                  v-if="r.errors > 0"
                  size="sm"
                  :pending="retry.isPending.value && retry.variables.value === r.b.batch_id"
                  pending-label="重试中…"
                  @click="retry.mutate(r.b.batch_id)"
                >
                  重试失败 ({{ r.errors }})
                </Button>
                <Button
                  v-if="r.inFlight > 0"
                  variant="destructive"
                  size="sm"
                  :pending="cancel.isPending.value && cancel.variables.value === r.b.batch_id"
                  pending-label="取消中…"
                  @click="confirmCancel(r.b)"
                >
                  取消 ({{ r.inFlight }})
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  :pending="
                    remove.isPending.value && remove.variables.value?.id === r.b.batch_id
                  "
                  pending-label="删除中…"
                  @click="confirmDelete(r.b)"
                  title="永久删除该批次及其所有数据粒、产物、进度、事件"
                >
                  删除
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
          </template>
        </template>
      </QueryState>
    </Card>
  </div>
</template>
