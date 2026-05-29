<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkerInfo } from "@/api";
import { fmtGB, nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useWorkerLifecycle } from "@/features/nodes/useWorkerLifecycle";
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
import ProgressBar from "@/components/ProgressBar.vue";
import NodeVersionRow from "@/features/nodes/components/NodeVersionRow.vue";
import TextInput from "@/ui/TextInput.vue";
import { Icon } from "@/components/Icon";

const props = defineProps<{ worker: WorkerInfo; focused?: boolean }>();

const isRemoved = computed(() => props.worker.removed_at != null);
const toast = useToast();

// All mutations + confirm dialogs live in the composable now.
const lc = useWorkerLifecycle(() => props.worker);

const inflightTotal = computed(
  () =>
    props.worker.queue_pending_download +
    props.worker.queue_downloading +
    props.worker.queue_pending_processing +
    props.worker.queue_processing +
    props.worker.queue_pending_upload +
    props.worker.queue_uploading,
);

const status = computed(() => nodeStatusBadge(!isRemoved.value, props.worker.last_seen, "已移除"));

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

const effective = computed(() =>
  Math.min(props.worker.capacity, props.worker.desired_capacity ?? props.worker.capacity),
);

function startEdit() {
  draft.value =
    props.worker.desired_capacity != null ? String(props.worker.desired_capacity) : "";
}

function submitDraft() {
  const t = (draft.value ?? "").trim();
  const next = t === "" ? null : Number(t);
  if (next !== null && (!Number.isInteger(next) || next < 1 || next > props.worker.capacity)) {
    toast.error(`并发上限必须是 1–${props.worker.capacity} 的整数`);
    return;
  }
  lc.setCapacity.mutate(next, { onSuccess: () => (draft.value = null) });
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
    <Card :class="isRemoved ? 'opacity-50' : undefined">
      <!-- 身份 -->
      <div class="flex items-start justify-between gap-2 px-5 pb-3 pt-4">
        <div class="min-w-0">
          <div class="flex items-center gap-1 font-mono text-[13px] font-semibold">
            <span class="truncate">{{ worker.worker_id }}</span>
            <CopyButton :value="worker.worker_id" title="复制节点 ID" />
          </div>
          <div
            class="mt-0.5 truncate font-mono text-2xs text-muted-foreground"
            :title="worker.public_url ?? ''"
          >
            {{ worker.public_url ?? "—" }}
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1.5">
          <HintTip
            v-if="worker.operator_paused && !isRemoved"
            text="管理员手动暂停 — 在手任务继续，不接新单。点下方「恢复」按钮解除"
          >
            <Badge tone="warn">手动暂停</Badge>
          </HintTip>
          <HintTip
            v-else-if="worker.paused && !isRemoved"
            :text="`worker 自我暂停 — 当前磁盘 ${diskPct.toFixed(0)}%，等待降到恢复阈值再领新任务`"
          >
            <Badge tone="warn">磁盘暂停</Badge>
          </HintTip>
          <Badge :tone="status.tone" dot>{{ status.label }}</Badge>
        </div>
      </div>

      <!-- 版本检查 + 更新：合二为一的锚点 -->
      <div class="border-b border-border/60 px-5 pb-3">
        <NodeVersionRow
          :version="worker.version"
          :pending="lc.pending.value"
          :actionable="!isRemoved"
          update-title="排空在手任务后拉取最新代码并重启该 worker"
          @update="lc.confirmUpdate"
        />
      </div>

      <div class="space-y-4 px-5 py-4">
        <!-- 健康 -->
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
              <span class="font-medium tracking-label">磁盘</span>
            </HintTip>
            <span class="tabular-nums">{{ fmtGB(worker.disk_used_gb) }} / {{ fmtGB(worker.disk_total_gb) }}</span>
          </div>
          <ProgressBar :value="worker.disk_used_gb" :max="worker.disk_total_gb" :tone="diskTone" />
        </div>

        <div class="grid grid-cols-3 gap-2 rounded-lg border border-border bg-muted/60 p-3 text-center lg:grid-cols-6">
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

        <!-- 约束 + 动作 -->
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
                :disabled="lc.setCapacity.isPending.value"
                placeholder="env"
                class="w-14 text-2xs tabular-nums"
              />
              <Button
                type="button"
                size="xs"
                :disabled="lc.setCapacity.isPending.value"
                @click="submitDraft"
              >
                保存
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                :disabled="lc.setCapacity.isPending.value"
                class="text-muted-foreground hover:text-foreground"
                @click="draft = null"
              >
                取消
              </Button>
            </template>
            <HintTip
              v-else-if="!isRemoved"
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
          <div class="flex flex-wrap items-center justify-end gap-1.5">
            <Button as-child variant="outline" size="xs" class="text-muted-foreground hover:text-primary">
              <RouterLink
                :to="`/events?source=${encodeURIComponent(worker.worker_id)}`"
                title="跳转到事件日志，已按本节点过滤"
              >
                <Icon name="events" :size="11" />
                事件
              </RouterLink>
            </Button>
            <template v-if="!isRemoved">
              <Button
                type="button"
                :variant="worker.operator_paused ? 'default' : 'outline'"
                size="xs"
                :disabled="lc.pause.isPending.value"
                :title="worker.operator_paused
                  ? '恢复领取新任务'
                  : '暂停领取新任务（在手的继续跑完）'"
                @click="lc.togglePause(worker.operator_paused)"
              >
                {{ lc.pause.isPending.value ? "…" : worker.operator_paused ? "恢复" : "暂停" }}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    title="更多运维操作"
                    aria-label="更多运维操作"
                  >
                    <Icon name="more" :size="14" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" class="min-w-48">
                  <DropdownMenuLabel class="text-mini font-medium tracking-label text-muted-foreground">
                    运维
                  </DropdownMenuLabel>
                  <DropdownMenuItem :disabled="lc.gc.isPending.value" @select="lc.confirmGc">
                    立即清理缓存
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    :disabled="lc.revoke.isPending.value || inflightTotal === 0"
                    :title="inflightTotal === 0
                      ? '当前无在手 lease'
                      : `立即释放在手的 ${inflightTotal} 条 lease（丢弃中间产物）`"
                    class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
                    @select="lc.confirmRevoke(inflightTotal)"
                  >
                    释放在手 lease {{ inflightTotal > 0 ? `(${inflightTotal})` : '' }}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel class="text-mini font-medium tracking-label text-muted-foreground">
                    生命周期
                  </DropdownMenuLabel>
                  <!-- Always-available fallback; the prominent inline 更新 button
                       (NodeVersionRow) only appears when a newer version exists. -->
                  <DropdownMenuItem :disabled="lc.pending.value" @select="lc.confirmUpdate">
                    更新…
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    :disabled="lc.pending.value"
                    class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
                    @select="lc.confirmRemove"
                  >
                    移除…
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </template>
            <span class="whitespace-nowrap">心跳 {{ fmtAge(worker.last_seen) }}</span>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
