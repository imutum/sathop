<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API, type TimingStage } from "@/api";
import { TIMING_STAGE_ZH, fmtDuration, fmtMs, fmtPerMinute } from "@/i18n";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Field from "@/components/Field.vue";

const props = defineProps<{ batchId: string; remaining: number; etaSeconds: number | null }>();

const STAGE_ORDER: TimingStage[] = ["download", "process", "upload"];

const q = useQuery({
  queryKey: computed(() => ["batch-timing", props.batchId]),
  queryFn: () => API.batchTiming(props.batchId),
  enabled: computed(() => !!props.batchId),
});

const data = computed(() => q.data.value);
const doneCount = computed(() => data.value?.stages.upload.count ?? 0);
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>耗时统计</CardTitle>
      <CardDescription>样本数 = 闭合阶段次数（同一数据粒重试会计入多次）。失败未闭合的阶段不计入。</CardDescription>
    </CardHeader>
    <div v-if="q.isLoading.value" class="px-6 py-4 text-xs text-muted-foreground">加载中…</div>
    <template v-if="data">
      <div
        v-if="data.wall_ms > 0"
        class="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-border/60 px-5 py-4 sm:grid-cols-4"
      >
        <Field label="总耗时（端到端）" hint="wall clock">
          <span class="tabular-nums">{{ fmtDuration(data.wall_ms) }}</span>
        </Field>
        <Field label="完成数据粒">
          <span class="tabular-nums">{{ doneCount }}</span>
        </Field>
        <Field label="平均吞吐">
          <span class="tabular-nums">{{ fmtPerMinute(doneCount, data.wall_ms) }}</span>
        </Field>
        <Field
          v-if="etaSeconds != null"
          :label="`预计剩余 (${remaining} 条)`"
          hint="按当前吞吐外推"
        >
          <span class="tabular-nums">≈ {{ fmtDuration(etaSeconds * 1000) }}</span>
        </Field>
      </div>
      <Table>
        <TableHeader class="bg-muted/50">
          <TableRow>
            <TableHead class="px-5">阶段</TableHead>
            <TableHead class="text-right">样本数</TableHead>
            <TableHead class="text-right">平均</TableHead>
            <TableHead class="text-right">P50</TableHead>
            <TableHead class="text-right">P95</TableHead>
            <TableHead class="px-5 text-right">最大</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="st in STAGE_ORDER"
            :key="st"
            :class="data.stages[st].count === 0 ? 'text-muted-foreground' : ''"
          >
            <TableCell class="px-5">{{ TIMING_STAGE_ZH[st] }}</TableCell>
            <TableCell class="text-right tabular-nums">{{ data.stages[st].count }}</TableCell>
            <TableCell class="text-right tabular-nums">
              {{ data.stages[st].count === 0 ? "—" : fmtMs(data.stages[st].avg_ms) }}
            </TableCell>
            <TableCell class="text-right tabular-nums">
              {{ data.stages[st].count === 0 ? "—" : fmtMs(data.stages[st].p50_ms) }}
            </TableCell>
            <TableCell class="text-right tabular-nums">
              {{ data.stages[st].count === 0 ? "—" : fmtMs(data.stages[st].p95_ms) }}
            </TableCell>
            <TableCell class="px-5 text-right tabular-nums">
              {{ data.stages[st].count === 0 ? "—" : fmtMs(data.stages[st].max_ms) }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </template>
  </Card>
</template>
