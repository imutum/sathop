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
const props = defineProps<{ counts: Partial<Record<GranuleState, number>>; overview?: boolean }>();

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
const GROUP: Record<string, { dot: string; tip: string }> = {
  pending: { dot: "bg-muted-foreground", tip: "尚未分配给工作节点的数据粒" },
  active:  { dot: "bg-sky-500 dark:bg-sky-400", tip: "已分配给工作节点，尚未确认交付的数据粒" },
  done:    { dot: "bg-success", tip: "接收端已确认交付，包括待清理和已完成的数据粒" },
  failed:  { dot: "bg-danger", tip: "等待重试或已停止的数据粒；已停止包括重试耗尽和主动取消" },
};

const totals = computed(() => pipelineTotals(props.counts));
const total = computed(() => totals.value.total);
const deliveredPct = computed(() => total.value ? (totals.value.done / total.value) * 100 : 0);
const groups = computed(() => pipelineGroups(props.counts));
const detailedGroups = computed(() => groups.value.filter((group) => group.subs.length));
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
    <div v-if="!overview">
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

    <!-- Keep totals visible; expand the detailed stages when needed. -->
    <div :class="overview ? 'grid items-center gap-6 sm:grid-cols-[156px_minmax(0,1fr)]' : ''">
      <div v-if="overview" class="relative mx-auto grid h-[156px] w-[156px] place-items-center">
        <svg viewBox="0 0 160 160" class="absolute inset-0 h-full w-full -rotate-90" role="img" :aria-label="`交付比例 ${pct(totals.done)}，${totals.done} / ${total} 个数据粒`">
          <circle cx="80" cy="80" r="70" fill="none" stroke="currentColor" stroke-width="7" class="text-primary/10" />
          <circle v-if="deliveredPct > 0" cx="80" cy="80" r="70" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" pathLength="100" :stroke-dasharray="`${deliveredPct} 100`" class="text-primary" />
          <circle cx="80" cy="80" r="58" fill="none" stroke="currentColor" stroke-width="0.5" class="text-primary/15" />
        </svg>
        <div class="text-center">
          <div class="text-[34px] font-semibold leading-none tracking-tight tabular-nums">{{ pct(totals.done) }}</div>
          <div class="mt-2 text-xs text-muted-foreground">交付比例</div>
          <div class="mt-1 text-[11px] text-muted-foreground">共 {{ total.toLocaleString() }} 个数据粒</div>
        </div>
      </div>
    <div :class="overview ? 'grid grid-cols-2 gap-x-5 gap-y-6' : 'grid grid-cols-2 gap-3 sm:grid-cols-4'">
      <div
        v-for="g in groups"
        :key="g.key"
        :class="overview ? 'border-l border-border/70 pl-4' : 'rounded-xl bg-muted/55 px-4 py-4'"
      >
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground" :title="GROUP[g.key].tip">
          <span :class="['h-1.5 w-1.5 rounded-full', GROUP[g.key].dot]" aria-hidden />
          {{ g.label }}
        </div>
        <div class="mt-3 flex flex-wrap items-baseline gap-2 tabular-nums">
          <span class="text-[28px] font-semibold leading-none tracking-tight text-foreground">
            {{ g.total.toLocaleString() }}
          </span>
          <span class="text-xs text-muted-foreground">{{ pct(g.total) }}</span>
        </div>
      </div>
    </div>
    </div>
    <details class="border-t border-border/70 pt-4">
      <summary class="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">阶段明细</summary>
      <div class="mt-4 grid gap-5 sm:grid-cols-3">
        <div v-for="g in detailedGroups" :key="g.key" class="space-y-2">
          <div class="mb-3 text-xs font-medium text-foreground">{{ g.label }}</div>
          <div
            v-for="sub in g.subs"
            :key="sub.state"
            class="flex items-center justify-between gap-2 text-xs"
          >
            <span class="inline-flex items-center gap-1.5 text-muted-foreground">
              <span :class="['h-1.5 w-1.5 rounded-sm', STAGE[sub.state].dot]" aria-hidden />
              {{ stateLabel(sub.state) }}
            </span>
            <span :class="['tabular-nums', sub.value ? 'text-foreground' : 'text-muted-foreground']">
              {{ sub.value.toLocaleString() }}
            </span>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>
