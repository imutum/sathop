<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, type BatchSummary, type GranuleState } from "@/api";
import { K } from "@/queryKeys";
import { stateLabel } from "@/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import CardSection from "@/components/CardSection.vue";
import CopyButton from "@/components/CopyButton.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import Stat from "@/components/Stat.vue";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import DeliveryStats from "@/features/batch/components/DeliveryStats.vue";
import BatchProgressCell from "@/features/batch/components/BatchProgressCell.vue";
import { pipelineSegments, pipelineTotals } from "@/features/batch/pipelineSummary";
import {
  completedTotal,
  errorTotal,
  inFlightTotal,
  isBatchClosed,
  totalCount,
} from "@/features/batch/summary";
import NodeStat from "@/features/nodes/components/NodeStat.vue";
import OnboardingCard from "@/components/onboarding/OnboardingCard.vue";
import { Icon } from "@/components/Icon";

const router = useRouter();

const overview = useQuery({ queryKey: [...K.overview], queryFn: API.overview });
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const receivers = useQuery({ queryKey: [...K.receivers], queryFn: API.receivers });
const bundles = useQuery({ queryKey: [...K.bundles], queryFn: API.bundles });
const batches = useQuery({ queryKey: [...K.batches], queryFn: API.batches });

const counts = computed(() => overview.data.value?.state_counts ?? {});
const stuck = computed(() => overview.data.value?.stuck_by_state ?? {});
const stuckTotal = computed(() => Object.values(stuck.value).reduce((a, b) => a + (b ?? 0), 0));
const pipeline = computed(() => pipelineTotals(counts.value));
const failed = computed(() => pipeline.value.failed);
const inflightTotal = computed(() => pipeline.value.active);
const done = computed(() => pipeline.value.done);

const stuckHint = computed(() =>
  stuckTotal.value > 0
    ? Object.entries(stuck.value)
        .map(([k, v]) => `${stateLabel(k as GranuleState)} ${v}`)
        .join(" · ")
    : "一切正常",
);
const stuckHours = computed(() => overview.data.value?.stuck_over_hours ?? 6);

const activeWorkers = computed(
  () =>
    (workers.data.value ?? []).filter((w) => Date.now() - new Date(w.last_seen).getTime() < 120_000)
      .length,
);
const activeReceivers = computed(
  () =>
    (receivers.data.value ?? []).filter(
      (r) => Date.now() - new Date(r.last_seen).getTime() < 120_000,
    ).length,
);

const hasChartData = computed(() => pipelineSegments(counts.value).length > 0);
const throughputPerMin = computed(() => overview.data.value?.throughput_per_min ?? null);
const etaRealtime = computed(() => overview.data.value?.eta_realtime ?? null);

// 活跃批次 = 未关闭（仍有在途或失败）。决策层焦点："此刻在跑哪些批次、进度如何"。
// 进度条复用便宜的 counts 计数（BatchProgressCell），点击进详情。
type ActiveBatchRow = {
  b: BatchSummary;
  total: number;
  done: number;
  errors: number;
  inFlight: number;
  pct: number;
};
const activeBatches = computed<ActiveBatchRow[]>(() =>
  (batches.data.value ?? [])
    .filter((b) => !isBatchClosed(b))
    .map((b) => {
      const total = totalCount(b.counts);
      const d = completedTotal(b);
      return {
        b,
        total,
        done: d,
        errors: errorTotal(b),
        inFlight: inFlightTotal(b),
        pct: total > 0 ? Math.round((d / total) * 100) : 0,
      };
    }),
);

