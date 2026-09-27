<script setup lang="ts">
import { computed } from "vue";
import { useNow } from "@vueuse/core";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, type BatchSummary } from "@/api";
import { K } from "@/queryKeys";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import CardSection from "@/components/CardSection.vue";
import CopyButton from "@/components/CopyButton.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import DeliveryStats from "@/features/batch/components/DeliveryStats.vue";
import BatchProgressCell from "@/features/batch/components/BatchProgressCell.vue";
import { pipelineSegments } from "@/features/batch/pipelineSummary";
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
const now = useNow({ interval: 30_000 });

const overview = useQuery({ queryKey: [...K.overview], queryFn: API.overview });
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const receivers = useQuery({ queryKey: [...K.receivers], queryFn: API.receivers });
const bundles = useQuery({ queryKey: [...K.bundles], queryFn: API.bundles });
const batches = useQuery({ queryKey: [...K.batches], queryFn: API.batches });

const counts = computed(() => overview.data.value?.state_counts ?? {});

const activeWorkers = computed(
  () =>
    (workers.data.value ?? []).filter((w) => now.value.getTime() - new Date(w.last_seen).getTime() < 120_000)
      .length,
);
const activeReceivers = computed(
  () =>
    (receivers.data.value ?? []).filter(
      (r) => now.value.getTime() - new Date(r.last_seen).getTime() < 120_000,
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

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <CardSection title="管道健康" description="各阶段当前驻留的数据粒分布" class="lg:col-span-2">
        <div v-if="overview.isPending.value" class="space-y-4 py-4" role="status" aria-label="正在加载管道状态">
          <Skeleton class="h-6 w-36" />
          <Skeleton class="h-16 w-full" />
          <Skeleton class="h-6 w-2/3" />
        </div>
        <p v-else-if="overview.data.value === undefined" class="py-12 text-center text-sm text-muted-foreground">管道状态暂不可用，请重试。</p>
        <div v-else-if="!hasChartData" class="flex h-44 items-center justify-center">
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
          <Skeleton v-if="workers.isPending.value" class="h-24 w-full" role="status" aria-label="正在加载工作节点" />
          <Alert v-else-if="workers.data.value === undefined" variant="destructive">
            <AlertDescription class="flex items-center justify-between gap-2">
              <span>工作节点加载失败</span>
              <Button size="sm" variant="outline" @click="workers.refetch()">重试</Button>
            </AlertDescription>
          </Alert>
          <NodeStat
            v-else
            label="工作节点"
            :value="activeWorkers"
            :total="workers.data.value?.length ?? 0"
            tooltip="点击查看节点详情；'在线' = 心跳在 2 分钟内"
            @click="router.push('/workers')"
          >
            <template #icon><Icon name="workers" :size="18" /></template>
          </NodeStat>
          <Skeleton v-if="receivers.isPending.value" class="h-24 w-full" role="status" aria-label="正在加载接收端" />
          <Alert v-else-if="receivers.data.value === undefined" variant="destructive">
            <AlertDescription class="flex items-center justify-between gap-2">
              <span>接收端加载失败</span>
              <Button size="sm" variant="outline" @click="receivers.refetch()">重试</Button>
            </AlertDescription>
          </Alert>
          <NodeStat
            v-else
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

    <CardSection title="活跃批次" :description="batches.data.value ? `${activeBatches.length} 个未结束 · 点击进入详情` : '批次执行进度与异常'">
      <div v-if="batches.isPending.value" class="grid grid-cols-1 gap-3 xl:grid-cols-2" role="status" aria-label="正在加载批次">
        <Skeleton v-for="i in 2" :key="i" class="h-28 w-full" />
      </div>
      <Alert v-else-if="batches.data.value === undefined" variant="destructive">
        <AlertDescription class="flex items-center justify-between gap-3">
          <span>批次加载失败：{{ batches.error.value?.message }}</span>
          <Button size="sm" variant="outline" @click="batches.refetch()">重试</Button>
        </AlertDescription>
      </Alert>
      <EmptyState
        v-else-if="activeBatches.length === 0"
        title="当前没有未结束的批次"
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
            <div class="flex shrink-0 flex-wrap justify-end gap-1.5">
              <Badge v-if="r.b.status === 'paused'" tone="warn">已暂停</Badge>
              <Badge tone="info">{{ r.b.target_receiver_id ?? "任意" }}</Badge>
            </div>
          </div>
          <BatchProgressCell
            class="mt-3"
            :done="r.done"
            :total="r.total"
            :pct="r.pct"
            :eta-realtime="r.b.status === 'paused' ? null : r.b.eta_realtime ?? null"
            :in-flight="r.inFlight"
            :errors="r.errors"
            :exhausted="r.b.objects_exhausted"
          />
        </RouterLink>
      </div>
    </CardSection>
  </div>
</template>
