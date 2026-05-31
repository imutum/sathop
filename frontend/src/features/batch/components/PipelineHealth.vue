<script setup lang="ts">
import { computed } from "vue";
import type { GranuleState } from "@/api";
import { stateLabel } from "@/i18n";
import { pipelineGroups, pipelineSegments, pipelineTotals } from "@/features/batch/pipelineSummary";

// One component, one 口径 — used by both the overview (aggregate state_counts)
// and a batch's 进度 (single-batch counts); only the data scope differs. Three
// big stages (待分配 → 进行中 → 已交付) + 异常, each carrying its small stages in
// processing order. The big-stage number is the sum; the small stages are its
// breakdown (parent→child, intentionally both shown), so nothing is duplicated
// — 待分配 is a leaf, present only as its card.
const props = defineProps<{ counts: Partial<Record<GranuleState, number>> }>();

// Stage colors stay local because they are presentation-only, not pipeline
// semantics. Each literal hue carries a `dark:` shift one shade lighter so
// the text/bar stay readable on the dark slate background.
const STAGE: Record<GranuleState, { bar: string; dot: string }> = {
  pending:     { bar: "bg-muted-foreground/40",               dot: "bg-muted-foreground" },
  queued:      { bar: "bg-amber-500/70 dark:bg-amber-400/60", dot: "bg-amber-500 dark:bg-amber-400" },
  downloading: { bar: "bg-sky-500 dark:bg-sky-400",           dot: "bg-sky-500 dark:bg-sky-400" },
  downloaded:  { bar: "bg-sky-600 dark:bg-sky-500",           dot: "bg-sky-600 dark:bg-sky-500" },
  processing:  { bar: "bg-indigo-500 dark:bg-indigo-400",     dot: "bg-indigo-500 dark:bg-indigo-400" },
  processed:   { bar: "bg-indigo-600 dark:bg-indigo-500",     dot: "bg-indigo-600 dark:bg-indigo-500" },
  uploading:   { bar: "bg-violet-500 dark:bg-violet-400",     dot: "bg-violet-500 dark:bg-violet-400" },
  uploaded:    { bar: "bg-violet-600 dark:bg-violet-500",     dot: "bg-violet-600 dark:bg-violet-500" },
  acked:       { bar: "bg-success/85",                        dot: "bg-success" },
  deleted:     { bar: "bg-success",                           dot: "bg-success" },
  failed:      { bar: "bg-danger",                            dot: "bg-danger" },
  blacklisted: { bar: "bg-danger/70",                         dot: "bg-danger" },
};

// Big-stage header tone + a one-line tip (kept on the card, not the small rows).
const GROUP: Record<string, { num: string; dot: string; tip: string }> = {
  pending: { num: "text-muted-foreground",           dot: "bg-muted-foreground",        tip: "orchestrator 还没派给任何 worker 的数据粒" },
  active:  { num: "text-sky-600 dark:text-sky-400",  dot: "bg-sky-500 dark:bg-sky-400", tip: "已 lease 到待交付之间的所有状态（含待分发：已上传待 receiver 拉取）；不含已交付" },
  done:    { num: "text-success",                    dot: "bg-success",                 tip: "receiver 已确认（待清理）或已清理（已完成）——已交付" },
  failed:  { num: "text-danger",                     dot: "bg-danger",                  tip: "待重试 + 已拉黑（达到重试上限）" },
};

const total = computed(() => pipelineTotals(props.counts).total);
const groups = computed(() => pipelineGroups(props.counts));
const segments = computed(() =>
  pipelineSegments(props.counts).map((seg) => ({ ...seg, label: stateLabel(seg.state) })),
);

function pct(n: number): string {
  if (total.value === 0) return "0%";
  return `${Math.round((n / total.value) * 100)}%`;
}
</script>

<template>
  <div class="space-y-5">
    <!-- 顶部：阶段分布条形图（全处理顺序，仅非零段） -->
    <div>
      <div class="mb-2 flex items-center justify-between text-xs">
        <span class="text-muted-foreground">阶段分布</span>
        <span class="tabular-nums text-muted-foreground">
          总计 <span class="font-medium text-foreground">{{ total.toLocaleString() }}</span>
        </span>
      </div>
      <div class="flex h-2.5 overflow-hidden rounded-full bg-muted">
        <div v-if="total === 0" class="h-full w-full bg-muted-foreground/10" aria-hidden />
        <div
          v-for="seg in segments"
          :key="seg.state"
          :class="['h-full transition-[width] duration-500', STAGE[seg.state].bar]"
          :style="{ width: `${Math.max(seg.pct, 1.5)}%` }"
          :title="`${seg.label} · ${seg.value} (${pct(seg.value)})`"
        />
      </div>
    </div>

    <!-- 分级：大阶段卡片 + 其小阶段。窄屏竖向堆叠，宽屏 4 列。 -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div
        v-for="g in groups"
        :key="g.key"
        class="rounded-lg border border-border bg-muted/40 px-3 py-2.5"
      >
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground" :title="GROUP[g.key].tip">
          <span :class="['h-1.5 w-1.5 rounded-full', GROUP[g.key].dot]" aria-hidden />
          {{ g.label }}
        </div>
        <div class="mt-1 flex items-baseline gap-1.5 tabular-nums">
          <span :class="['text-xl font-semibold leading-none', GROUP[g.key].num]">
            {{ g.total.toLocaleString() }}
          </span>
          <span class="text-xs text-muted-foreground">{{ pct(g.total) }}</span>
        </div>
        <!-- 小阶段：按处理顺序，count=0 也显示（位置稳定）；待分配为叶子无子项 -->
        <div v-if="g.subs.length" class="mt-2.5 space-y-1 border-t border-border/50 pt-2">
          <div
            v-for="sub in g.subs"
            :key="sub.state"
            class="flex items-center justify-between gap-2 text-2xs"
          >
            <span class="inline-flex items-center gap-1.5 text-muted-foreground">
              <span :class="['h-1.5 w-1.5 rounded-sm', STAGE[sub.state].dot]" aria-hidden />
              {{ stateLabel(sub.state) }}
            </span>
            <span :class="['tabular-nums', sub.value ? 'text-foreground' : 'text-muted-foreground/40']">
              {{ sub.value.toLocaleString() }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
