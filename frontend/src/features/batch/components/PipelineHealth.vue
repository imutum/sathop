<script setup lang="ts">
import { computed } from "vue";
import { STATE_ORDER, type GranuleState } from "@/api";
import { stateLabel } from "@/i18n";

// Pipeline health visualization: a single horizontal stacked bar showing
// where each granule currently sits in the pipeline, plus a 4-cell summary
// strip (已清理 / 处理中 / 待处理 / 异常). Stage tints are constrained —
// neutral for waiting, sky for in-flight, success for done, danger for
// errored — so the eye can read distribution at a glance.
const props = defineProps<{ counts: Partial<Record<GranuleState, number>> }>();

// Stage tint palette. The granule pipeline has 11 named states, so we
// allow Tailwind palette colors here (sky/amber/violet) — they're the
// only way to give each state a distinguishable hue. This palette is
// quarantined to PipelineHealth; everything else stays on tokens.
const STAGE: Record<GranuleState, { bar: string; chip: string; dot: string }> = {
  pending:     { bar: "bg-muted-foreground/40", chip: "text-muted-foreground", dot: "bg-muted-foreground" },
  queued:      { bar: "bg-amber-500/70",        chip: "text-amber-600",        dot: "bg-amber-500" },
  downloading: { bar: "bg-sky-500",             chip: "text-sky-600",          dot: "bg-sky-500" },
  downloaded:  { bar: "bg-sky-600",             chip: "text-sky-700",          dot: "bg-sky-600" },
  processing:  { bar: "bg-indigo-500",          chip: "text-indigo-600",       dot: "bg-indigo-500" },
  processed:   { bar: "bg-indigo-600",          chip: "text-indigo-700",       dot: "bg-indigo-600" },
  uploaded:    { bar: "bg-violet-500",          chip: "text-violet-600",       dot: "bg-violet-500" },
  acked:       { bar: "bg-success/85",          chip: "text-success",          dot: "bg-success" },
  deleted:     { bar: "bg-success",             chip: "text-success",          dot: "bg-success" },
  failed:      { bar: "bg-danger",              chip: "text-danger",           dot: "bg-danger" },
  blacklisted: { bar: "bg-danger/70",           chip: "text-danger",           dot: "bg-danger" },
};

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const PENDING: GranuleState[] = ["pending", "queued"];
const FAILED: GranuleState[] = ["failed", "blacklisted"];

const total = computed(() =>
  STATE_ORDER.reduce((s, k) => s + (props.counts[k] ?? 0), 0),
);
const cleared = computed(() => TERMINAL.reduce((s, k) => s + (props.counts[k] ?? 0), 0));
const pending = computed(() => PENDING.reduce((s, k) => s + (props.counts[k] ?? 0), 0));
const failed = computed(() => FAILED.reduce((s, k) => s + (props.counts[k] ?? 0), 0));
const inFlight = computed(() => total.value - cleared.value - pending.value - failed.value);

const segments = computed(() =>
  STATE_ORDER.filter((s) => (props.counts[s] ?? 0) > 0).map((s) => ({
    state: s,
    label: stateLabel(s),
    value: props.counts[s] ?? 0,
    pct: total.value > 0 ? ((props.counts[s] ?? 0) / total.value) * 100 : 0,
  })),
);

function pct(n: number): string {
  if (total.value === 0) return "0%";
  return `${Math.round((n / total.value) * 100)}%`;
}

const chips = computed(() => [
  { key: "cleared",  label: "已清理", value: cleared.value,  tone: "text-success",          dot: "bg-success",          tip: "管线终态：已 ack 或已清理的数据粒数量" },
  { key: "inflight", label: "处理中", value: inFlight.value, tone: "text-sky-600",          dot: "bg-sky-500",          tip: "正在下载 / 处理 / 上传中的数据粒" },
  { key: "pending",  label: "待处理", value: pending.value,  tone: "text-amber-600",        dot: "bg-amber-500",        tip: "尚未被 worker 领取的数据粒" },
  { key: "failed",   label: "异常",   value: failed.value,   tone: "text-danger",           dot: "bg-danger",           tip: "失败 + 已拉黑（达到重试上限）的数据粒" },
]);
</script>

<template>
  <div class="space-y-5">
    <!-- Stacked segment bar — one slice per non-zero stage, tinted per
         STAGE map. Hover-tooltips on each slice expose the state name. -->
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

    <!-- 4-chip summary — terminal / inflight / pending / failed buckets,
         each labeled in Chinese with a percentage of total. -->
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

    <!-- Per-stage legend — only states with count > 0 appear, sorted by
         pipeline order so the eye reads the journey left → right. -->
    <div v-if="segments.length > 0" class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
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
