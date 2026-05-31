<script setup lang="ts">
import { computed } from "vue";
import type { GranuleState } from "@/api";
import { stateLabel } from "@/i18n";
import { pipelineSegments, pipelineTotals } from "@/features/batch/pipelineSummary";

// `detailed` adds the per-state legend (the bottleneck locator operators read on
// the batch-detail page). The overview omits it: the 4 rollup chips already carry
// those numbers (待分配 is identical; the rest are this legend summed), so showing
// both there is pure duplication.
const props = defineProps<{ counts: Partial<Record<GranuleState, number>>; detailed?: boolean }>();

// Stage colors stay local because they are presentation-only, not pipeline
// semantics. Each literal hue carries a `dark:` shift one shade lighter so
// the chip text and bar stay readable on the dark slate background (the
// X-600/-700 text shades vanish on dark; X-500 bars look harsh).
const STAGE: Record<GranuleState, { bar: string; chip: string; dot: string }> = {
  pending:     { bar: "bg-muted-foreground/40",                  chip: "text-muted-foreground",                 dot: "bg-muted-foreground" },
  queued:      { bar: "bg-amber-500/70 dark:bg-amber-400/60",    chip: "text-amber-600 dark:text-amber-400",    dot: "bg-amber-500 dark:bg-amber-400" },
  downloading: { bar: "bg-sky-500 dark:bg-sky-400",              chip: "text-sky-600 dark:text-sky-400",        dot: "bg-sky-500 dark:bg-sky-400" },
  downloaded:  { bar: "bg-sky-600 dark:bg-sky-500",              chip: "text-sky-700 dark:text-sky-400",        dot: "bg-sky-600 dark:bg-sky-500" },
  processing:  { bar: "bg-indigo-500 dark:bg-indigo-400",        chip: "text-indigo-600 dark:text-indigo-400",  dot: "bg-indigo-500 dark:bg-indigo-400" },
  processed:   { bar: "bg-indigo-600 dark:bg-indigo-500",        chip: "text-indigo-700 dark:text-indigo-400",  dot: "bg-indigo-600 dark:bg-indigo-500" },
  uploading:   { bar: "bg-violet-500 dark:bg-violet-400",        chip: "text-violet-600 dark:text-violet-400",  dot: "bg-violet-500 dark:bg-violet-400" },
  uploaded:    { bar: "bg-violet-600 dark:bg-violet-500",        chip: "text-violet-700 dark:text-violet-400",  dot: "bg-violet-600 dark:bg-violet-500" },
  acked:       { bar: "bg-success/85",                            chip: "text-success",                          dot: "bg-success" },
  deleted:     { bar: "bg-success",                               chip: "text-success",                          dot: "bg-success" },
  failed:      { bar: "bg-danger",                                chip: "text-danger",                           dot: "bg-danger" },
  blacklisted: { bar: "bg-danger/70",                             chip: "text-danger",                           dot: "bg-danger" },
};

const totals = computed(() => pipelineTotals(props.counts));
const total = computed(() => totals.value.total);
const pending = computed(() => totals.value.pending);
const inFlight = computed(() => totals.value.active);
const done = computed(() => totals.value.done);
const failed = computed(() => totals.value.failed);

const segments = computed(() =>
  pipelineSegments(props.counts).map((seg) => ({
    ...seg,
    label: stateLabel(seg.state),
  })),
);

function pct(n: number): string {
  if (total.value === 0) return "0%";
  return `${Math.round((n / total.value) * 100)}%`;
}

const chips = computed(() => [
  { key: "pending",  label: "待分配", value: pending.value,  tone: "text-muted-foreground",            dot: "bg-muted-foreground",        tip: "orchestrator 还没派给任何 worker 的数据粒" },
  { key: "inflight", label: "进行中", value: inFlight.value, tone: "text-sky-600 dark:text-sky-400",   dot: "bg-sky-500 dark:bg-sky-400", tip: "已 lease 到待交付之间的所有状态合计（含上传中、待分发）；不含已交付" },
  { key: "done",     label: "已交付", value: done.value,     tone: "text-success",                     dot: "bg-success",                 tip: "receiver 已确认（acked）或已清理（deleted）——已交付" },
  { key: "failed",   label: "异常",   value: failed.value,   tone: "text-danger",                      dot: "bg-danger",                  tip: "待重试 + 已拉黑（达到重试上限）的数据粒" },
]);
</script>

<template>
  <div class="space-y-5">
    <div>
      <div class="mb-2 flex items-center justify-between text-xs">
        <span class="text-muted-foreground">阶段分布</span>
        <span class="tabular-nums text-muted-foreground">
          总计 <span class="font-medium text-foreground">{{ total.toLocaleString() }}</span>
        </span>
      </div>
      <div class="flex h-2.5 overflow-hidden rounded-full bg-muted">
        <div
          v-if="total === 0"
          class="h-full w-full bg-muted-foreground/10"
          aria-hidden
        />
        <div
          v-for="seg in segments"
          :key="seg.state"
          :class="['h-full transition-[width] duration-500', STAGE[seg.state].bar]"
          :style="{ width: `${Math.max(seg.pct, 1.5)}%` }"
          :title="`${seg.label} · ${seg.value} (${pct(seg.value)})`"
        />
      </div>
    </div>

    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div
        v-for="c in chips"
        :key="c.key"
        class="rounded-lg border border-border bg-muted/40 px-3 py-2.5"
        :title="c.tip"
      >
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span :class="['h-1.5 w-1.5 rounded-full', c.dot]" aria-hidden />
          {{ c.label }}
        </div>
        <div class="mt-1 flex items-baseline gap-1.5 tabular-nums">
          <span :class="['text-xl font-semibold leading-none', c.tone]">
            {{ c.value.toLocaleString() }}
          </span>
          <span class="text-xs text-muted-foreground">{{ pct(c.value) }}</span>
        </div>
      </div>
    </div>

    <div v-if="detailed && segments.length > 0" class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span
        v-for="seg in segments"
        :key="seg.state"
        :class="['inline-flex items-center gap-1.5 text-xs', STAGE[seg.state].chip]"
      >
        <span :class="['h-2 w-2 rounded-sm', STAGE[seg.state].bar]" aria-hidden />
        <span class="text-muted-foreground">{{ seg.label }}</span>
        <span class="tabular-nums">{{ seg.value }}</span>
      </span>
    </div>
  </div>
</template>
