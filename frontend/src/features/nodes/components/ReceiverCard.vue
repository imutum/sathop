<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { API, type ReceiverInfo } from "@/api";
import { fmtGB, fmtRate, nodeStatusBadge } from "@/lib/format";
import { PLATFORM_ZH, fmtAge } from "@/i18n";
import { useToast } from "@/composables/useToast";
import { Badge } from "@/components/ui/badge";
import CopyButton from "@/components/CopyButton.vue";
import NodeLifecycleActions from "@/features/nodes/components/NodeLifecycleActions.vue";
import Crosshair from "@/components/chrome/Crosshair.vue";
import { Icon } from "@/components/Icon";
import { computed } from "vue";

const props = defineProps<{ receiver: ReceiverInfo }>();
const qc = useQueryClient();
const toast = useToast();

const enable = useMutation({
  mutationFn: (next: boolean) => API.setReceiverEnabled(props.receiver.receiver_id, next),
  onSuccess: (_r, next) => {
    qc.invalidateQueries({ queryKey: ["receivers"] });
    toast.success(next ? "已启用" : "已禁用，下次 pull 会被拒绝");
  },
  onError: (e: Error) => toast.error(`失败：${e.message}`),
});

const forget = useMutation({
  mutationFn: () => API.forgetReceiver(props.receiver.receiver_id),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["receivers"] });
    toast.success(`已删除接收端 ${props.receiver.receiver_id}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

const status = computed(() => nodeStatusBadge(props.receiver.enabled, props.receiver.last_seen));
const pending = computed(() => enable.isPending.value || forget.isPending.value);
</script>

<template>
  <div class="relative overflow-hidden rounded-md border border-border bg-card text-card-foreground shadow-card">
    <Crosshair tone="muted" :inset="5" :size="9" />

    <div class="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
      <div class="min-w-0 space-y-1.5">
        <div class="flex items-center gap-2 text-3xs uppercase tracking-section text-muted-foreground readout">
          <span class="text-primary">RCV</span>
          <span aria-hidden class="h-2 w-px bg-border" />
          <span>ENDPOINT</span>
        </div>
        <div class="flex items-center gap-1 readout text-[13px] font-semibold">
          <span class="truncate">{{ receiver.receiver_id }}</span>
          <CopyButton :value="receiver.receiver_id" title="复制接收端 ID" />
        </div>
        <div class="readout text-3xs text-muted-foreground">
          PLATFORM · {{ PLATFORM_ZH[receiver.platform] ?? receiver.platform }}
        </div>
      </div>
      <Badge :tone="status.tone" dot>{{ status.label }}</Badge>
    </div>

    <div class="grid grid-cols-2 gap-px bg-border">
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">DISK · FREE</div>
        <div class="font-display text-[20px] font-medium leading-none tabular-nums">
          {{ fmtGB(receiver.disk_free_gb) }}
        </div>
      </div>
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">HEARTBEAT</div>
        <div class="readout text-[13px] tabular-nums">↻ {{ fmtAge(receiver.last_seen) }}</div>
      </div>
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout">PULLING</div>
        <div class="font-display text-[20px] font-medium leading-none tabular-nums">
          {{ receiver.queue_pulling }}
        </div>
      </div>
      <div class="space-y-0.5 bg-card px-4 py-3.5">
        <div class="text-3xs uppercase tracking-section text-muted-foreground readout" title="过去约 60 秒的拉取吞吐">
          THROUGHPUT
        </div>
        <div class="readout text-[13px] tabular-nums">{{ fmtRate(receiver.recent_pull_bps) }}</div>
      </div>
    </div>

    <div class="flex items-center justify-end gap-3 border-t border-border px-5 py-2.5">
      <RouterLink
        :to="`/events?source=${encodeURIComponent(receiver.receiver_id)}`"
        class="readout inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-background px-2 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-primary"
        title="查看该接收端的事件流"
      >
        <Icon name="events" :size="11" />
        LOG
      </RouterLink>
      <NodeLifecycleActions
        :enabled="receiver.enabled"
        :pending="pending"
        @set-enabled="enable.mutate"
        @forget="forget.mutate"
        :disable-confirm="`禁用 receiver ${receiver.receiver_id}？\n\n已下载的对象可继续 ack；不会再被分到新对象。`"
        :forget-confirm="`从注册表中移除 ${receiver.receiver_id}？\n\n仅删除元数据；目标已绑定此接收端的批次将无法 pull。`"
        disable-title="禁用此接收端"
        forget-title="永久从注册表中删除（仅在已禁用时允许）"
      />
    </div>
  </div>
</template>
