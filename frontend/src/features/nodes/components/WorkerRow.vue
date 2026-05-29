<script setup lang="ts">
import { computed } from "vue";
import type { WorkerInfo } from "@/api";
import { nodeStatusBadge } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { useWorkerLifecycle } from "@/features/nodes/useWorkerLifecycle";
import { TableCell, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import HintTip from "@/components/HintTip.vue";
import QueueBar from "@/components/QueueBar.vue";
import { Icon } from "@/components/Icon";

const props = defineProps<{
  worker: WorkerInfo;
  selected: boolean;
  tab: "active" | "history";
}>();

const emit = defineEmits<{
  (e: "toggle", shiftKey: boolean): void;
  (e: "open"): void;
}>();

const lc = useWorkerLifecycle(() => props.worker);

const status = computed(() =>
  nodeStatusBadge(props.tab === "active", props.worker.last_seen, "已移除"),
);

const diskPct = computed(() =>
  props.worker.disk_total_gb > 0
    ? (props.worker.disk_used_gb / props.worker.disk_total_gb) * 100
    : 0,
);
const diskTone = computed(() => {
  const p = diskPct.value;
  if (p > 80) return "bg-danger";
  if (p > 60) return "bg-warning";
  return "bg-primary";
});

const inflightTotal = computed(
  () =>
    props.worker.queue_pending_download +
    props.worker.queue_downloading +
    props.worker.queue_pending_processing +
    props.worker.queue_processing +
    props.worker.queue_pending_upload +
    props.worker.queue_uploading,
);

// dl/pr 显示：实测生效值，括号内为覆盖值（若有）。
function concDisplay(live: number | null, override: number | null): string {
  return `${live ?? "-"}${override != null ? `（${override}）` : ""}`;
}

// Checkbox 的 shift-range：reka-ui Checkbox 的 @update:model-value 不带原始事件，
// 用 mousedown 捕获 shiftKey，再在 toggle 时回传。
let shiftPressed = false;
function onCheckboxMousedown(e: MouseEvent) {
  shiftPressed = e.shiftKey;
}

// v-memo 签名（design item 10）。
const memo = computed(() => [
  props.worker.last_seen,
  props.worker.cpu_percent,
  props.worker.mem_percent,
  props.worker.disk_used_gb,
  props.worker.disk_total_gb,
  props.worker.operator_paused,
  props.worker.paused,
  props.worker.live_download_concurrency,
  props.worker.live_process_concurrency,
  props.worker.download_concurrency,
  props.worker.process_concurrency,
  inflightTotal.value,
  props.worker.version,
  props.selected,
]);
</script>

<template>
  <!-- active -->
  <TableRow
    v-if="tab === 'active'"
    v-memo="memo"
    :data-state="selected ? 'selected' : undefined"
    class="cursor-pointer"
    @click="emit('open')"
  >
    <TableCell class="w-8" @click.stop @mousedown="onCheckboxMousedown">
      <Checkbox :model-value="selected" @update:model-value="emit('toggle', shiftPressed)" />
    </TableCell>
    <TableCell class="w-6">
      <Badge :tone="status.tone" dot :title="status.label" class="size-1.5 border-0 bg-transparent p-0" />
    </TableCell>
    <TableCell class="font-mono text-xs">
      <span class="flex items-center gap-1.5">
        <span class="truncate">{{ worker.worker_id }}</span>
        <HintTip
          v-if="worker.operator_paused"
          text="管理员手动暂停 — 在手任务继续，不接新单"
        >
          <Badge tone="warn" class="px-1.5 py-0 text-mini">暂停</Badge>
        </HintTip>
        <HintTip
          v-else-if="worker.paused"
          text="worker 自我暂停 — 磁盘超阈值，等待降回恢复阈值再领新任务"
        >
          <Badge tone="warn" class="px-1.5 py-0 text-mini">磁盘暂停</Badge>
        </HintTip>
      </span>
    </TableCell>
    <TableCell class="tabular-nums">{{ worker.cpu_percent.toFixed(0) }}%</TableCell>
    <TableCell class="tabular-nums">{{ worker.mem_percent.toFixed(0) }}%</TableCell>
    <TableCell>
      <HintTip :text="`磁盘 ${diskPct.toFixed(0)}%`">
        <span class="flex items-center gap-1.5">
          <span class="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
            <span :class="['block h-full', diskTone]" :style="{ width: `${Math.min(100, diskPct)}%` }" />
          </span>
          <span class="tabular-nums text-2xs text-muted-foreground">{{ diskPct.toFixed(0) }}%</span>
        </span>
      </HintTip>
    </TableCell>
    <TableCell class="text-2xs">
      <HintTip text="下载并发 / 处理并发：实测生效值（括号内为运维下发的覆盖值）">
        <span class="tabular-nums">
          {{ concDisplay(worker.live_download_concurrency, worker.download_concurrency) }}
          /
          {{ concDisplay(worker.live_process_concurrency, worker.process_concurrency) }}
        </span>
      </HintTip>
    </TableCell>
    <TableCell><QueueBar :worker="worker" /></TableCell>
    <TableCell class="whitespace-nowrap text-2xs text-muted-foreground">{{ fmtAge(worker.last_seen) }}</TableCell>
    <TableCell class="w-8 text-right" @click.stop>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button type="button" variant="ghost" size="icon-sm" title="更多运维操作" aria-label="更多运维操作">
            <Icon name="more" :size="14" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="min-w-44">
          <DropdownMenuItem
            :disabled="lc.pause.isPending.value"
            @select="lc.togglePause(worker.operator_paused)"
          >
            {{ worker.operator_paused ? "恢复" : "暂停" }}
          </DropdownMenuItem>
          <DropdownMenuItem :disabled="lc.gc.isPending.value" @select="lc.confirmGc">
            立即清理缓存
          </DropdownMenuItem>
          <DropdownMenuItem
            :disabled="lc.revoke.isPending.value || inflightTotal === 0"
            :title="inflightTotal === 0 ? '当前无在手 lease' : `立即释放在手的 ${inflightTotal} 条 lease`"
            class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
            @select="lc.confirmRevoke(inflightTotal)"
          >
            释放在手 lease {{ inflightTotal > 0 ? `(${inflightTotal})` : "" }}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
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
          <DropdownMenuSeparator />
          <DropdownMenuItem as-child>
            <RouterLink :to="`/events?source=${encodeURIComponent(worker.worker_id)}`">
              <Icon name="events" :size="12" />
              事件
            </RouterLink>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </TableCell>
  </TableRow>

  <!-- history -->
  <TableRow
    v-else
    v-memo="memo"
    :data-state="selected ? 'selected' : undefined"
    class="cursor-pointer opacity-70"
    @click="emit('open')"
  >
    <TableCell class="w-8" @click.stop @mousedown="onCheckboxMousedown">
      <Checkbox :model-value="selected" @update:model-value="emit('toggle', shiftPressed)" />
    </TableCell>
    <TableCell class="w-16">
      <Badge tone="error" class="px-1.5 py-0 text-mini">已移除</Badge>
    </TableCell>
    <TableCell class="font-mono text-xs">
      <span class="truncate">{{ worker.worker_id }}</span>
    </TableCell>
    <TableCell class="whitespace-nowrap text-2xs text-muted-foreground">{{ fmtAge(worker.last_seen) }}</TableCell>
    <TableCell class="w-8 text-right" @click.stop>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button type="button" variant="ghost" size="icon-sm" title="更多操作" aria-label="更多操作">
            <Icon name="more" :size="14" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="min-w-40">
          <DropdownMenuLabel class="text-mini font-medium tracking-label text-muted-foreground">
            生命周期
          </DropdownMenuLabel>
          <DropdownMenuItem
            :disabled="lc.purge.isPending.value"
            class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
            @select="lc.confirmPurge"
          >
            <Icon name="trash" :size="12" />
            彻底删除
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </TableCell>
  </TableRow>
</template>
