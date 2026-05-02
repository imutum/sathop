<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { API, type WorkerInfo } from "@/api";
import { fmtGB, nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useToast } from "@/composables/useToast";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import CopyButton from "@/components/CopyButton.vue";
import HintTip from "@/components/HintTip.vue";
import NodeLifecycleActions from "@/features/nodes/components/NodeLifecycleActions.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import TextInput from "@/ui/TextInput.vue";
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

// Capacity editor: draft=null ⇒ display mode; draft=string ⇒ editing.
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
    :class="
      focused
        ? 'rounded-lg ring-2 ring-primary/60 ring-offset-2 ring-offset-background'
        : undefined
    "
  >
    <Card>
      <div class="flex items-start justify-between gap-2 border-b border-border/60 px-5 py-4">
        <div class="min-w-0">
          <div class="flex items-center gap-1 font-mono text-[13px] font-semibold">
            <span class="truncate">{{ worker.worker_id }}</span>
            <CopyButton :value="worker.worker_id" title="复制节点 ID" />
          </div>
          <div class="mt-0.5 truncate font-mono text-2xs text-muted-foreground" :title="worker.public_url ?? ''">
            {{ worker.public_url ?? "—" }}
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1.5">
          <HintTip
            v-if="worker.paused"
            :text="`worker 已自我暂停 — 当前磁盘 ${diskPct.toFixed(0)}%，等待降到恢复阈值再领新任务`"
          >
            <Badge tone="warn">已暂停</Badge>
          </HintTip>
          <Badge :tone="status.tone" dot>{{ status.label }}</Badge>
        </div>
      </div>

      <div class="space-y-4 px-5 py-4">
        <div class="grid grid-cols-3 gap-3">
          <HintTip text="进程实时 CPU 占用，由 worker 上报">
            <div>
              <div class="stat-label">CPU</div>
              <div class="mt-0.5 text-[15px] font-semibold tabular-nums">
                {{ worker.cpu_percent.toFixed(0) }}%
              </div>
            </div>
          </HintTip>
          <HintTip text="进程实时内存占用，由 worker 上报">
            <div>
              <div class="stat-label">内存</div>
              <div class="mt-0.5 text-[15px] font-semibold tabular-nums">
                {{ worker.mem_percent.toFixed(0) }}%
              </div>
            </div>
          </HintTip>
          <HintTip text="本月累计上传出站流量（receiver 拉取的字节）">
            <div>
              <div class="stat-label">月出站</div>
              <div class="mt-0.5 text-[15px] font-semibold tabular-nums">
                {{ fmtGB(worker.monthly_egress_gb) }}
              </div>
            </div>
          </HintTip>
        </div>

        <div>
          <div class="mb-1.5 flex items-center justify-between text-2xs text-muted-foreground">
            <HintTip text="超过 SATHOP_DISK_PAUSE_PCT（默认 85%）会自动暂停领新任务">
              <span class="font-medium uppercase tracking-widest">磁盘</span>
            </HintTip>
            <span class="tabular-nums">{{ fmtGB(worker.disk_used_gb) }} / {{ fmtGB(worker.disk_total_gb) }}</span>
          </div>
          <ProgressBar :value="worker.disk_used_gb" :max="worker.disk_total_gb" :tone="diskTone" />
        </div>

        <div class="grid grid-cols-4 gap-3 rounded-lg border border-border bg-muted/60 p-3 text-center">
          <HintTip text="已 lease、尚未开始下载的数据粒数量">
            <div>
              <div class="stat-label">排队</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_queued }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在下载源数据中">
            <div>
              <div class="stat-label">下载</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_downloading }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在执行任务包脚本">
            <div>
              <div class="stat-label">处理</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_processing }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在上传产物到本节点存储">
            <div>
              <div class="stat-label">上传</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_uploading }}
              </div>
            </div>
          </HintTip>
        </div>

        <div class="flex items-center justify-between border-t border-border/60 pt-3 text-2xs text-muted-foreground">
          <span class="flex items-center gap-1.5">
            <HintTip text="当前生效的并发上限 / 容器启动时声明的硬容量">
              <span>容量 {{ effective }}/{{ worker.capacity }}</span>
            </HintTip>
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
                class="w-14 text-2xs tabular-nums"
              />
              <button
                @click="submitDraft"
                :disabled="setCap.isPending.value"
                class="rounded-md bg-primary/15 px-1.5 py-0.5 text-mini font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
              >
                保存
              </button>
              <button
                @click="draft = null"
                :disabled="setCap.isPending.value"
                class="text-mini text-muted-foreground hover:text-foreground"
              >
                取消
              </button>
            </template>
            <HintTip
              v-else
              :text="worker.desired_capacity != null
                ? '修改运行时并发上限（不能超过容器声明的容量）'
                : '人工限流：临时压低这台节点的并发上限'"
            >
              <button
                @click="startEdit"
                class="rounded-md border border-border bg-background px-1.5 py-0.5 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
              >
                {{ worker.desired_capacity != null ? "改" : "限流" }}
              </button>
            </HintTip>
          </span>
          <div class="flex items-center gap-3">
            <HintTip text="跳转到事件日志，已按本节点过滤">
              <RouterLink
                :to="`/events?source=${encodeURIComponent(worker.worker_id)}`"
                class="inline-flex h-6 items-center gap-1 rounded-md border border-border bg-background px-2 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-primary"
              >
                <Icon name="events" :size="11" />
                事件
              </RouterLink>
            </HintTip>
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
            <span>心跳 {{ fmtAge(worker.last_seen) }}</span>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
