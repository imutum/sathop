<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { API, type ReceiverInfo } from "@/api";
import { fmtGB, fmtRate, nodeStatusBadge } from "@/lib/format";
import { PLATFORM_ZH, fmtAge } from "@/i18n";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import CopyButton from "@/components/CopyButton.vue";
import HintTip from "@/components/HintTip.vue";
import NodeLifecycleActions from "@/features/nodes/components/NodeLifecycleActions.vue";
import { Icon } from "@/components/Icon";
import { computed } from "vue";

const props = defineProps<{ receiver: ReceiverInfo }>();
const qc = useQueryClient();
const toast = useToast();

const enable = useMutation({
  mutationFn: (next: boolean) => API.setReceiverEnabled(props.receiver.receiver_id, next),
  onSuccess: (_r, next) => {
    // Optimistic local cache update so the badge + button labels flip
    // immediately, independent of SSE timing or refetch latency.
    qc.setQueryData<ReceiverInfo[]>(["receivers"], (prev) =>
      prev?.map((r) =>
        r.receiver_id === props.receiver.receiver_id ? { ...r, enabled: next } : r,
      ) ?? prev,
    );
    qc.invalidateQueries({ queryKey: ["receivers"] });
    toast.success(next ? "已启用" : "已禁用，下次 pull 会被拒绝");
  },
  onError: (e: Error) => toast.error(`失败：${e.message}`),
});

const forget = useMutation({
  mutationFn: () => API.forgetReceiver(props.receiver.receiver_id),
  onSuccess: () => {
    qc.setQueryData<ReceiverInfo[]>(["receivers"], (prev) =>
      prev?.filter((r) => r.receiver_id !== props.receiver.receiver_id) ?? prev,
    );
    qc.invalidateQueries({ queryKey: ["receivers"] });
    toast.success(`已删除接收端 ${props.receiver.receiver_id}`);
  },
  onError: (e: Error) => toast.error(`删除失败：${e.message}`),
});

function onSetEnabled(next: boolean): void {
  enable.mutate(next);
}
async function onForget(): Promise<void> {
  const ok = await requestConfirm({
    title: `永久移除接收端 ${props.receiver.receiver_id}？`,
    description:
      "将从注册表中删除这条接收端记录。\n" +
      "如果接收端容器仍在运行，下次心跳会自动重新注册（misclick 重启容器即恢复）。\n" +
      "想让它彻底不再回来：先停掉容器再点移除。",
    confirmText: "永久移除",
    tone: "danger",
  });
  if (ok) forget.mutate();
}

const status = computed(() => nodeStatusBadge(props.receiver.enabled, props.receiver.last_seen));
const pending = computed(() => enable.isPending.value || forget.isPending.value);
</script>

<template>
  <Card>
    <div class="flex items-start justify-between gap-2 border-b border-border/60 px-5 py-4">
      <div class="min-w-0">
        <div class="flex items-center gap-1 font-mono text-[13px] font-semibold">
          <span class="truncate">{{ receiver.receiver_id }}</span>
          <CopyButton :value="receiver.receiver_id" title="复制接收端 ID" />
        </div>
        <div class="mt-0.5 text-2xs text-muted-foreground">
          平台 · {{ PLATFORM_ZH[receiver.platform] ?? receiver.platform }}
        </div>
      </div>
      <Badge :tone="status.tone" dot>{{ status.label }}</Badge>
    </div>

    <div class="grid grid-cols-2 gap-4 px-5 py-4">
      <HintTip text="该接收端可用磁盘空间，由它定期上报">
        <div>
          <div class="stat-label">剩余磁盘</div>
          <div class="mt-1 text-base font-semibold tabular-nums">
            {{ fmtGB(receiver.disk_free_gb) }}
          </div>
        </div>
      </HintTip>
      <HintTip text="距离上一次心跳的时长，超过 2 分钟视为离线">
        <div>
          <div class="stat-label">心跳</div>
          <div class="mt-1 text-[12.5px]">{{ fmtAge(receiver.last_seen) }}</div>
        </div>
      </HintTip>
      <HintTip text="正在并发拉取的产物数量">
        <div>
          <div class="stat-label">拉取中</div>
          <div class="mt-1 text-base font-semibold tabular-nums">
            {{ receiver.queue_pulling }}
          </div>
        </div>
      </HintTip>
      <HintTip text="过去约 60 秒的拉取吞吐">
        <div>
          <div class="stat-label">速率</div>
          <div class="mt-1 text-[12.5px] tabular-nums">{{ fmtRate(receiver.recent_pull_bps) }}</div>
        </div>
      </HintTip>
    </div>

    <div class="flex items-center justify-end gap-3 border-t border-border/60 px-5 py-2.5">
      <HintTip text="跳转到事件日志，已按本接收端过滤">
        <RouterLink
          :to="`/events?source=${encodeURIComponent(receiver.receiver_id)}`"
          class="inline-flex h-6 items-center gap-1 rounded-md border border-border bg-background px-2 text-mini text-muted-foreground transition hover:border-primary/40 hover:text-primary"
        >
          <Icon name="events" :size="11" />
          事件
        </RouterLink>
      </HintTip>
      <NodeLifecycleActions
        :enabled="receiver.enabled"
        :pending="pending"
        @set-enabled="onSetEnabled"
        @forget="onForget"
        disable-title="禁用此接收端（不再分到新对象，可点启用恢复）"
        forget-title="永久从注册表中删除（仅在已禁用时允许）"
      />
    </div>
  </Card>
</template>
