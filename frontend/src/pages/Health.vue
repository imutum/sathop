<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { fmtAge, stateLabel } from "@/i18n";
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

// 诊断页：承接从总览降级的三块原始信号——在途明细、卡住明细、近期事件。
// 总览只留决策层（管道健康 / 节点 / 活跃批次）；运维要查"哪一粒卡在哪"来这里。
// 沿用「呈现原始数字、不内置阈值判定」的取向：表格摆清，判断交给人。
const router = useRouter();

const overview = useQuery({ queryKey: [...K.overview], queryFn: API.overview });
const inflight = useQuery({ queryKey: [...K.inflight], queryFn: () => API.inFlight(50) });
const stuckList = useQuery({
  queryKey: [...K.stuck],
  queryFn: () => API.stuck(50),
  // 昂贵全扫，仅在总览汇总显示存在卡住时才拉，避免无谓扫描。
  enabled: computed(
    () =>
      Object.values(overview.data.value?.stuck_by_state ?? {}).reduce((a, b) => a + (b ?? 0), 0) > 0,
  ),
});

const active = computed(() => inflight.data.value ?? []);
const stuckRows = computed(() => stuckList.data.value ?? []);
const stuckTotal = computed(() =>
  Object.values(overview.data.value?.stuck_by_state ?? {}).reduce((a, b) => a + (b ?? 0), 0),
);
const stuckHours = computed(() => overview.data.value?.stuck_over_hours ?? 6);
const lastEvents = computed(() => overview.data.value?.last_events ?? []);

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
    <PageHeader
      title="健康诊断"
      description="管道在途与异常的逐粒明细 · 原始数字呈现，卡点由你判断"
    />

    <CardSection
      title="正在处理"
      description="近 50 条非终态数据粒"
      :padded="false"
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
            <TableCell class="py-2.5 font-mono text-cell text-muted-foreground" @click.stop>
              <WorkerRef :worker-id="g.leased_by" />
            </TableCell>
            <TableCell class="px-5 py-2.5 text-cell text-muted-foreground">{{ fmtAge(g.updated_at) }}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardSection>

    <CardSection
      title="卡住的数据粒"
      :description="`非终态且 > ${stuckHours} 小时未推进 · 最旧者优先`"
      :padded="false"
      :class="stuckTotal > 0 ? 'border-warning/40' : ''"
    >
      <template #meta>
        <HintTip text="数据粒在非终态停留过久，多半是 worker 失联、下载卡死或脚本无响应。点击行查看其事件日志。">
          <Badge v-if="stuckTotal > 0" variant="warning" class="tabular-nums">{{ stuckRows.length }} / {{ stuckTotal }}</Badge>
          <Badge v-else variant="outline" class="text-muted-foreground">无</Badge>
        </HintTip>
      </template>
      <EmptyState
        v-if="stuckTotal === 0"
        :title="`没有超过 ${stuckHours} 小时未推进的数据粒`"
        description="管道流转正常"
        illustration="signal"
      />
      <Table v-else>
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
            <TableCell class="py-2.5 font-mono text-cell text-muted-foreground" @click.stop>
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

    <CardSection title="最近事件" description="最新 10 条" :padded="false">
      <template #meta>
        <Button as-child variant="ghost" size="xs" class="text-muted-foreground hover:text-foreground">
          <RouterLink to="/events">查看全部</RouterLink>
        </Button>
      </template>
      <EmptyState v-if="lastEvents.length === 0" title="暂无事件" illustration="inbox" />
      <EventTimeline v-else :events="lastEvents" />
    </CardSection>
  </div>
</template>
