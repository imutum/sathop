<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API, type WorkerInfo } from "@/api";
import { K } from "@/queryKeys";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import Segmented from "@/components/Segmented.vue";
import WorkerRow from "@/features/nodes/components/WorkerRow.vue";
import WorkerDrawer from "@/features/nodes/components/WorkerDrawer.vue";
import OnboardWorkerModal from "@/features/onboarding/components/OnboardWorkerModal.vue";
import Modal from "@/ui/Modal.vue";
import { Icon } from "@/components/Icon";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useLatestRelease } from "@/composables/useVersionCheck";

const qc = useQueryClient();
const toast = useToast();
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const list = computed(() => workers.data.value ?? []);

// Target release for "更新" — the newest version (resolved server-side, shared
// query). null while unknown ⇒ the update degrades to a same-version restart.
const latest = useLatestRelease();
const updateTarget = computed(() => (latest.data.value?.tag ?? "").replace(/^v/, "") || null);

// Active vs history (removed) split. Removed nodes get their own tab so the
// common case — a screenful of live nodes — never has to scroll past tombstones.
const activeList = computed(() => list.value.filter((w) => w.removed_at == null));
const removedList = computed(() => list.value.filter((w) => w.removed_at != null));
const activeCount = computed(() => activeList.value.length);
const hasHistory = computed(() => removedList.value.length > 0);

type Tab = "active" | "history";
const tab = ref<Tab>("active");
// History is only reachable when it exists; if the last removed node is purged
// while history is open, fall back to active.
watch(hasHistory, (h) => {
  if (!h) tab.value = "active";
});
// Rows of the current tab, in display order — the basis for select-all + shift range.
const rows = computed(() =>
  hasHistory.value && tab.value === "history" ? removedList.value : activeList.value,
);
const tabOptions = computed(() => [
  { value: "active", label: "活跃", count: activeCount.value },
  { value: "history", label: "历史", count: removedList.value.length },
]);

// ── Selection (always-on, scoped to current tab) ────────────────────────────
const selected = ref<Set<string>>(new Set());
const selectedCount = computed(() => selected.value.size);
let lastIndex = -1; // last toggled row index within current tab, for shift-range

function toggle(id: string, shiftKey: boolean) {
  const ids = rows.value.map((w) => w.worker_id);
  const i = ids.indexOf(id);
  const next = new Set(selected.value);
  if (shiftKey && lastIndex >= 0 && i >= 0) {
    const [lo, hi] = lastIndex < i ? [lastIndex, i] : [i, lastIndex];
    const turnOn = !next.has(id);
    for (let k = lo; k <= hi; k++) turnOn ? next.add(ids[k]) : next.delete(ids[k]);
  } else {
    next.has(id) ? next.delete(id) : next.add(id);
  }
  lastIndex = i;
  selected.value = next;
}

const allSelected = computed(
  () => rows.value.length > 0 && rows.value.every((w) => selected.value.has(w.worker_id)),
);
const indeterminate = computed(() => selectedCount.value > 0 && !allSelected.value);
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(rows.value.map((w) => w.worker_id));
  lastIndex = -1;
}
function clearSelection() {
  selected.value = new Set();
  lastIndex = -1;
}
// Switching tabs clears selection so stale ids never linger across active/history.
watch(tab, clearSelection);

// ── Batch dispatch: client-side fan-out over the existing per-worker fns ─────
const batchPending = ref(false);

function summarize(verb: string, results: PromiseSettledResult<unknown>[]) {
  const failed = results.filter((r) => r.status === "rejected").length;
  const ok = results.length - failed;
  if (failed === 0) toast.success(`已对 ${ok} 个节点${verb}`);
  else if (ok === 0) toast.error(`${verb}失败：${failed} 个节点`);
  else toast.error(`已对 ${ok} 个节点${verb}，${failed} 个失败`);
}

async function fanOut(verb: string, fn: (id: string) => Promise<unknown>) {
  const ids = [...selected.value];
  if (ids.length === 0) return;
  batchPending.value = true;
  const results = await Promise.allSettled(ids.map(fn));
  batchPending.value = false;
  qc.invalidateQueries({ queryKey: [...K.workers] });
  summarize(verb, results);
  clearSelection();
}

