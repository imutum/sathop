<script setup lang="ts">
import { API, type ReceiverInfo } from "@/api";
import { K } from "@/queryKeys";
import { fmtGB, fmtRate, nodeStatusBadge } from "@/lib/format";
import { PLATFORM_ZH, fmtAge } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import CopyButton from "@/components/CopyButton.vue";
import HintTip from "@/components/HintTip.vue";
import NodeLifecycleActions from "@/features/nodes/components/NodeLifecycleActions.vue";
import { useNodeLifecycle } from "@/features/nodes/useNodeLifecycle";
import { Icon } from "@/components/Icon";
import { computed } from "vue";

const props = defineProps<{ receiver: ReceiverInfo }>();

const lifecycle = useNodeLifecycle<ReceiverInfo>({
  id: props.receiver.receiver_id,
  queryKey: K.receivers,
  getId: (receiver) => receiver.receiver_id,
  setEnabled: (next) => API.setReceiverEnabled(props.receiver.receiver_id, next),
  forget: () => API.forgetReceiver(props.receiver.receiver_id),
  restart: () => API.restartReceiver(props.receiver.receiver_id),
  enabledMessage: "已启用",
  disabledMessage: "已禁用，下次 pull 会被拒绝",
  deletedMessage: `已删除接收端 ${props.receiver.receiver_id}`,
  restartMessage: "已发送重启信号，下次心跳生效",
  forgetConfirm: {
    title: `永久移除接收端 ${props.receiver.receiver_id}？`,
    description:
      "将从注册表中删除这条接收端记录。\n" +
      "如果接收端容器仍在运行，下次心跳会自动重新注册（misclick 重启容器即恢复）。\n" +
      "想让它彻底不再回来：先停掉容器再点移除。",
    confirmText: "永久移除",
    tone: "danger",
  },
  restartConfirm: {
    title: `重启接收端 ${props.receiver.receiver_id}？`,
    description:
      "向该接收端发送重启信号 — 它会在下一次心跳收到后立即退出，由容器 restart 策略拉起。\n" +
      "在手的拉取会被中断，未 ack 的对象会在重启后重新分发。",
    confirmText: "重启",
  },
});

const status = computed(() => nodeStatusBadge(props.receiver.enabled, props.receiver.last_seen));
</script>

<template>
  <Card>
    <div class="flex items-start justify-between gap-2 border-b border-border/60 px-5 py-4">
      <div class="min-w-0">
        <div class="flex items-center gap-1 font-mono text-[13px] font-semibold">
          <span class="truncate">{{ receiver.receiver_id }}</span>
          <CopyButton :value="receiver.receiver_id" title="复制接收端 ID" />
          <HintTip
            v-if="receiver.version"
            :text="`接收端上报的运行版本（来自 sathop 包元数据）— 排查问题时确认是不是最新镜像`"
          >
            <Badge tone="info" class="ml-1 font-mono">v{{ receiver.version }}</Badge>
          </HintTip>
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

    <div class="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 px-5 py-2.5">
      <Button as-child variant="outline" size="xs" class="text-muted-foreground hover:text-primary">
        <RouterLink
          :to="`/events?source=${encodeURIComponent(receiver.receiver_id)}`"
          title="跳转到事件日志，已按本接收端过滤"
        >
          <Icon name="events" :size="11" />
          事件
        </RouterLink>
      </Button>
      <NodeLifecycleActions
        :enabled="receiver.enabled"
        :pending="lifecycle.pending.value"
        @set-enabled="lifecycle.setEnabled"
        @forget="lifecycle.confirmForget"
        @restart="lifecycle.confirmRestart"
        disable-title="禁用此接收端（不再分到新对象，可点启用恢复）"
        forget-title="永久从注册表中删除（仅在已禁用时允许）"
        restart-title="向该接收端发送重启信号（一次心跳内生效）"
      />
    </div>
  </Card>
</template>
