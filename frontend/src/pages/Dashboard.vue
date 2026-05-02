<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, STATE_ORDER, type GranuleState } from "@/api";
import { fmtAge, levelLabel, stateLabel } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import Stat from "@/components/Stat.vue";
import StateBarChart from "@/features/batch/components/StateBarChart.vue";
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
  // No point fetching when nothing is stuck — the count comes from `overview`.
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
// Sum of every state except `deleted` — i.e. granules still occupying any
// resource (worker disk, receiver mailbox).
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
        .map(([k, v]) => `${stateLabel(k as GranuleState)}:${v}`)
        .join(" · ")
    : "一切顺利",
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
    <PageHeader title="总览" description="管道健康一览 · SSE 实时更新" />

    <OnboardingCard v-if="firstRun" />

    <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Stat label="处理中" :value="inflightTotal.toLocaleString()" to="/batches">
        <template #icon><Icon name="pulse" /></template>
      </Stat>
      <Stat label="已完成" :value="done.toLocaleString()" tone="good" to="/batches">
        <template #icon><Icon name="check" /></template>
      </Stat>
      <Stat
        label="失败"
        :value="failed.toLocaleString()"
        :tone="failed > 0 ? 'bad' : 'default'"
        :to="failed > 0 ? '/events?level=error' : '/batches'"
      >
        <template #icon><Icon name="alert" /></template>
      </Stat>
      <Stat
        :label="`卡住 > ${stuckHours} 小时`"
        :value="stuckTotal.toLocaleString()"
        :tone="stuckTotal > 0 ? 'warn' : 'default'"
        :hint="stuckHint"
      />
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle>各阶段数据粒数量</CardTitle>
          <CardDescription>管线各阶段当前驻留数据粒</CardDescription>
        </CardHeader>
        <CardContent>
          <div v-if="!hasChartData" class="flex h-56 items-center justify-center">
            <EmptyState title="暂无数据粒" />
          </div>
          <StateBarChart v-else :counts="counts" />
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
              @click="router.push('/workers')"
            >
              <template #icon><Icon name="workers" /></template>
            </NodeStat>
            <NodeStat
              label="接收端"
              :value="activeReceivers"
              :total="receivers.data.value?.length ?? 0"
              @click="router.push('/receivers')"
            >
              <template #icon><Icon name="receivers" /></template>
            </NodeStat>
          </div>
        </CardContent>
      </Card>
    </div>

    <Card>
      <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
        <div class="space-y-1.5">
          <CardTitle>正在处理</CardTitle>
          <CardDescription>近 30 条非终态数据粒</CardDescription>
        </div>
        <span class="rounded-full border border-border bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground tabular-nums">
          {{ active.length > 0 ? `${active.length} 条` : "空闲" }}
        </span>
      </CardHeader>
      <EmptyState
        v-if="active.length === 0"
        title="当前没有正在处理的数据粒"
        description="新建批次后，活动条目会自动出现在这里。"
      />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted/50 th-row">
            <tr>
              <th class="px-5 py-2.5">数据粒</th>
              <th class="px-2 py-2.5">批次</th>
              <th class="px-2 py-2.5">当前阶段</th>
              <th class="px-2 py-2.5">工作节点</th>
              <th class="px-5 py-2.5">更新</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="g in active"
              :key="g.granule_id"
              class="cursor-pointer border-t border-border/70 transition hover:bg-muted/50"
              title="跳转到该数据粒详情"
              @click="gotoGranule(g.batch_id, g.granule_id)"
            >
              <td class="px-5 py-2.5 font-mono text-[11.5px]">{{ g.granule_id }}</td>
              <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted-foreground">{{ g.batch_id }}</td>
              <td class="px-2 py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </td>
              <td
                class="px-2 py-2.5 font-mono text-[11.5px] text-muted-foreground"
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
              </td>
              <td class="px-5 py-2.5 text-[11.5px] text-muted-foreground">{{ fmtAge(g.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card v-if="stuckTotal > 0">
      <CardHeader class="flex-row items-start justify-between space-y-0 gap-4">
        <div class="space-y-1.5">
          <CardTitle>卡住的数据粒</CardTitle>
          <CardDescription>非终态且 &gt; {{ stuckHours }} 小时未推进 · 最旧者优先</CardDescription>
        </div>
        <span
          class="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[11px] font-medium text-warning tabular-nums"
        >
          {{ stuckRows.length }} / {{ stuckTotal }}
        </span>
      </CardHeader>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted/50 th-row">
            <tr>
              <th class="px-5 py-2.5">数据粒</th>
              <th class="px-2 py-2.5">批次</th>
              <th class="px-2 py-2.5">状态</th>
              <th class="px-2 py-2.5">领取方</th>
              <th class="px-2 py-2.5">滞留</th>
              <th class="px-5 py-2.5">错误</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="g in stuckRows"
              :key="g.granule_id"
              class="cursor-pointer border-t border-border/70 transition hover:bg-muted/50"
              title="跳转到该数据粒详情"
              @click="gotoGranule(g.batch_id, g.granule_id)"
            >
              <td class="px-5 py-2.5 font-mono text-[11.5px]">{{ g.granule_id }}</td>
              <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted-foreground">{{ g.batch_id }}</td>
              <td class="px-2 py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </td>
              <td
                class="px-2 py-2.5 font-mono text-[11.5px] text-muted-foreground"
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
              </td>
              <td class="px-2 py-2.5 text-[11.5px] text-warning tabular-nums">
                {{ fmtHours(g.age_hours) }}
              </td>
              <td class="max-w-[320px] truncate px-5 py-2.5 font-mono text-[11.5px] text-danger">
                {{ g.error ?? "—" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>最近事件</CardTitle>
        <CardDescription>后台 10 条</CardDescription>
      </CardHeader>
      <div class="divide-y divide-border/60">
        <div
          v-for="e in lastEvents"
          :key="e.id"
          class="flex items-center gap-3 px-5 py-2.5 font-mono text-[11.5px] transition hover:bg-muted/50"
        >
          <span class="w-20 shrink-0 text-muted-foreground">{{ fmtAge(e.ts) }}</span>
          <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
          <span class="w-32 shrink-0 truncate text-muted-foreground">{{ e.source }}</span>
          <span class="flex-1 truncate text-foreground">{{ e.message }}</span>
        </div>
        <EmptyState v-if="lastEvents.length === 0" title="暂无事件" />
      </div>
    </Card>
  </div>
</template>
