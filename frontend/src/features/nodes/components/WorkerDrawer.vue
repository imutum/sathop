<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkerInfo } from "@/api";
import { fmtGB, nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useWorkerLifecycle } from "@/features/nodes/useWorkerLifecycle";
import { useToast } from "@/composables/useToast";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import CopyButton from "@/components/CopyButton.vue";
import HintTip from "@/components/HintTip.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import NodeVersionRow from "@/features/nodes/components/NodeVersionRow.vue";
import TextInput from "@/ui/TextInput.vue";
import { Icon } from "@/components/Icon";

// 单节点全量详情抽屉。worker 由父级从 live query 按 id 解析后传入，
// 因此 SSE refetch 时抽屉随之刷新 —— 始终读响应式 prop，不缓存快照。
const props = defineProps<{ open: boolean; worker: WorkerInfo | null }>();
const emit = defineEmits<{ (e: "update:open", v: boolean): void }>();

const toast = useToast();
// 仅在 worker 存在时取 id；关闭态下 worker=null，组件主体被 v-if 跳过。
const lc = useWorkerLifecycle(() => props.worker ?? { worker_id: "" });

const isRemoved = computed(() => props.worker?.removed_at != null);
const status = computed(() =>
  props.worker ? nodeStatusBadge(!isRemoved.value, props.worker.last_seen, "已移除") : null,
);

const diskPct = computed(() => {
  const w = props.worker;
  return w && w.disk_total_gb > 0 ? (w.disk_used_gb / w.disk_total_gb) * 100 : 0;
});
const diskTone = computed<"bad" | "warn" | "accent">(() => {
  const p = diskPct.value;
  if (p > 80) return "bad";
  if (p > 60) return "warn";
  return "accent";
});

const inflightTotal = computed(() => {
  const w = props.worker;
  if (!w) return 0;
  return (
    w.queue_pending_download +
    w.queue_downloading +
    w.queue_pending_processing +
    w.queue_processing +
    w.queue_pending_upload +
    w.queue_uploading
  );
});

// 6 阶段栅格（顺序/文案/提示与原 WorkerCard 一致）。
const STAGES = [
  { key: "queue_pending_download", label: "待下载", tip: "已 lease、等下载槽位（download_sem 满）" },
  { key: "queue_downloading", label: "下载中", tip: "正在拉源数据" },
  { key: "queue_pending_processing", label: "待处理", tip: "已下载、等 CPU 槽位（process_sem 满）" },
  { key: "queue_processing", label: "处理中", tip: "正在执行任务包脚本（CPU 在跑）" },
  { key: "queue_pending_upload", label: "待上传", tip: "处理完、等上传槽位（upload_sem 满）— 防 MinIO/WAN 打满网卡" },
  { key: "queue_uploading", label: "上传中", tip: "正在把产物落到本节点存储" },
] as const;

// 两个并发编辑器（下载 / 处理）。editing===null ⇒ 显示态；否则编辑该维度。
type Dim = "download" | "process";
const editing = ref<Dim | null>(null);
const draft = ref("");
const draftInput = ref<InstanceType<typeof TextInput> | null>(null);
watch(editing, (v) => {
  if (v !== null) void nextTick(() => draftInput.value?.focus());
});
// 抽屉切换节点 / 关闭时退出编辑态。
watch(
  () => [props.worker?.worker_id, props.open],
  () => (editing.value = null),
);

const dl = computed(() => ({
  live: props.worker?.live_download_concurrency ?? null,
  override: props.worker?.download_concurrency ?? null,
}));
const pr = computed(() => ({
  live: props.worker?.live_process_concurrency ?? null,
  override: props.worker?.process_concurrency ?? null,
}));

function startEdit(dim: Dim) {
  const ov = dim === "download" ? dl.value.override : pr.value.override;
  draft.value = ov != null ? String(ov) : "";
  editing.value = dim;
}

function submitDraft() {
  const dim = editing.value;
  if (dim === null) return;
  // type=number 的 v-model 会回吐 number，必须 String(...) 再 trim，否则 .trim() 抛 TypeError。
  const t = String(draft.value ?? "").trim();
  const next = t === "" ? null : Number(t);
  if (next !== null && (!Number.isInteger(next) || next < 1)) {
    toast.error("并发必须是 ≥ 1 的整数，留空表示用节点默认值");
    return;
  }
  const body = {
    download_concurrency: dim === "download" ? next : dl.value.override,
    process_concurrency: dim === "process" ? next : pr.value.override,
  };
  lc.setConcurrency.mutate(body, { onSuccess: () => (editing.value = null) });
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter") submitDraft();
  if (e.key === "Escape") editing.value = null;
}
</script>

