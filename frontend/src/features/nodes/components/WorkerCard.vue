<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { API, type WorkerInfo } from "@/api";
import { fmtGB, nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import CopyButton from "@/components/CopyButton.vue";
import HintTip from "@/components/HintTip.vue";
import { useNodeLifecycle } from "@/features/nodes/useNodeLifecycle";
import ProgressBar from "@/components/ProgressBar.vue";
import TextInput from "@/ui/TextInput.vue";
import { Icon } from "@/components/Icon";

const props = defineProps<{ worker: WorkerInfo; focused?: boolean }>();

const qc = useQueryClient();
const toast = useToast();

const lifecycle = useNodeLifecycle<WorkerInfo>({
  id: props.worker.worker_id,
  queryKey: "workers",
  getId: (worker) => worker.worker_id,
  setEnabled: (next) => API.setWorkerEnabled(props.worker.worker_id, next),
  forget: () => API.forgetWorker(props.worker.worker_id),
  restart: () => API.restartWorker(props.worker.worker_id),
  enabledMessage: "已启用",
  disabledMessage: "已禁用，已在手任务排空后停止接新单",
  deletedMessage: `已删除节点 ${props.worker.worker_id}`,
  restartMessage: "已发送重启信号，下次心跳生效",
  forgetConfirm: {
    title: `永久移除节点 ${props.worker.worker_id}？`,
    description:
      "将从注册表中删除这条节点记录。\n" +
      "如果 worker 容器仍在运行，下次心跳会自动重新注册（misclick 重启容器即恢复）。\n" +
      "想让它彻底不再回来：先停掉容器再点移除。",
    confirmText: "永久移除",
    tone: "danger",
  },
  restartConfirm: {
    title: `重启节点 ${props.worker.worker_id}？`,
    description:
      "向该 worker 发送重启信号 — 它会在下一次心跳收到后立即退出，由容器 restart 策略拉起。\n" +
      "在手任务的 lease 在 30 分钟后被回收并重新分配，重启过程中不接新单。",
    confirmText: "重启",
  },
});

const pause = useMutation({
  mutationFn: (next: boolean) => API.setWorkerPaused(props.worker.worker_id, next),
  onSuccess: (_r, next) => {
    qc.invalidateQueries({ queryKey: ["workers"] });
    toast.success(next ? "已暂停领新任务（在手任务继续）" : "已恢复");
  },
  onError: (e: Error) => toast.error(`暂停切换失败：${e.message}`),
});

const revoke = useMutation({
  mutationFn: () => API.revokeWorkerLeases(props.worker.worker_id),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: ["workers"] });
    qc.invalidateQueries({ queryKey: ["batches"] });
    toast.success(`已释放 ${r.revoked} 条 lease，等待其他 worker 抢占`);
  },
  onError: (e: Error) => toast.error(`释放失败：${e.message}`),
});

const gc = useMutation({
  mutationFn: () => API.workerGc(props.worker.worker_id),
  onSuccess: () => {
    toast.success("已发送清理信号，下次心跳生效");
  },
  onError: (e: Error) => toast.error(`触发失败：${e.message}`),
});

function onTogglePause(): void {
  pause.mutate(!props.worker.operator_paused);
}

async function onRevokeAll(): Promise<void> {
  const ok = await requestConfirm({
    title: `立即释放此节点的所有 lease？`,
    description:
      "把这台节点持有的全部在手 lease 重置回 待分配，等其他 worker 抢占。\n" +
      "已下载/已处理的中间产物会被丢弃；retry_count 会 +1，仍受 max_retries 限制。\n" +
      "用于 worker 卡住但还在心跳的场景（不卡的话就用禁用 + 等 lease 到期更稳）。",
    confirmText: "立即释放",
    tone: "danger",
  });
  if (ok) revoke.mutate();
}

async function onGc(): Promise<void> {
  const ok = await requestConfirm({
    title: `让节点立即清理缓存？`,
    description:
      "向该 worker 发送清理信号 — 下一次心跳生效，立即跑一次 venv LRU + shared 孤儿清理。\n" +
      "正在使用的 bundle/venv 不会被清掉（受 in_use 锁保护）。",
    confirmText: "清理缓存",
  });
  if (ok) gc.mutate();
}

