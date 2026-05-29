<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import Segmented from "@/components/Segmented.vue";
import WorkerCard from "@/features/nodes/components/WorkerCard.vue";
import OnboardWorkerModal from "@/features/onboarding/components/OnboardWorkerModal.vue";
import { Icon } from "@/components/Icon";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import Modal from "@/ui/Modal.vue";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";

const qc = useQueryClient();
const toast = useToast();
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const list = computed(() => workers.data.value ?? []);

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
const shown = computed(() =>
  hasHistory.value && tab.value === "history" ? removedList.value : activeList.value,
);
const tabOptions = computed(() => [
  { value: "active", label: "活跃", count: activeCount.value },
  { value: "history", label: "历史", count: removedList.value.length },
]);

const updateAll = useMutation({
  mutationFn: () => API.updateAllWorkers(),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: [...K.workers] });
    toast.success(`已向 ${r.count} 个活跃节点发送更新信号`);
  },
  onError: (e: Error) => toast.error(`全部更新失败：${e.message}`),
});

async function onUpdateAll() {
  const ok = await requestConfirm({
    title: "更新全部工作节点？",
    description:
      "向所有活跃（未暂停）的 worker 发送更新信号。\n" +
      "它们会依次排空在手任务、拉取最新代码后重新启动。",
    confirmText: "全部更新",
  });
  if (ok) updateAll.mutate();
}

const removeAll = useMutation({
  mutationFn: () => API.removeAllWorkers(),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: [...K.workers] });
    toast.success(`已移除 ${r.count} 个工作节点`);
  },
  onError: (e: Error) => toast.error(`全部移除失败：${e.message}`),
});

async function onRemoveAll() {
  const ok = await requestConfirm({
    title: "移除全部工作节点？",
    description:
      "所有 worker 将在排空在手任务后自动停止，容器不再重启。\n" +
      "移除后节点 ID 不可再注册 — 如需恢复集群，需启动新的 worker。",
    confirmText: "全部移除",
    tone: "danger",
  });
  if (ok) removeAll.mutate();
}

// Multi-select for bulk concurrency. Only meaningful on the active tab; the
// per-worker concurrency editor on each card remains the primitive.
const selectMode = ref(false);
const selected = ref<Set<string>>(new Set());
const selectedCount = computed(() => selected.value.size);
const allSelected = computed(
  () => activeCount.value > 0 && selectedCount.value === activeCount.value,
);

function toggleSelect(id: string) {
  const next = new Set(selected.value);
  next.has(id) ? next.delete(id) : next.add(id);
  selected.value = next;
}
function toggleSelectAll() {
  selected.value = allSelected.value
    ? new Set()
    : new Set(activeList.value.map((w) => w.worker_id));
}
function exitSelect() {
  selectMode.value = false;
  selected.value = new Set();
}
// Leaving the active tab cancels selection so stale ids never linger.
watch(tab, (t) => {
  if (t !== "active") exitSelect();
});

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
    exitSelect();
  },
  onError: (e: Error) => toast.error(`批量设置失败：${e.message}`),
});

function openBulkConc() {
  bulkDl.value = "";
  bulkPr.value = "";
  showBulkConc.value = true;
}

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

// Deep-link: /workers?id=<worker_id> scrolls + ring-highlights one card. Used
// by leased_by cells in BatchDetail / Dashboard.
const route = useRoute();
const focusId = computed(() => (route.query.id as string | undefined) ?? null);
const cardRefs = ref<Record<string, HTMLElement | null>>({});

let lastScrolled: string | null = null;
function maybeScroll() {
  const id = focusId.value;
  if (!id || lastScrolled === id) return;
  const el = cardRefs.value[id];
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
      // the target card is rendered before maybeScroll() looks up its ref.
      const w = list.value.find((x) => x.worker_id === id);
      if (w) tab.value = w.removed_at != null ? "history" : "active";
    }
    void nextTick(maybeScroll);
  },
  { immediate: true },
);

function setRef(id: string, el: Element | null) {
  cardRefs.value[id] = el as HTMLElement | null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="工作节点" description="集群内已注册的 Worker · 心跳 / 资源 / 队列">
      <template #actions>
        <template v-if="tab === 'active' && selectMode">
          <span class="self-center text-2xs text-muted-foreground">已选 {{ selectedCount }}</span>
          <Button variant="outline" class="gap-1.5" @click="toggleSelectAll">
            {{ allSelected ? "清除" : "全选" }}
          </Button>
          <Button
            variant="default"
            class="gap-1.5"
            :disabled="selectedCount === 0"
            @click="openBulkConc"
          >
            设置并发
          </Button>
          <Button variant="ghost" class="gap-1.5 text-muted-foreground" @click="exitSelect">
            退出多选
          </Button>
        </template>
        <template v-else>
          <Button
            v-if="tab === 'active' && activeCount > 0"
            variant="outline"
            class="gap-1.5"
            @click="selectMode = true"
          >
            多选
          </Button>
          <Button
            v-if="tab === 'active' && activeCount > 0"
            variant="outline"
            class="gap-1.5"
            :disabled="updateAll.isPending.value"
            @click="onUpdateAll"
          >
            全部更新
          </Button>
          <Button
            v-if="tab === 'active' && activeCount > 0"
            variant="outline"
            class="gap-1.5 text-destructive hover:bg-destructive/10"
            :disabled="removeAll.isPending.value"
            @click="onRemoveAll"
          >
            全部移除
          </Button>
          <Button variant="default" class="gap-1.5" @click="showOnboard = true">
            <Icon name="plus" :size="13" />
            接入工作节点
          </Button>
        </template>
      </template>
    </PageHeader>

    <QueryState :query="workers">
      <template #loading>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton v-for="n in 3" :key="n" class="h-48 w-full" />
        </div>
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
          <Card v-if="shown.length === 0">
            <CardContent class="pt-6">
              <EmptyState
                :title="tab === 'history' ? '暂无历史节点' : '当前无活跃节点'"
                :description="tab === 'history' ? undefined : '已注册的节点都在历史中。'"
                illustration="inbox"
              />
            </CardContent>
          </Card>
          <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div
              v-for="w in shown"
              :key="w.worker_id"
              :ref="(el) => setRef(w.worker_id, el as Element | null)"
              class="relative"
            >
              <label
                v-if="selectMode && tab === 'active'"
                class="absolute right-3 top-3 z-10 flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-background/90 px-2 py-1 shadow-sm backdrop-blur"
              >
                <Checkbox
                  :model-value="selected.has(w.worker_id)"
                  @update:model-value="toggleSelect(w.worker_id)"
                />
                <span class="text-2xs text-muted-foreground">选中</span>
              </label>
              <WorkerCard :worker="w" :focused="focusId === w.worker_id" />
            </div>
          </div>
        </div>
      </template>
    </QueryState>

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