<template>
  <Sheet :open="open" @update:open="emit('update:open', $event)">
    <SheetContent side="right" class="w-full gap-0 overflow-y-auto p-0 sm:max-w-md">
      <template v-if="worker">
        <!-- 身份 -->
        <div class="flex items-start justify-between gap-2 border-b border-border/60 px-5 pb-4 pt-5 pr-12">
          <div class="min-w-0">
            <div class="flex items-center gap-1 font-mono text-sm font-semibold">
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
            <Badge v-if="status" :tone="status.tone" dot>{{ status.label }}</Badge>
          </div>
        </div>

        <!-- 版本 + 更新 -->
        <div class="border-b border-border/60 px-5 py-3">
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

          <!-- 磁盘 -->
          <div>
            <div class="mb-1.5 flex items-center justify-between text-2xs text-muted-foreground">
              <HintTip text="超过 SATHOP_DISK_PAUSE_PCT（默认 85%）会自动暂停领新任务">
                <span class="font-medium tracking-label">磁盘</span>
              </HintTip>
              <span class="tabular-nums">{{ fmtGB(worker.disk_used_gb) }} / {{ fmtGB(worker.disk_total_gb) }}</span>
            </div>
            <ProgressBar :value="worker.disk_used_gb" :max="worker.disk_total_gb" :tone="diskTone" />
          </div>

          <!-- 队列 6 阶段栅格 -->
          <div class="grid grid-cols-3 gap-2 rounded-lg border border-border bg-muted/60 p-3 text-center lg:grid-cols-6">
            <HintTip v-for="s in STAGES" :key="s.key" :text="s.tip">
              <div>
                <div class="stat-label">{{ s.label }}</div>
                <div class="mt-0.5 text-base font-semibold tabular-nums text-foreground">
                  {{ worker[s.key] }}
                </div>
              </div>
            </HintTip>
          </div>

          <!-- 并发编辑器 -->
          <div class="space-y-2 border-t border-border/60 pt-3 text-2xs text-muted-foreground">
            <!-- 下载并发 -->
            <div class="flex items-center gap-1.5">
              <HintTip text="下载并发：当前 worker 实测生效值 / 运维下发的覆盖值（留空=节点默认）。调大瞬时生效；调小会触发一次短暂排空后重建">
                <span>
                  下载并发
                  <span class="tabular-nums text-foreground">{{ dl.live ?? "-" }}</span>
                  <span v-if="dl.override != null" class="text-muted-foreground">（覆盖 {{ dl.override }}）</span>
                </span>
              </HintTip>
              <template v-if="editing === 'download'">
                <TextInput
                  ref="draftInput"
                  type="number"
                  :min="1"
                  :model-value="draft"
                  placeholder="默认"
                  class="w-14 text-2xs tabular-nums"
                  :disabled="lc.setConcurrency.isPending.value"
                  @update:model-value="draft = $event"
                  @keydown="onKey"
                />
                <Button type="button" size="xs" :disabled="lc.setConcurrency.isPending.value" @click="submitDraft">保存</Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  class="text-muted-foreground hover:text-foreground"
                  :disabled="lc.setConcurrency.isPending.value"
                  @click="editing = null"
                >取消</Button>
              </template>
              <Button
                v-else-if="!isRemoved"
                type="button"
                variant="outline"
                size="xs"
                class="ml-auto text-muted-foreground hover:text-foreground"
                @click="startEdit('download')"
              >改</Button>
            </div>
            <!-- 处理并发 -->
            <div class="flex items-center gap-1.5">
              <HintTip text="处理并发：当前 worker 实测生效值 / 运维下发的覆盖值（留空=节点默认）。调大瞬时生效；调小会触发一次短暂排空后重建">
                <span>
                  处理并发
                  <span class="tabular-nums text-foreground">{{ pr.live ?? "-" }}</span>
                  <span v-if="pr.override != null" class="text-muted-foreground">（覆盖 {{ pr.override }}）</span>
                </span>
              </HintTip>
              <template v-if="editing === 'process'">
                <TextInput
                  ref="draftInput"
                  type="number"
                  :min="1"
                  :model-value="draft"
                  placeholder="默认"
                  class="w-14 text-2xs tabular-nums"
                  :disabled="lc.setConcurrency.isPending.value"
                  @update:model-value="draft = $event"
                  @keydown="onKey"
                />
                <Button type="button" size="xs" :disabled="lc.setConcurrency.isPending.value" @click="submitDraft">保存</Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  class="text-muted-foreground hover:text-foreground"
                  :disabled="lc.setConcurrency.isPending.value"
                  @click="editing = null"
                >取消</Button>
              </template>
              <Button
                v-else-if="!isRemoved"
                type="button"
                variant="outline"
                size="xs"
                class="ml-auto text-muted-foreground hover:text-foreground"
                @click="startEdit('process')"
              >改</Button>
            </div>
          </div>

          <!-- 动作 -->
          <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3 text-2xs text-muted-foreground">
            <span class="whitespace-nowrap">心跳 {{ fmtAge(worker.last_seen) }}</span>
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
                  :title="worker.operator_paused ? '恢复领取新任务' : '暂停领取新任务（在手的继续跑完）'"
                  @click="lc.togglePause(worker.operator_paused)"
                >
                  {{ lc.pause.isPending.value ? "…" : worker.operator_paused ? "恢复" : "暂停" }}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  class="text-muted-foreground hover:text-foreground"
                  :disabled="lc.gc.isPending.value"
                  title="向该 worker 发送清理信号，下次心跳生效"
                  @click="lc.confirmGc"
                >
                  清缓存
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  class="text-danger hover:bg-danger/10"
                  :disabled="lc.revoke.isPending.value || inflightTotal === 0"
                  :title="inflightTotal === 0 ? '当前无在手 lease' : `立即释放在手的 ${inflightTotal} 条 lease（丢弃中间产物）`"
                  @click="lc.confirmRevoke(inflightTotal)"
                >
                  释放lease {{ inflightTotal > 0 ? `(${inflightTotal})` : "" }}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  class="text-muted-foreground hover:text-foreground"
                  :disabled="lc.pending.value"
                  @click="lc.confirmUpdate"
                >
                  更新…
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  class="text-danger hover:bg-danger/10"
                  :disabled="lc.pending.value"
                  @click="lc.confirmRemove"
                >
                  移除…
                </Button>
              </template>
              <Button
                v-else
                type="button"
                variant="outline"
                size="xs"
                class="text-danger hover:bg-danger/10"
                :disabled="lc.purge.isPending.value"
                title="从注册表中物理删除该节点记录"
                @click="lc.confirmPurge"
              >
                <Icon name="trash" :size="11" />
                彻底删除
              </Button>
            </div>
          </div>
        </div>
      </template>
    </SheetContent>
  </Sheet>
</template>