const inflightTotal = computed(
  () =>
    props.worker.queue_pending_download +
    props.worker.queue_downloading +
    props.worker.queue_pending_processing +
    props.worker.queue_processing +
    props.worker.queue_pending_upload +
    props.worker.queue_uploading,
);

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
            <HintTip
              v-if="worker.version"
              :text="`worker 上报的运行版本（来自 sathop 包元数据）— 排查问题时确认是不是最新镜像`"
            >
              <Badge tone="info" class="ml-1 font-mono">v{{ worker.version }}</Badge>
            </HintTip>
          </div>
          <div class="mt-0.5 truncate font-mono text-2xs text-muted-foreground" :title="worker.public_url ?? ''">
            {{ worker.public_url ?? "—" }}
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1.5">
          <HintTip
            v-if="worker.operator_paused"
            text="管理员手动暂停 — 在手任务继续，不接新单。点下方「恢复」按钮解除"
          >
            <Badge tone="warn">手动暂停</Badge>
          </HintTip>
          <HintTip
            v-else-if="worker.paused"
            :text="`worker 自我暂停 — 当前磁盘 ${diskPct.toFixed(0)}%，等待降到恢复阈值再领新任务`"
          >
            <Badge tone="warn">磁盘暂停</Badge>
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

        <div class="grid grid-cols-3 gap-2 rounded-lg border border-border bg-muted/60 p-3 text-center sm:grid-cols-6">
          <HintTip text="已 lease、等下载槽位（download_sem 满）">
            <div>
              <div class="stat-label">待下载</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_pending_download }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在拉源数据">
            <div>
              <div class="stat-label">下载中</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_downloading }}
              </div>
            </div>
          </HintTip>
          <HintTip text="已下载、等 CPU 槽位（process_sem 满）">
            <div>
              <div class="stat-label">待处理</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_pending_processing }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在执行任务包脚本（CPU 在跑）">
            <div>
              <div class="stat-label">处理中</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_processing }}
              </div>
            </div>
          </HintTip>
          <HintTip text="处理完、等上传槽位（upload_sem 满）— 防 MinIO/WAN 打满网卡">
            <div>
              <div class="stat-label">待上传</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_pending_upload }}
              </div>
            </div>
          </HintTip>
          <HintTip text="正在把产物落到本节点存储">
            <div>
              <div class="stat-label">上传中</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                {{ worker.queue_uploading }}
              </div>
            </div>
          </HintTip>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3 text-2xs text-muted-foreground">
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
              <Button
                type="button"
                size="xs"
                :disabled="setCap.isPending.value"
                @click="submitDraft"
              >
                保存
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                :disabled="setCap.isPending.value"
                class="text-muted-foreground hover:text-foreground"
                @click="draft = null"
              >
                取消
              </Button>
            </template>
            <HintTip
              v-else
              :text="worker.desired_capacity != null
                ? '修改运行时并发上限（不能超过容器声明的容量）'
                : '人工限流：临时压低这台节点的并发上限'"
            >
              <Button
                type="button"
                variant="outline"
                size="xs"
                class="text-muted-foreground hover:text-foreground"
                @click="startEdit"
              >
                {{ worker.desired_capacity != null ? "改" : "限流" }}
              </Button>
            </HintTip>
          </span>
          <div class="flex items-center gap-2">
            <HintTip text="跳转到事件日志，已按本节点过滤">
              <Button as-child variant="outline" size="xs" class="text-muted-foreground hover:text-primary">
                <RouterLink :to="`/events?source=${encodeURIComponent(worker.worker_id)}`">
                  <Icon name="events" :size="11" />
                  事件
                </RouterLink>
              </Button>
            </HintTip>
            <Button
              type="button"
              :variant="worker.operator_paused ? 'default' : 'outline'"
              size="xs"
              :disabled="pause.isPending.value"
              :title="worker.operator_paused
                ? '恢复领取新任务'
                : '暂停领取新任务（在手的继续跑完）'"
              @click="onTogglePause"
            >
              {{ pause.isPending.value ? "…" : worker.operator_paused ? "恢复" : "暂停" }}
            </Button>
            <DropdownMenu>
              <HintTip text="更多运维操作">
                <DropdownMenuTrigger as-child>
                  <Button type="button" variant="outline" size="icon-sm" aria-label="更多运维">
                    <Icon name="more" :size="14" />
                  </Button>
                </DropdownMenuTrigger>
              </HintTip>
              <DropdownMenuContent align="end" class="min-w-48">
                <DropdownMenuLabel class="text-mini font-medium uppercase tracking-label text-muted-foreground">
                  运维
                </DropdownMenuLabel>
                <DropdownMenuItem
                  :disabled="gc.isPending.value"
                  @select="onGc"
                >
                  立即清理缓存
                </DropdownMenuItem>
                <DropdownMenuItem
                  :disabled="revoke.isPending.value || inflightTotal === 0"
                  :title="inflightTotal === 0
                    ? '当前无在手 lease'
                    : `立即释放在手的 ${inflightTotal} 条 lease（丢弃中间产物）`"
                  class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
                  @select="onRevokeAll"
                >
                  释放在手 lease {{ inflightTotal > 0 ? `(${inflightTotal})` : '' }}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuLabel class="text-mini font-medium uppercase tracking-label text-muted-foreground">
                  生命周期
                </DropdownMenuLabel>
                <DropdownMenuItem
                  :disabled="lifecycle.pending.value"
                  @select="lifecycle.confirmRestart"
                >
                  重启…
                </DropdownMenuItem>
                <DropdownMenuItem
                  :disabled="lifecycle.pending.value || worker.enabled"
                  :title="worker.enabled ? '请先禁用此节点，再点击此按钮永久移除' : '永久从注册表中删除（misclick → 重启 worker 自动重建）'"
                  class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
                  @select="lifecycle.confirmForget"
                >
                  永久移除…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              type="button"
              :variant="worker.enabled ? 'outline' : 'default'"
              size="xs"
              :disabled="lifecycle.pending.value"
              :title="worker.enabled ? '禁用此节点（在手任务继续，可点启用恢复）' : '重新启用此节点'"
              @click="lifecycle.setEnabled(!worker.enabled)"
            >
              {{ lifecycle.pending.value ? "…" : worker.enabled ? "禁用" : "启用" }}
            </Button>
            <span>心跳 {{ fmtAge(worker.last_seen) }}</span>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
