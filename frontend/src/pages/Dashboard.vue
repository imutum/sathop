<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, STATE_ORDER, type GranuleState } from "@/api";
import { fmtAge, stateLabel } from "@/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import EmptyState from "@/components/EmptyState.vue";
import EventTimeline from "@/components/EventTimeline.vue";
import HintTip from "@/components/HintTip.vue";
import PageHeader from "@/components/PageHeader.vue";
import Stat from "@/components/Stat.vue";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import NodeStat from "@/features/nodes/components/NodeStat.vue";
import OnboardingCard from "@/components/onboarding/OnboardingCard.vue";
import { Icon } from "@/components/Icon";

const router = useRouter();

const overview = useQuery({ queryKey: ["overview"], queryFn: API.overview });
const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });
const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
const inflight = useQuery({ queryKey: ["in-flight"], queryFn: () => API.inFlight(30) });
const stuckList = useQuery({
  queryKey: ["stuck"],
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
const failed = computed(() => (counts.value.failed ?? 0) + (counts.value.blacklisted ?? 0));
const inflightTotal = computed(() =>
  STATE_ORDER.reduce(
    (s, k) => (k === "deleted" ? s : s + (counts.value[k] ?? 0)),
    0,
  ),
);
const done = computed(() => counts.value.deleted ?? 0);

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

const hasChartData = computed(() => STATE_ORDER.some((s) => (counts.value[s] ?? 0) > 0));

const active = computed(() => inflight.data.value ?? []);

const firstRun = computed(
  () =>
    overview.isSuccess.value &&
    workers.isSuccess.value &&
    Object.keys(counts.value).length === 0 &&
    (workers.data.value?.length ?? 0) === 0,
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

    <OnboardingCard v-if="firstRun" />

    <!-- Four stat cards. Each carries a tooltip that explains *what the
         number means* — operators new to SatHop shouldn't have to dig. -->
    <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Stat
        label="处理中"
        :value="inflightTotal.toLocaleString()"
        hint="尚未达到终态的数据粒"
        tooltip="所有非终态数据粒的总和。终态 = 已清理 / 已 ack。"
        to="/batches"
      >
        <template #icon><Icon name="pulse" :size="18" /></template>
      </Stat>
      <Stat
        label="已完成"
        :value="done.toLocaleString()"
        tone="good"
        hint="累计已清理"
        tooltip="管线终态计数 — 数据粒被 receiver 拉走 + worker 上的产物已删除。"
        to="/batches"
      >
        <template #icon><Icon name="check" :size="18" /></template>
      </Stat>
      <Stat
        label="失败"
        :value="failed.toLocaleString()"
        :tone="failed > 0 ? 'bad' : 'default'"
        :hint="failed > 0 ? '点击查看错误事件' : '本周期无异常'"
        tooltip="失败 + 已拉黑数据粒之和。已拉黑表示达到自动重试上限。"
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
      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle>管道健康</CardTitle>
          <CardDescription>各阶段当前驻留的数据粒分布</CardDescription>
        </CardHeader>
        <CardContent>
          <div v-if="!hasChartData" class="flex h-44 items-center justify-center">
            <EmptyState title="暂无数据粒" description="管线空闲，等待新批次注入" illustration="signal" />
          </div>
          <PipelineHealth v-else :counts="counts" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>节点</CardTitle>
          <CardDescription>集群健康度</CardDescription>
        </CardHeader>
        <CardContent>
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
        </CardContent>
      </Card>
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
          <div class="space-y-1.5">
            <CardTitle>正在处理</CardTitle>
            <CardDescription>近 30 条非终态数据粒 · 点击行进入详情</CardDescription>
          </div>
          <span
            :class="[
              'rounded-full border px-2.5 py-0.5 text-2xs font-medium tabular-nums',
              active.length > 0
                ? 'border-primary/30 bg-primary/10 text-primary'
                : 'border-border bg-muted text-muted-foreground',
            ]"
          >
            {{ active.length > 0 ? `${active.length} 条` : "空闲" }}
          </span>
        </CardHeader>
        <EmptyState
          v-if="active.length === 0"
          title="当前没有正在处理的数据粒"
          description="新建批次后，活动条目会自动出现在这里"
          illustration="signal"
        />
        <Table v-else>
          <TableHeader class="bg-muted/50">
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
              class="cursor-pointer"
              title="点击查看该数据粒的详情、进度与事件"
              @click="gotoGranule(g.batch_id, g.granule_id)"
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
                <RouterLink
                  v-if="g.leased_by"
                  :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                  class="transition hover:text-primary"
                  title="跳转到该 worker 卡片"
                >
                  {{ g.leased_by }}
                </RouterLink>
                <template v-else>—</template>
              </TableCell>
              <TableCell class="px-5 py-2.5 text-cell text-muted-foreground">{{ fmtAge(g.updated_at) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Card>

      <Card>
        <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
          <div class="space-y-1.5">
            <CardTitle>最近事件</CardTitle>
            <CardDescription>最新 10 条 · 点击查看全部</CardDescription>
          </div>
          <RouterLink
            to="/events"
            class="rounded-md border border-border bg-background px-2.5 py-1 text-2xs font-medium text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          >
            查看全部
          </RouterLink>
        </CardHeader>
        <EmptyState
          v-if="lastEvents.length === 0"
          title="暂无事件"
          illustration="inbox"
        />
        <EventTimeline v-else :events="lastEvents" />
      </Card>
    </div>

    <!-- Stuck panel — only shown when something is genuinely stuck. The
         border-warning rim makes it impossible to miss. -->
    <Card v-if="stuckTotal > 0" class="border-warning/40">
      <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
        <div class="space-y-1.5">
          <CardTitle>卡住的数据粒</CardTitle>
          <CardDescription>非终态且 &gt; {{ stuckHours }} 小时未推进 · 最旧者优先</CardDescription>
        </div>
        <HintTip text="数据粒在非终态停留过久，多半是 worker 失联、下载卡死或脚本无响应。点击行查看其事件日志。">
          <span
            class="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-2xs font-medium text-warning tabular-nums"
          >
            {{ stuckRows.length }} / {{ stuckTotal }}
          </span>
        </HintTip>
      </CardHeader>
      <Table>
        <TableHeader class="bg-muted/50">
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
            class="cursor-pointer"
            title="点击查看该数据粒的详情、进度与事件"
            @click="gotoGranule(g.batch_id, g.granule_id)"
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
              <RouterLink
                v-if="g.leased_by"
                :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                class="transition hover:text-primary"
              >
                {{ g.leased_by }}
              </RouterLink>
              <template v-else>—</template>
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
    </Card>
  </div>
</template>
