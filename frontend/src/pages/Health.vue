<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { fmtAge, stateLabel } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import QueryState from "@/components/QueryState.vue";

const router = useRouter();

const overview = useQuery({ queryKey: [...K.overview], queryFn: API.overview });
const inflight = useQuery({ queryKey: [...K.inflight], queryFn: () => API.inFlight(50) });
const stuckTotal = computed(() =>
  Object.values(overview.data.value?.stuck_by_state ?? {}).reduce((sum, count) => sum + (count ?? 0), 0),
);
const stuckList = useQuery({
  queryKey: [...K.stuck],
  queryFn: () => API.stuck(50),
  // 昂贵全扫，仅在总览汇总显示存在卡住时才拉，避免无谓扫描。
  enabled: computed(() => stuckTotal.value > 0),
});

const active = computed(() => inflight.data.value ?? []);
const stuckRows = computed(() => stuckList.data.value ?? []);
const stuckHours = computed(() => overview.data.value?.stuck_over_hours ?? 6);
const lastEvents = computed(() => overview.data.value?.last_events ?? []);
const showingStaleData = computed(() =>
  [overview, inflight, stuckList].some((query) => query.error.value && query.data.value !== undefined),
);

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
      description="查看处理中的数据粒、进度超时与近期事件"
    />
    <Alert v-if="showingStaleData">
      <AlertDescription>部分信息刷新失败，以下保留上次结果，请稍后刷新。</AlertDescription>
    </Alert>

    <CardSection
      title="正在处理"
      description="最近 50 条活动数据粒"
      :padded="false"
    >
      <template #meta>
        <Badge v-if="active.length > 0" variant="info" class="tabular-nums">{{ active.length }} 条</Badge>
        <Badge v-else-if="inflight.isSuccess.value" variant="outline" class="text-muted-foreground">空闲</Badge>
      </template>
      <QueryState :query="inflight">
        <template #loading>
          <p role="status" class="p-5 text-sm text-muted-foreground">正在加载处理明细…</p>
        </template>
        <template #error="{ retry }">
          <Alert variant="destructive">
            <AlertDescription class="flex items-center justify-between gap-3">
              <span>处理明细加载失败</span>
              <Button size="sm" variant="outline" @click="retry">重试</Button>
            </AlertDescription>
          </Alert>
        </template>
        <template #empty>
          <EmptyState
            title="当前没有正在处理的数据粒"
            description="任务开始处理后，可在此查看明细。"
            illustration="signal"
          />
        </template>
        <template #default>
          <Table>
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
        </template>
      </QueryState>
    </CardSection>

    <QueryState :query="overview">
      <template #loading>
        <p role="status" class="py-5 text-sm text-muted-foreground">正在加载诊断信息…</p>
      </template>
      <template #error="{ retry }">
        <Alert variant="destructive">
          <AlertDescription class="flex items-center justify-between gap-3">
            <span>诊断信息加载失败，暂时无法确认超时情况</span>
            <Button size="sm" variant="outline" @click="retry">重试</Button>
          </AlertDescription>
        </Alert>
      </template>
      <template #default>
        <CardSection
          title="进度超时"
          :description="`超过 ${stuckHours} 小时未推进，按滞留时间排序`"
          :padded="false"
          :class="stuckTotal > 0 ? 'border-warning/40' : ''"
        >
          <template #meta>
            <HintTip text="请结合节点状态、下载进度与事件日志排查原因。">
              <Badge v-if="stuckTotal > 0" variant="warning" class="tabular-nums">{{ stuckRows.length }} / {{ stuckTotal }}</Badge>
              <Badge v-else variant="outline" class="text-muted-foreground">无</Badge>
            </HintTip>
          </template>
          <EmptyState
            v-if="stuckTotal === 0"
            :title="`没有超过 ${stuckHours} 小时未推进的数据粒`"
            description="当前未发现超过设定阈值的活动数据粒。"
            illustration="signal"
          />
          <QueryState v-else :query="stuckList">
            <template #loading>
              <p role="status" class="p-5 text-sm text-muted-foreground">正在加载超时明细…</p>
            </template>
            <template #error="{ retry }">
              <Alert variant="destructive">
                <AlertDescription class="flex items-center justify-between gap-3">
                  <span>超时明细加载失败</span>
                  <Button size="sm" variant="outline" @click="retry">重试</Button>
                </AlertDescription>
              </Alert>
            </template>
            <template #empty>
              <EmptyState title="暂无超时明细" description="汇总与明细可能存在短暂更新间隔，请稍后查看。" />
            </template>
            <template #default>
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
            </template>
          </QueryState>
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
      </template>
    </QueryState>
  </div>
</template>
