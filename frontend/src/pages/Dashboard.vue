<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, STATE_ORDER, type GranuleState } from "@/api";
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
import EmptyState from "@/components/EmptyState.vue";
import EventTimeline from "@/components/EventTimeline.vue";
import PageHeader from "@/components/PageHeader.vue";
import Stat from "@/components/Stat.vue";
import Panel from "@/components/chrome/Panel.vue";
import SectionLabel from "@/components/chrome/SectionLabel.vue";
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
    : "ALL CLEAR",
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
  <div class="space-y-8">
    <PageHeader n="01" kicker="TELEMETRY" title="任务总览">
      <template #description>
        分布式数据管线的实时遥测视图 · SSE 推送 · UTC 时基
      </template>
      <template #meta>
        <span>STREAM · ACTIVE</span>
      </template>
    </PageHeader>

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

    <!-- ─── Stat row : 4 channel readouts ────────────────────────────────── -->
    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat code="T-01" label="处理中" :value="inflightTotal.toLocaleString()" :hint="`${inflightTotal} 条在管`" to="/batches">
        <template #icon><Icon name="pulse" :size="16" /></template>
      </Stat>
      <Stat code="T-02" label="已完成" :value="done.toLocaleString()" tone="good" :hint="`累计清理 ${done}`" to="/batches">
        <template #icon><Icon name="check" :size="16" /></template>
      </Stat>
      <Stat
        code="T-03"
        label="失败"
        :value="failed.toLocaleString()"
        :tone="failed > 0 ? 'bad' : 'default'"
        :hint="failed > 0 ? '需要介入' : '本周期无异常'"
        :to="failed > 0 ? '/events?level=error' : '/batches'"
      >
        <template #icon><Icon name="alert" :size="16" /></template>
      </Stat>
      <Stat
        code="T-04"
        :label="`卡住 > ${stuckHours}h`"
        :value="stuckTotal.toLocaleString()"
        :tone="stuckTotal > 0 ? 'warn' : 'default'"
        :hint="stuckHint"
      >
        <template #icon><Icon name="settings" :size="16" /></template>
      </Stat>
    </div>

    <!-- ─── Pipeline + Fleet ─────────────────────────────────────────────── -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Panel class="lg:col-span-2" :live="hasChartData">
        <header class="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div class="space-y-2">
            <SectionLabel n="02" label="Pipeline Health" caption="各阶段数据粒分布" />
            <h2 class="font-display text-[22px] font-medium leading-tight tracking-tight text-foreground">
              管道健康
              <span class="text-muted-foreground/60">/</span>
              <span class="text-muted-foreground">阶段分布</span>
            </h2>
          </div>
          <span
            v-if="hasChartData"
            class="readout inline-flex items-center gap-2 rounded-sm border border-primary/30 bg-primary/10 px-2 py-1 text-3xs font-semibold uppercase tracking-section text-primary"
          >
            <span class="signal-led" aria-hidden />
            STREAMING
          </span>
        </header>
        <div class="rule mx-5" />
        <div class="px-5 py-5">
          <div v-if="!hasChartData" class="flex h-44 items-center justify-center">
            <EmptyState title="暂无数据粒" description="管线空闲，等待新批次注入" illustration="signal" />
          </div>
          <PipelineHealth v-else :counts="counts" />
        </div>
      </Panel>

      <Panel>
        <header class="space-y-2 px-5 pt-4 pb-3">
          <SectionLabel n="03" label="Fleet" caption="集群健康度" />
          <h2 class="font-display text-[22px] font-medium leading-tight tracking-tight text-foreground">
            节点
            <span class="text-muted-foreground/60">/</span>
            <span class="text-muted-foreground">舰队</span>
          </h2>
        </header>
        <div class="rule mx-5" />
        <div class="space-y-3 px-5 py-5">
          <NodeStat
            label="工作节点"
            :value="activeWorkers"
            :total="workers.data.value?.length ?? 0"
            @click="router.push('/workers')"
          >
            <template #icon><Icon name="workers" :size="17" /></template>
          </NodeStat>
          <NodeStat
            label="接收端"
            :value="activeReceivers"
            :total="receivers.data.value?.length ?? 0"
            @click="router.push('/receivers')"
          >
            <template #icon><Icon name="receivers" :size="17" /></template>
          </NodeStat>
        </div>
      </Panel>
    </div>

    <!-- ─── Active queue + Signal log ────────────────────────────────────── -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Panel class="lg:col-span-2">
        <header class="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div class="space-y-2">
            <SectionLabel n="04" label="Active Queue" caption="近 30 条非终态数据粒" />
            <h2 class="font-display text-[22px] font-medium leading-tight tracking-tight text-foreground">
              正在处理
            </h2>
          </div>
          <span
            :class="[
              'readout inline-flex items-center gap-2 rounded-sm border px-2 py-1 text-3xs font-semibold uppercase tracking-section',
              active.length > 0
                ? 'border-primary/30 bg-primary/10 text-primary'
                : 'border-border bg-muted text-muted-foreground',
            ]"
          >
            <span :class="['signal-led', active.length === 0 && 'signal-led--idle']" aria-hidden />
            {{ active.length > 0 ? `${active.length}·LIVE` : "IDLE" }}
          </span>
        </header>
        <div class="rule mx-5" />
        <EmptyState
          v-if="active.length === 0"
          title="管线空闲"
          description="所有数据粒已处理完成或队列为空"
          illustration="signal"
        />
        <Table v-else>
          <TableHeader class="bg-muted/50">
            <TableRow>
              <TableHead class="px-5 text-3xs uppercase tracking-section">数据粒</TableHead>
              <TableHead class="text-3xs uppercase tracking-section">批次</TableHead>
              <TableHead class="text-3xs uppercase tracking-section">阶段</TableHead>
              <TableHead class="text-3xs uppercase tracking-section">节点</TableHead>
              <TableHead class="px-5 text-3xs uppercase tracking-section">更新</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="g in active"
              :key="g.granule_id"
              class="cursor-pointer"
              title="跳转到该数据粒详情"
              @click="gotoGranule(g.batch_id, g.granule_id)"
            >
              <TableCell class="px-5 py-2.5 readout text-cell">{{ g.granule_id }}</TableCell>
              <TableCell class="py-2.5 readout text-cell text-muted-foreground">{{ g.batch_id }}</TableCell>
              <TableCell class="py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </TableCell>
              <TableCell
                class="py-2.5 readout text-cell text-muted-foreground"
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
              <TableCell class="px-5 py-2.5 readout text-cell text-muted-foreground">{{ fmtAge(g.updated_at) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Panel>

      <Panel>
        <header class="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div class="space-y-2">
            <SectionLabel n="05" variant="live" label="Signal Log" caption="最近 10 条事件" />
            <h2 class="font-display text-[22px] font-medium leading-tight tracking-tight text-foreground">
              事件流
            </h2>
          </div>
          <RouterLink
            to="/events"
            class="readout inline-flex items-center gap-1.5 rounded-sm border border-border bg-background px-2 py-1 text-3xs font-semibold uppercase tracking-section text-muted-foreground transition hover:border-primary/40 hover:text-primary"
          >
            查看全部
            <Icon name="arrowRight" :size="11" />
          </RouterLink>
        </header>
        <div class="rule mx-5" />
        <EmptyState
          v-if="lastEvents.length === 0"
          title="暂无事件"
          illustration="signal"
        />
        <EventTimeline v-else :events="lastEvents" />
      </Panel>
    </div>

    <!-- ─── Stuck panel — only when something is genuinely stuck ─────────── -->
    <Panel v-if="stuckTotal > 0" :live="false" class="border-warning/40">
      <header class="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
        <div class="space-y-2">
          <SectionLabel n="06" label="Anomalies" caption="非终态且超时数据粒" />
          <h2 class="font-display text-[22px] font-medium leading-tight tracking-tight text-foreground">
            卡住的数据粒
            <span class="text-muted-foreground/60">·</span>
            <span class="text-warning">> {{ stuckHours }}h</span>
          </h2>
        </div>
        <span
          class="readout inline-flex items-center gap-1.5 rounded-sm border border-warning/40 bg-warning/10 px-2 py-1 text-3xs font-semibold uppercase tracking-section text-warning tabular-nums"
        >
          <span class="h-1 w-1 rounded-full bg-warning" aria-hidden />
          {{ stuckRows.length }} / {{ stuckTotal }}
        </span>
      </header>
      <div class="rule mx-5" />
      <Table>
        <TableHeader class="bg-muted/50">
          <TableRow>
            <TableHead class="px-5 text-3xs uppercase tracking-section">数据粒</TableHead>
            <TableHead class="text-3xs uppercase tracking-section">批次</TableHead>
            <TableHead class="text-3xs uppercase tracking-section">状态</TableHead>
            <TableHead class="text-3xs uppercase tracking-section">领取方</TableHead>
            <TableHead class="text-3xs uppercase tracking-section">滞留</TableHead>
            <TableHead class="px-5 text-3xs uppercase tracking-section">错误</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="g in stuckRows"
            :key="g.granule_id"
            class="cursor-pointer"
            title="跳转到该数据粒详情"
            @click="gotoGranule(g.batch_id, g.granule_id)"
          >
            <TableCell class="px-5 py-2.5 readout text-cell">{{ g.granule_id }}</TableCell>
            <TableCell class="py-2.5 readout text-cell text-muted-foreground">{{ g.batch_id }}</TableCell>
            <TableCell class="py-2.5">
              <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
            </TableCell>
            <TableCell
              class="py-2.5 readout text-cell text-muted-foreground"
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
            <TableCell class="py-2.5 readout text-cell text-warning tabular-nums">
              {{ fmtHours(g.age_hours) }}
            </TableCell>
            <TableCell class="max-w-[320px] truncate px-5 py-2.5 readout text-cell text-danger">
              {{ g.error ?? "—" }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Panel>
  </div>
</template>
