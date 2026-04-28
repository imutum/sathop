<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API, type GranuleState } from "../api";
import { fmtAge, levelLabel, stateLabel } from "../i18n";
import Badge from "../ui/Badge.vue";
import Card from "../ui/Card.vue";
import EmptyState from "../ui/EmptyState.vue";
import PageHeader from "../ui/PageHeader.vue";
import Stat from "../ui/Stat.vue";
import NodeStat from "./NodeStat.vue";
import OnboardingCard from "./OnboardingCard.vue";
import { Icon } from "../ui/Icon";

// ECharts is heavy (~1MB). Defer until first render with data — empty/onboarding
// state pays nothing.
const StateBarChart = defineAsyncComponent({
  loader: () => import("./StateBarChart.vue"),
  loadingComponent: {
    template: `<div class="flex h-[280px] items-center justify-center text-xs text-muted"><span class="mr-2">加载图表…</span></div>`,
  },
  delay: 80,
});

const ORDER: GranuleState[] = [
  "pending",
  "queued",
  "downloading",
  "downloaded",
  "processing",
  "processed",
  "uploaded",
  "acked",
  "deleted",
];

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
const inflightTotal = computed(() =>
  ORDER.slice(0, 8).reduce((s, k) => s + (counts.value[k] ?? 0), 0),
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

const hasChartData = computed(() => ORDER.some((s) => (counts.value[s] ?? 0) > 0));

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
      <Card
        title="各阶段数据粒数量"
        description="管线各阶段当前驻留数据粒"
        class-name="lg:col-span-2"
      >
        <div v-if="!hasChartData" class="flex h-56 items-center justify-center">
          <EmptyState title="暂无数据粒" />
        </div>
        <StateBarChart v-else :counts="counts" />
      </Card>

      <Card title="节点" description="集群健康度">
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
      </Card>
    </div>

    <Card title="正在处理" description="近 30 条非终态数据粒" :padded="false">
      <template #action>
        <span class="rounded-full border border-border bg-subtle px-2.5 py-0.5 text-[11px] font-medium text-muted tabular-nums">
          {{ active.length > 0 ? `${active.length} 条` : "空闲" }}
        </span>
      </template>
      <EmptyState
        v-if="active.length === 0"
        title="当前没有正在处理的数据粒"
        description="新建批次后，活动条目会自动出现在这里。"
      />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-subtle/50 th-row">
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
              class="cursor-pointer border-t border-border/70 transition hover:bg-subtle/50"
              title="跳转到该数据粒详情"
              @click="gotoGranule(g.batch_id, g.granule_id)"
            >
              <td class="px-5 py-2.5 font-mono text-[11.5px]">{{ g.granule_id }}</td>
              <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted">{{ g.batch_id }}</td>
              <td class="px-2 py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </td>
              <td
                class="px-2 py-2.5 font-mono text-[11.5px] text-muted"
                @click.stop
              >
                <RouterLink
                  v-if="g.leased_by"
                  :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                  class="transition hover:text-accent"
                  title="跳转到该 worker 卡片"
                >
                  {{ g.leased_by }}
                </RouterLink>
                <template v-else>—</template>
              </td>
              <td class="px-5 py-2.5 text-[11.5px] text-muted">{{ fmtAge(g.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card
      v-if="stuckTotal > 0"
      title="卡住的数据粒"
      :description="`非终态且 > ${stuckHours} 小时未推进 · 最旧者优先`"
      :padded="false"
    >
      <template #action>
        <span
          class="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[11px] font-medium text-warning tabular-nums"
        >
          {{ stuckRows.length }} / {{ stuckTotal }}
        </span>
      </template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-subtle/50 th-row">
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
              class="cursor-pointer border-t border-border/70 transition hover:bg-subtle/50"
              title="跳转到该数据粒详情"
              @click="gotoGranule(g.batch_id, g.granule_id)"
            >
              <td class="px-5 py-2.5 font-mono text-[11.5px]">{{ g.granule_id }}</td>
              <td class="px-2 py-2.5 font-mono text-[11.5px] text-muted">{{ g.batch_id }}</td>
              <td class="px-2 py-2.5">
                <Badge :tone="g.state" dot>{{ stateLabel(g.state) }}</Badge>
              </td>
              <td
                class="px-2 py-2.5 font-mono text-[11.5px] text-muted"
                @click.stop
              >
                <RouterLink
                  v-if="g.leased_by"
                  :to="`/workers?id=${encodeURIComponent(g.leased_by)}`"
                  class="transition hover:text-accent"
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

    <Card title="最近事件" description="后台 10 条" :padded="false">
      <div class="divide-y divide-border/60">
        <div
          v-for="e in lastEvents"
          :key="e.id"
          class="flex items-center gap-3 px-5 py-2.5 font-mono text-[11.5px] transition hover:bg-subtle/50"
        >
          <span class="w-20 shrink-0 text-muted">{{ fmtAge(e.ts) }}</span>
          <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
          <span class="w-32 shrink-0 truncate text-muted">{{ e.source }}</span>
          <span class="flex-1 truncate text-text">{{ e.message }}</span>
        </div>
        <EmptyState v-if="lastEvents.length === 0" title="暂无事件" />
      </div>
    </Card>
  </div>
</template>