async function onBatchUpdate() {
  const n = selectedCount.value;
  if (n === 0) return;
  const target = updateTarget.value;
  const ok = await requestConfirm({
    title: target ? `升级 ${n} 个节点到 v${target}？` : `重启 ${n} 个节点？`,
    description: target
      ? `所选 worker 在下次心跳后各自排空在手任务、写入待装版本 v${target} 并重启，由 entrypoint 拉取该版本发布包安装。混版期间管道仍正常流转，建议分批操作以免吞吐断崖。`
      : "未能确定最新版本，将发送同版本重启信号（排空在手任务后重启，版本不变）。",
    confirmText: target ? "升级并重启" : "重启",
    tone: "danger",
  });
  if (!ok) return;
  void fanOut(target ? `升级到 v${target}` : "重启", (id) => API.updateWorker(id, target));
}
function onBatchPause() {
  void fanOut("暂停领新任务", (id) => API.setWorkerPaused(id, true));
}
function onBatchResume() {
  void fanOut("恢复", (id) => API.setWorkerPaused(id, false));
}
function onBatchGc() {
  void fanOut("发送清理信号", (id) => API.workerGc(id));
}

async function onBatchRevoke() {
  const n = selectedCount.value;
  const ok = await requestConfirm({
    title: `释放 ${n} 个节点的在手 lease？`,
    description:
      "把这些节点持有的全部在手 lease 重置回 待分配，等其他 worker 抢占。\n" +
      "已下载/已处理的中间产物会被丢弃；retry_count 会 +1，仍受 max_retries 限制。",
    confirmText: "立即释放",
    tone: "danger",
  });
  if (!ok) return;
  await fanOut("释放在手 lease", (id) => API.revokeWorkerLeases(id));
  qc.invalidateQueries({ queryKey: [...K.batches] });
}

async function onBatchRemove() {
  const n = selectedCount.value;
  const ok = await requestConfirm({
    title: `移除 ${n} 个工作节点？`,
    description:
      "这些节点将被永久移除，容器会在排空任务后自动停止。\n" +
      "移除后节点 ID 不可再注册 — 如需恢复，请启动新的 worker。",
    confirmText: "移除",
    tone: "danger",
  });
  if (ok) await fanOut("发送移除信号", (id) => API.removeWorker(id));
}

async function onBatchPurge() {
  const n = selectedCount.value;
  const ok = await requestConfirm({
    title: `彻底删除 ${n} 个节点记录？`,
    description:
      "从注册表中物理删除这些节点记录（已上传产物与事件日志不受影响，各自按保留周期老化）。\n" +
      "如果对应容器仍在运行，删除后它会以新节点身份重新注册。",
    confirmText: "彻底删除",
    tone: "danger",
  });
  if (ok) await fanOut("彻底删除", (id) => API.purgeWorker(id));
}

// ── Batch concurrency (bulk endpoint) ────────────────────────────────────────
const showBulkConc = ref(false);
const bulkDl = ref("");
const bulkPr = ref("");

const setConcurrencyBulk = useMutation({
  mutationFn: (body: { download_concurrency: number | null; process_concurrency: number | null }) =>
    API.setWorkersConcurrency([...selected.value], body),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: [...K.workers] });
    toast.success(`已向 ${r.applied.length} 个节点下发并发设置，下次心跳收敛`);
    showBulkConc.value = false;
    clearSelection();
  },
  onError: (e: Error) => toast.error(`批量设置失败：${e.message}`),
});

function openBulkConc() {
  bulkDl.value = "";
  bulkPr.value = "";
  showBulkConc.value = true;
}

// type=number 的 v-model 会回吐 number，先 String(...) 再 trim 才安全。
function parseConc(s: string): number | null | undefined {
  const t = String(s ?? "").trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isInteger(n) && n >= 1 ? n : undefined;
}

function submitBulkConc() {
  const dl = parseConc(bulkDl.value);
  const pr = parseConc(bulkPr.value);
  if (dl === undefined || pr === undefined) {
    toast.error("并发必须是 ≥ 1 的整数，留空表示用各节点默认值");
    return;
  }
  setConcurrencyBulk.mutate({ download_concurrency: dl, process_concurrency: pr });
}