// Onboarding checklist reflects real cluster state, shown until all three done.
const onboardStatus = computed(() => ({
  worker: (workers.data.value?.length ?? 0) > 0,
  bundle: (bundles.data.value?.length ?? 0) > 0,
  batch: Object.keys(counts.value).length > 0,
}));
const showOnboarding = computed(
  () =>
    overview.isSuccess.value &&
    workers.isSuccess.value &&
    bundles.isSuccess.value &&
    !(onboardStatus.value.worker && onboardStatus.value.bundle && onboardStatus.value.batch),
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="总览" description="管线健康一览 · 后台事件流实时推送" />

    <Alert v-if="overview.error.value && overview.data.value === undefined" variant="destructive">
      <AlertDescription class="flex items-center justify-between gap-3">
        <span>加载总览失败：{{ overview.error.value.message }}</span>
        <Button size="sm" variant="outline" @click="overview.refetch()">重试</Button>
      </AlertDescription>
    </Alert>

    <OnboardingCard v-if="showOnboarding" :status="onboardStatus" />

    <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Stat
        label="进行中"
        :value="inflightTotal.toLocaleString()"
        hint="lease ~ 待交付之间的活粒"
        tooltip="待下载 / 下载中 / 待处理 / 处理中 / 待上传 / 上传中 / 待分发 七个阶段合计。不含 待分配 与 已交付。"
        to="/batches"
      >
        <template #icon><Icon name="pulse" :size="18" /></template>
      </Stat>
      <Stat
        label="已交付"
        :value="done.toLocaleString()"
        tone="good"
        hint="已交付计数"
        tooltip="receiver 已确认（acked）或已清理（deleted）——数据粒已交付。"
        to="/batches"
      >
        <template #icon><Icon name="check" :size="18" /></template>
      </Stat>
      <Stat
        label="异常"
        :value="failed.toLocaleString()"
        :tone="failed > 0 ? 'bad' : 'default'"
        :hint="failed > 0 ? '点击查看错误事件' : '本周期无异常'"
        tooltip="待重试 + 已拉黑数据粒之和。已拉黑表示达到自动重试上限，需手动重置。"
        :to="failed > 0 ? '/events?level=error' : '/batches'"
      >
        <template #icon><Icon name="alert" :size="18" /></template>
      </Stat>
      <Stat
        :label="`卡住 > ${stuckHours} 小时`"
        :value="stuckTotal.toLocaleString()"
        :tone="stuckTotal > 0 ? 'warn' : 'default'"
        :hint="stuckHint"
        tooltip="非终态、且最近一次状态推进发生在 N 小时之前的数据粒。点击进健康诊断查看逐粒明细。"
        to="/health"
      >
        <template #icon><Icon name="settings" :size="18" /></template>
      </Stat>
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <CardSection title="管道健康" description="各阶段当前驻留的数据粒分布" class="lg:col-span-2">
        <div v-if="!hasChartData" class="flex h-44 items-center justify-center">
          <EmptyState title="暂无数据粒" description="管线空闲，等待新批次注入" illustration="signal" />
        </div>
        <template v-else>
          <PipelineHealth :counts="counts" />
          <DeliveryStats
            class="mt-5"
            :throughput-per-min="throughputPerMin"
            :eta-seconds="etaRealtime"
          />
        </template>
      </CardSection>

      <CardSection title="节点" description="集群健康度">
        <div class="space-y-3">
          <NodeStat
            label="工作节点"
            :value="activeWorkers"
            :total="workers.data.value?.length ?? 0"
            tooltip="点击查看节点详情；'在线' = 心跳在 2 分钟内"
            @click="router.push('/workers')"
          >
            <template #icon><Icon name="workers" :size="18" /></template>
          </NodeStat>
          <NodeStat
            label="接收端"
            :value="activeReceivers"
            :total="receivers.data.value?.length ?? 0"
            tooltip="点击查看接收端详情；'在线' = 心跳在 2 分钟内"
            @click="router.push('/receivers')"
          >
            <template #icon><Icon name="receivers" :size="18" /></template>
          </NodeStat>
        </div>
      </CardSection>
    </div>

    <CardSection title="正在执行的批次" :description="`${activeBatches.length} 个进行中 · 点击进入详情`">
      <EmptyState
        v-if="activeBatches.length === 0"
        title="当前没有进行中的批次"
        description="新建批次后会出现在这里；已完成的批次见批次页"
        illustration="signal"
      >
        <template #action>
          <Button variant="default" @click="router.push('/batches')">
            <Icon name="plus" :size="13" />
            新建任务
          </Button>
        </template>
      </EmptyState>
      <div v-else class="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <RouterLink
          v-for="r in activeBatches"
          :key="r.b.batch_id"
          :to="`/batches/${r.b.batch_id}`"
          class="block rounded-xl border border-border bg-card p-4 shadow-soft transition hover:border-primary/40 hover:shadow-pop"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="truncate font-medium text-foreground">{{ r.b.name }}</div>
              <div class="mt-0.5 inline-flex items-center font-mono text-2xs text-muted-foreground" @click.stop.prevent>
                {{ r.b.batch_id }}
                <CopyButton :value="r.b.batch_id" title="复制批次 ID" />
              </div>
            </div>
            <Badge tone="info" class="shrink-0">{{ r.b.target_receiver_id ?? "任意" }}</Badge>
          </div>
          <BatchProgressCell
            class="mt-3"
            :done="r.done"
            :total="r.total"
            :pct="r.pct"
            :eta-realtime="r.b.eta_realtime ?? null"
            :in-flight="r.inFlight"
            :errors="r.errors"
            :exhausted="r.b.objects_exhausted"
          />
        </RouterLink>
      </div>
    </CardSection>
  </div>
</template>
