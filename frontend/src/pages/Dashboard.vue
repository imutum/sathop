<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, type GranuleState } from "@/api";
import { K } from "@/queryKeys";
import { fmtAge, stateLabel } from "@/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import CardSection from "@/components/CardSection.vue";
import EmptyState from "@/components/EmptyState.vue";
import WorkerRef from "@/components/WorkerRef.vue";
import EventTimeline from "@/components/EventTimeline.vue";
import HintTip from "@/components/HintTip.vue";
import PageHeader from "@/components/PageHeader.vue";
import Stat from "@/components/Stat.vue";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import DeliveryStats from "@/features/batch/components/DeliveryStats.vue";
import { pipelineSegments, pipelineTotals } from "@/features/batch/pipelineSummary";
import NodeStat from "@/features/nodes/components/NodeStat.vue";
import OnboardingCard from "@/components/onboarding/OnboardingCard.vue";
import { Icon } from "@/components/Icon";

const router = useRouter();

const overview = useQuery({ queryKey: [...K.overview], queryFn: API.overview });
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const receivers = useQuery({ queryKey: [...K.receivers], queryFn: API.receivers });
const bundles = useQuery({ queryKey: [...K.bundles], queryFn: API.bundles });
const inflight = useQuery({ queryKey: [...K.inflight], queryFn: () => API.inFlight(30) });
const stuckList = useQuery({
  queryKey: [...K.stuck],
  queryFn: () => API.stuck(50),
  enabled: computed(
    () =>
      Object.values(overview.data.value?.stuck_by_state ?? {}).reduce((a, b) => a + (b ?? 0), 0) > 0,
  ),
});

const counts = computed(() => overview.data.value?.state_counts ?? {});
const stuck = computed(() => overview.data.value?.stuck_by_state ?? {});
const stuckTotal = computed(() =>
  Object.values(stuck.value).reduce((a, b) => a + (b ?? 0), 0),
);
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

const activeWorkers = computed(
  () =>
    (workers.data.value ?? []).filter(
      (w) => Date.now() - new Date(w.last_seen).getTime() < 120_000,
    ).length,
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
const active = computed(() => inflight.data.value ?? []);

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

const lastEvents = computed(() => overview.data.value?.last_events ?? []);
const stuckRows = computed(() => stuckList.data.value ?? []);
const stuckHours = computed(() => overview.data.value?.stuck_over_hours ?? 6);

function gotoGranule(batchId: string, granuleId: string) {
  router.push(`/batches/${batchId}?granule=${encodeURIComponent(granuleId)}`);
}

function fmtHours(h: number): string {
  if (h < 24) return `${h.toFixed(1)} 小时`;
  return `${(h / 24).toFixed(1)} 天`;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="总览" description="管线健康一览 · 后台事件流实时推送" />

    <Alert
      v-if="overview.error.value && overview.data.value === undefined"
      variant="destructive"
    >
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
        tooltip="非终态、且最近一次状态推进发生在 N 小时之前的数据粒。可能是 worker 失联、下载卡死或脚本无响应。"
      >
        <template #icon><Icon name="settings" :size="18" /></template>
      </Stat>
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <CardSection
        title="管道健康"
        description="各阶段当前驻留的数据粒分布"
        class="lg:col-span-2"
      >
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

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <CardSection
        title="正在处理"
        description="近 30 条非终态数据粒"
        :padded="false"
        class="lg:col-span-2"
      >
        <template #meta>
          <Badge v-if="active.length > 0" variant="info" class="tabular-nums">{{ active.length }} 条</Badge>
          <Badge v-else variant="outline" class="text-muted-foreground">空闲</Badge>
        </template>
        <EmptyState
          v-if="active.length === 0"
          title="当前没有正在处理的数据粒"
          description="新建批次后，活动条目会自动出现在这里"
          illustration="signal"
        />
        <Table v-else>
          <TableHeader class="bg-muted/40">
            <TableRow>
              <TableHead class="px-5">数据粒</TableHead>
              <TableHead>批次</TableHead>
              <TableHead>当前阶段</TableHead>
              <TableHead>工作节点</TableHead>
              <TableHead class="px-5">更新</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="g in active"
              :key="g.granule_id"
              role="button"
              tabindex="0"
              class="cursor-pointer focus:outline-none focus-visible:bg-muted/50"
              @click="gotoGranule(g.batch_id, g.granule_id)"
              @keydown.enter="gotoGranule(g.batch_id, g.granule_id)"
              @keydown.space.prevent="gotoGranule(g.batch_id, g.granule_id)"
            >
              <TableCell class="px-5 py-2.5 font-mono text-cell">{{ g.granule_id }}</TableCell>
              <TableCell class="py-2.5 font-mono text-cell text-muted-foreground">{{ g.batch_id }}</TableCell>
              <TableCell class="py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </TableCell>
              <TableCell
                class="py-2.5 font-mono text-cell text-muted-foreground"
                @click.stop
              >
                <WorkerRef :worker-id="g.leased_by" />
              </TableCell>
              <TableCell class="px-5 py-2.5 text-cell text-muted-foreground">{{ fmtAge(g.updated_at) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardSection>

      <CardSection title="最近事件" description="最新 10 条" :padded="false">
        <template #meta>
          <Button as-child variant="ghost" size="xs" class="text-muted-foreground hover:text-foreground">
            <RouterLink to="/events">查看全部</RouterLink>
          </Button>
        </template>
        <EmptyState
          v-if="lastEvents.length === 0"
          title="暂无事件"
          illustration="inbox"
        />
        <EventTimeline v-else :events="lastEvents" />
      </CardSection>
    </div>

    <CardSection
      v-if="stuckTotal > 0"
      title="卡住的数据粒"
      :description="`非终态且 > ${stuckHours} 小时未推进 · 最旧者优先`"
      :padded="false"
      class="border-warning/40"
    >
      <template #meta>
        <HintTip text="数据粒在非终态停留过久，多半是 worker 失联、下载卡死或脚本无响应。点击行查看其事件日志。">
          <Badge variant="warning" class="tabular-nums">{{ stuckRows.length }} / {{ stuckTotal }}</Badge>
        </HintTip>
      </template>
      <Table>
        <TableHeader class="bg-muted/40">
          <TableRow>
            <TableHead class="px-5">数据粒</TableHead>
            <TableHead>批次</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>领取方</TableHead>
            <TableHead>滞留</TableHead>
            <TableHead class="px-5">错误</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="g in stuckRows"
            :key="g.granule_id"
            role="button"
            tabindex="0"
            class="cursor-pointer focus:outline-none focus-visible:bg-muted/50"
            @click="gotoGranule(g.batch_id, g.granule_id)"
            @keydown.enter="gotoGranule(g.batch_id, g.granule_id)"
            @keydown.space.prevent="gotoGranule(g.batch_id, g.granule_id)"
          >
            <TableCell class="px-5 py-2.5 font-mono text-cell">{{ g.granule_id }}</TableCell>
            <TableCell class="py-2.5 font-mono text-cell text-muted-foreground">{{ g.batch_id }}</TableCell>
            <TableCell class="py-2.5">
              <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
            </TableCell>
            <TableCell
              class="py-2.5 font-mono text-cell text-muted-foreground"
              @click.stop
            >
              <WorkerRef :worker-id="g.leased_by" />
            </TableCell>
            <TableCell class="py-2.5 text-cell text-warning tabular-nums">
              {{ fmtHours(g.age_hours) }}
            </TableCell>
            <TableCell class="max-w-[320px] truncate px-5 py-2.5 font-mono text-cell text-danger">
              {{ g.error ?? "—" }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardSection>
  </div>
</template>