const showOnboard = ref(false);

// ── Detail drawer ────────────────────────────────────────────────────────────
// openWorkerId is resolved against the live list each render, so the drawer
// live-updates while open (SSE refetch flows through), and closes if the worker
// disappears (e.g. purged elsewhere).
const openWorkerId = ref<string | null>(null);
const drawerWorker = computed<WorkerInfo | null>(
  () => list.value.find((w) => w.worker_id === openWorkerId.value) ?? null,
);
const drawerOpen = computed({
  get: () => openWorkerId.value != null && drawerWorker.value != null,
  set: (v) => {
    if (!v) openWorkerId.value = null;
  },
});

// ── Deep-link: /workers?id=<worker_id> scrolls + highlights one row ──────────
const route = useRoute();
const focusId = computed(() => (route.query.id as string | undefined) ?? null);
const rowEls = ref<Record<string, HTMLElement | null>>({});

let lastScrolled: string | null = null;
function maybeScroll() {
  const id = focusId.value;
  if (!id || lastScrolled === id) return;
  const el = rowEls.value[id];
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  lastScrolled = id;
}

watch(
  [focusId, list],
  () => {
    const id = focusId.value;
    if (id) {
      // A deep-linked removed worker lives in the history tab — switch to it so
      // the target row is rendered before maybeScroll() looks up its ref.
      const w = list.value.find((x) => x.worker_id === id);
      if (w) tab.value = w.removed_at != null ? "history" : "active";
    }
    void nextTick(maybeScroll);
  },
  { immediate: true },
);

