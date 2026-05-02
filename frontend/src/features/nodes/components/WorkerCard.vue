<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { API, type WorkerInfo } from "@/api";
import { fmtGB, nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useToast } from "@/composables/useToast";
import { Badge } from "@/components/ui/badge";
import CopyButton from "@/components/CopyButton.vue";
import NodeLifecycleActions from "@/features/nodes/components/NodeLifecycleActions.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import TextInput from "@/ui/TextInput.vue";
import Crosshair from "@/components/chrome/Crosshair.vue";
import { Icon } from "@/components/Icon";

const props = defineProps<{ worker: WorkerInfo; focused?: boolean }>();

const qc = useQueryClient();
const toast = useToast();

const enable = useMutation({
  mutationFn: (next: boolean) => API.setWorkerEnabled(props.worker.worker_id, next),
  onSuccess: (_r, next) => {
    qc.invalidateQueries({ queryKey: ["workers"] });
    toast.success(next ? "已启用" : "已禁用，已在手任务排空后停止接新单");
  },
  onError: (e: Error) => toast.error(`失败：${e.message}`),
});

const forget = useMutation({
  mutationFn: () => API.forgetWorker(props.worker.worker_id),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["workers"] });
    toast.success(`已删除节点 ${props.worker.worker_id}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

const lifecyclePending = computed(() => enable.isPending.value || forget.isPending.value);

const status = computed(() =>
  nodeStatusBadge(props.worker.enabled, props.worker.last_seen),
);

const diskPct = computed(() =>
  props.worker.disk_total_gb > 0
    ? (props.worker.disk_used_gb / props.worker.disk_total_gb) * 100
    : 0,
);
const diskTone = computed<"bad" | "warn" | "accent">(() => {
  const p = diskPct.value;
  if (p > 80) return "bad";
  if (p > 60) return "warn";
  return "accent";
});

const draft = ref<string | null>(null);
const draftInput = ref<InstanceType<typeof TextInput> | null>(null);
watch(draft, (v) => {
  if (v !== null) void nextTick(() => draftInput.value?.focus());
});
const setCap = useMutation({
  mutationFn: (n: number | null) => API.setWorkerCapacity(props.worker.worker_id, n),
  onSuccess: (_r, n) => {
    qc.invalidateQueries({ queryKey: ["workers"] });
    toast.success(n == null ? "已清除并发上限" : `已设并发上限 ${n}`);
    draft.value = null;
  },
  onError: (e: Error) => toast.error(`设置失败：${e.message}`),
});

const effective = computed(() =>
  Math.min(props.worker.capacity, props.worker.desired_capacity ?? props.worker.capacity),
);

function startEdit() {
  draft.value =
    props.worker.desired_capacity != null ? String(props.worker.desired_capacity) : "";
}

function submitDraft() {
  const t = (draft.value ?? "").trim();
  if (t === "") {
    setCap.mutate(null);
    return;
  }
  const n = Number(t);
  if (!Number.isInteger(n) || n < 1 || n > props.worker.capacity) {
    toast.error(`并发上限必须是 1–${props.worker.capacity} 的整数`);
    return;
  }
  setCap.mutate(n);
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter") submitDraft();
  if (e.key === "Escape") draft.value = null;
}
</script>

<template>
  <div
    :class="[
      'relative overflow-hidden rounded-md border bg-card text-card-foreground shadow-card transition',
      focused
        ? 'border-primary/60 shadow-glow ring-1 ring-primary/30'
        : 'border-border',
    ]"
  >
    <Crosshair :tone="focused ? 'primary' : 'muted'" :inset="5" :size="9" />

    <!-- Header strip — channel code, ID, copy, status chip -->
    <div class="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
      <div class="min-w-0 space-y-1.5">
        <div class="flex items-center gap-2 text-3xs uppercase tracking-section text-muted-foreground readout">
          <span class="text-primary">WRK</span>
          <span aria-hidden class="h-2 w-px bg-border" />
          <span>NODE</span>
        </div>
        <div class="flex items-center gap-1 readout text-[13px] font-semibold">
          <span class="truncate">{{ worker.worker_id }}</span>
          <CopyButton :value="worker.worker_id" title="复制节点 ID" />
        </div>
        <div
          class="readout truncate text-3xs text-muted-foreground"
          :title="worker.public_url ?? ''"
        >
          {{ worker.public_url ?? "—" }}
        </div>
      </div>
      <div class="flex shrink-0 flex-col items-end gap-1.5">
        <Badge :tone="status.tone" dot>{{ status.label }}</Badge>
        <span
          v-if="worker.paused"
          class="readout inline-flex items-center gap-1 rounded-sm border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-section text-warning"
          :title="`worker 已自我暂停 — 当前磁盘 ${diskPct.toFixed(0)}%，等待降到恢复阈值再领新任务`"
        >
          <span class="h-1 w-1 rounded-full bg-warning" />
          PAUSED
        </span>
      </div>
    </div>

    <!-- Telemetry grid: CPU / Mem / Egress -->
    <div class="grid grid-cols-3 gap-px bg-border">
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">CPU</div>
        <div class="font-display text-[20px] font-medium leading-none tabular-nums">
          {{ worker.cpu_percent.toFixed(0) }}<span class="text-base text-muted-foreground">%</span>
        </div>
      </div>
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">MEM</div>
        <div class="font-display text-[20px] font-medium leading-none tabular-nums">
          {{ worker.mem_percent.toFixed(0) }}<span class="text-base text-muted-foreground">%</span>
        </div>
      </div>
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">EGRESS · MO</div>
        <div class="font-display text-[20px] font-medium leading-none tabular-nums">
          {{ fmtGB(worker.monthly_egress_gb) }}
        </div>
      </div>
    </div>

    <!-- Disk gauge -->
    <div class="space-y-1.5 px-5 pt-4">
      <div class="flex items-center justify-between text-3xs uppercase tracking-section text-muted-foreground readout">
        <span>DISK</span>
        <span class="tabular-nums text-foreground/80">
          {{ fmtGB(worker.disk_used_gb) }} <span class="text-muted-foreground">/</span> {{ fmtGB(worker.disk_total_gb) }}
        </span>
      </div>
      <ProgressBar :value="worker.disk_used_gb" :max="worker.disk_total_gb" :tone="diskTone" />
    </div>

    <!-- Queue stages -->
    <div class="mx-5 my-4 grid grid-cols-4 gap-px overflow-hidden rounded-sm border border-border bg-border">
      <div class="space-y-0.5 bg-card px-2 py-2.5 text-center">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">QUEUE</div>
        <div class="font-display text-[17px] font-medium tabular-nums">{{ worker.queue_queued }}</div>
      </div>
      <div class="space-y-0.5 bg-card px-2 py-2.5 text-center">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">DL</div>
        <div class="font-display text-[17px] font-medium tabular-nums">{{ worker.queue_downloading }}</div>
      </div>
      <div class="space-y-0.5 bg-card px-2 py-2.5 text-center">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">PROC</div>
        <div class="font-display text-[17px] font-medium tabular-nums">{{ worker.queue_processing }}</div>
      </div>
      <div class="space-y-0.5 bg-card px-2 py-2.5 text-center">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">UP</div>
        <div class="font-display text-[17px] font-medium tabular-nums">{{ worker.queue_uploading }}</div>
      </div>
    </div>

    <!-- Footer: capacity editor + actions + heartbeat -->
    <div class="flex items-center justify-between gap-3 border-t border-border px-5 py-2.5 text-3xs text-muted-foreground readout uppercase tracking-section">
      <span class="flex items-center gap-1.5">
        <span>CAP</span>
        <span class="text-foreground tabular-nums">{{ effective }}/{{ worker.capacity }}</span>
        <template v-if="draft !== null">
          <TextInput
            ref="draftInput"
            type="number"
            :min="1"
            :max="worker.capacity"
            :model-value="draft"
            @update:model-value="draft = $event"
            @keydown="onKey"
            :disabled="setCap.isPending.value"
            placeholder="env"
            class="w-14 readout text-2xs tabular-nums"
          />
          <button
            @click="submitDraft"
            :disabled="setCap.isPending.value"
            class="rounded-sm bg-primary/15 px-1.5 py-0.5 text-mini font-semibold text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            SAVE
          </button>
          <button
            @click="draft = null"
            :disabled="setCap.isPending.value"
            class="text-mini text-muted-foreground hover:text-foreground"
          >
            ×
          </button>
        </template>
        <button
          v-else
          @click="startEdit"
          class="rounded-sm border border-border bg-background px-1.5 py-0.5 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          title="改实际并发上限（不超过容器启动设置的容量）"
        >
          {{ worker.desired_capacity != null ? "EDIT" : "LIMIT" }}
        </button>
      </span>
      <div class="flex items-center gap-3 normal-case tracking-normal">
        <RouterLink
          :to="`/events?source=${encodeURIComponent(worker.worker_id)}`"
          class="readout inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-background px-2 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-primary"
          title="查看该 worker 的事件流"
        >
          <Icon name="events" :size="11" />
          LOG
        </RouterLink>
        <NodeLifecycleActions
          :enabled="worker.enabled"
          :pending="lifecyclePending"
          @set-enabled="enable.mutate"
          @forget="forget.mutate"
          :disable-confirm="`禁用 worker ${worker.worker_id}？\n\n已 lease 的任务继续完成；不会再领新任务。`"
          :forget-confirm="`从注册表中移除 ${worker.worker_id}？\n\n仅删除元数据；如果它仍持有任务会被服务端拒绝。`"
          disable-title="禁用此节点（在手任务继续）"
          forget-title="永久从注册表中删除（仅在已禁用且无任务时允许）"
        />
        <span class="readout text-3xs">↻ {{ fmtAge(worker.last_seen) }}</span>
      </div>
    </div>
  </div>
</template>