function setRowRef(id: string, el: Element | null) {
  rowEls.value[id] = el as HTMLElement | null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="工作节点" description="集群内已注册的 Worker · 心跳 / 资源 / 队列">
      <template #actions>
        <Button variant="default" class="gap-1.5" @click="showOnboard = true">
          <Icon name="plus" :size="13" />
          接入工作节点
        </Button>
      </template>
    </PageHeader>

    <QueryState :query="workers">
      <template #loading>
        <Skeleton class="h-64 w-full" />
      </template>
      <template #error="{ error, retry }">
        <Alert variant="destructive">
          <AlertDescription class="flex items-center justify-between gap-3">
            <span>加载工作节点失败：{{ error.message }}</span>
            <Button size="sm" variant="outline" @click="retry">重试</Button>
          </AlertDescription>
        </Alert>
      </template>
      <template #empty>
        <Card>
          <CardContent class="pt-6">
            <EmptyState
              title="暂无已注册的工作节点"
              description="点下方按钮生成接入命令，复制到目标机器执行即可。"
              illustration="inbox"
            >
              <template #action>
                <Button variant="default" class="gap-1.5" @click="showOnboard = true">
                  <Icon name="plus" :size="13" />
                  接入工作节点
                </Button>
              </template>
            </EmptyState>
          </CardContent>
        </Card>
      </template>
      <template #default>
        <div class="space-y-4">
          <Segmented
            v-if="hasHistory"
            v-model="tab"
            :options="tabOptions"
            aria-label="活跃 / 历史 工作节点"
          />

          <!-- 批量工具栏：>=1 选中时出现 -->
          <div
            v-if="selectedCount > 0"
            class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2"
          >
            <span class="text-2xs font-medium text-foreground">已选 {{ selectedCount }}</span>
            <Button
              variant="ghost"
              size="xs"
              class="text-muted-foreground hover:text-foreground"
              @click="clearSelection"
            >
              清除
            </Button>
            <span class="mx-1 h-4 w-px bg-border" />
            <template v-if="tab === 'active'">
              <Button variant="outline" size="xs" :disabled="batchPending" @click="onBatchUpdate">更新</Button>
              <Button variant="outline" size="xs" :disabled="batchPending" @click="onBatchPause">暂停</Button>
              <Button variant="outline" size="xs" :disabled="batchPending" @click="onBatchResume">恢复</Button>
              <Button variant="outline" size="xs" :disabled="batchPending" @click="onBatchGc">清缓存</Button>
              <Button
                variant="outline"
                size="xs"
                class="text-danger hover:bg-danger/10"
                :disabled="batchPending"
                @click="onBatchRevoke"
              >
                释放lease
              </Button>
              <Button variant="outline" size="xs" :disabled="batchPending" @click="openBulkConc">设并发</Button>
              <Button
                variant="outline"
                size="xs"
                class="text-danger hover:bg-danger/10"
                :disabled="batchPending"
                @click="onBatchRemove"
              >
                移除
              </Button>
            </template>
            <Button
              v-else
              variant="outline"
              size="xs"
              class="text-danger hover:bg-danger/10"
              :disabled="batchPending"
              @click="onBatchPurge"
            >
              彻底删除
            </Button>
          </div>

          <Card v-if="rows.length === 0">
            <CardContent class="pt-6">
              <EmptyState
                :title="tab === 'history' ? '暂无历史节点' : '当前无活跃节点'"
                :description="tab === 'history' ? undefined : '已注册的节点都在历史中。'"
                illustration="inbox"
              />
            </CardContent>
          </Card>

          <Card v-else>
            <CardContent class="p-0">
              <Table>
                <TableHeader>
                  <TableRow v-if="tab === 'active'">
                    <TableHead class="w-8">
                      <Checkbox
                        :model-value="indeterminate ? 'indeterminate' : allSelected"
                        aria-label="全选当前页"
                        @update:model-value="toggleAll"
                      />
                    </TableHead>
                    <TableHead class="w-6" />
                    <TableHead>节点</TableHead>
                    <TableHead>CPU</TableHead>
                    <TableHead>内存</TableHead>
                    <TableHead>磁盘</TableHead>
                    <TableHead>并发</TableHead>
                    <TableHead>队列</TableHead>
                    <TableHead>心跳</TableHead>
                    <TableHead class="w-8" />
                  </TableRow>
                  <TableRow v-else>
                    <TableHead class="w-8">
                      <Checkbox
                        :model-value="indeterminate ? 'indeterminate' : allSelected"
                        aria-label="全选当前页"
                        @update:model-value="toggleAll"
                      />
                    </TableHead>
                    <TableHead class="w-16">状态</TableHead>
                    <TableHead>节点</TableHead>
                    <TableHead>最后心跳</TableHead>
                    <TableHead class="w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <template v-for="w in rows" :key="w.worker_id">
                    <WorkerRow
                      :ref="(c: any) => setRowRef(w.worker_id, c?.$el ?? null)"
                      :worker="w"
                      :tab="tab"
                      :selected="selected.has(w.worker_id)"
                      @toggle="toggle(w.worker_id, $event)"
                      @open="openWorkerId = w.worker_id"
                    />
                  </template>
                  <TableEmpty v-if="rows.length === 0" :colspan="tab === 'active' ? 10 : 5">
                    无数据
                  </TableEmpty>
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      </template>
    </QueryState>

    <WorkerDrawer v-model:open="drawerOpen" :worker="drawerWorker" />

    <OnboardWorkerModal v-if="showOnboard" @close="showOnboard = false" />

    <Modal v-if="showBulkConc" width-class="w-[min(420px,95vw)]" @close="showBulkConc = false">
      <h2 class="mb-1 text-base font-semibold">批量设置并发</h2>
      <p class="mb-4 text-2xs text-muted-foreground">
        对已选的 {{ selectedCount }} 个节点统一下发。留空 = 用各节点默认值（清除覆盖）。
        节点流水线天花板 = 下载并发 + 处理并发；调大瞬时生效，调小会触发一次短暂排空后重建。
      </p>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <Label for="bulk-dl">下载并发</Label>
          <Input id="bulk-dl" v-model="bulkDl" type="number" min="1" placeholder="默认" class="tabular-nums" />
        </div>
        <div>
          <Label for="bulk-pr">处理并发</Label>
          <Input id="bulk-pr" v-model="bulkPr" type="number" min="1" placeholder="默认" class="tabular-nums" />
        </div>
      </div>
      <div class="mt-5 flex justify-end gap-2">
        <Button variant="ghost" @click="showBulkConc = false">取消</Button>
        <Button
          variant="default"
          :disabled="setConcurrencyBulk.isPending.value"
          @click="submitBulkConc"
        >
          下发
        </Button>
      </div>
    </Modal>
  </div>
</template>
