<script setup lang="ts">
import { computed } from "vue";
import { STATE_ORDER, type GranuleState } from "@/api";
import { stateLabel } from "@/i18n";

// Pipeline health bar: a stacked horizontal segment that mirrors the
// granule-state journey left → right (pending → cleared), with mono numerals
// underneath as a gauge strip. The bar is *the* dataviz on the dashboard —
// kept clean: thin baseline rule, no gradients, distinct stage tints.
const props = defineProps<{ counts: Partial<Record<GranuleState, number>> }>();

// Bar segment palette — stage-aware, but constrained: warm for pending side,
// cool for in-flight, signature amber for processing, success green for done.
const STAGE: Record<GranuleState, { bar: string; chip: string }> = {
  pending:     { bar: "bg-muted-foreground/40",  chip: "text-muted-foreground" },
  queued:      { bar: "bg-amber-400/70",         chip: "text-amber-600" },
  downloading: { bar: "bg-sky-500/85",           chip: "text-sky-600" },
  downloaded:  { bar: "bg-sky-700/85",           chip: "text-sky-700" },
  processing:  { bar: "bg-primary",              chip: "text-primary" },
  processed:   { bar: "bg-primary/80",           chip: "text-primary" },
  uploaded:    { bar: "bg-violet-500/85",        chip: "text-violet-600" },
  acked:       { bar: "bg-success/85",           chip: "text-success" },
  deleted:     { bar: "bg-success",              chip: "text-success" },
  failed:      { bar: "bg-danger",               chip: "text-danger" },
  blacklisted: { bar: "bg-danger/70",            chip: "text-danger" },
};

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const PENDING: GranuleState[] = ["pending", "queued"];
const FAILED: GranuleState[] = ["failed", "blacklisted"];

const total = computed(() =>
  STATE_ORDER.reduce((s, k) => s + (props.counts[k] ?? 0), 0),
);
const cleared = computed(() =>
  TERMINAL.reduce((s, k) => s + (props.counts[k] ?? 0), 0),
);
const pending = computed(() =>
  PENDING.reduce((s, k) => s + (props.counts[k] ?? 0), 0),
);
const failed = computed(() =>
  FAILED.reduce((s, k) => s + (props.counts[k] ?? 0), 0),
);
const inFlight = computed(() =>
  total.value - cleared.value - pending.value - failed.value,
);

// Visible segments — only stages with count > 0 contribute, in pipeline order.
const segments = computed(() =>
  STATE_ORDER.filter((s) => (props.counts[s] ?? 0) > 0).map((s) => ({
    state: s,
    label: stateLabel(s),
    value: props.counts[s] ?? 0,
    pct: total.value > 0 ? ((props.counts[s] ?? 0) / total.value) * 100 : 0,
  })),
);

function pctOf(n: number): string {
  if (total.value === 0) return "0%";
  return `${Math.round((n / total.value) * 100)}%`;
}

const chips = computed(() => [
  { key: "cleared",  label: "已清理", value: cleared.value,  tone: "text-success",          dot: "bg-success" },
  { key: "inflight", label: "处理中", value: inFlight.value, tone: "text-primary",          dot: "bg-primary" },
  { key: "pending",  label: "待处理", value: pending.value,  tone: "text-amber-600",        dot: "bg-amber-500" },
  { key: "failed",   label: "异常",   value: failed.value,   tone: "text-danger",           dot: "bg-danger" },
]);
</script>

<template>
  <div class="space-y-5">
    <!-- Stacked bar — tick marks above show 0/25/50/75/100 % anchors. -->
    <div>
      <div class="mb-2 flex items-center justify-between text-3xs text-muted-foreground readout">
        <span class="uppercase tracking-section">PIPELINE · DISTRIBUTION</span>
        <span class="tabular-nums">
          <span class="text-foreground">{{ total.toLocaleString() }}</span>
          <span class="text-muted-foreground/70"> · TOTAL</span>
        </span>
      </div>
      <div class="relative">
        <!-- Tick rail above the bar. -->
        <div class="absolute -top-1 left-0 right-0 flex justify-between text-3xs text-muted-foreground/60 readout">
          <span aria-hidden>│</span>
          <span aria-hidden>│</span>
          <span aria-hidden>│</span>
          <span aria-hidden>│</span>
          <span aria-hidden>│</span>
        </div>
        <div class="mt-3 flex h-2.5 overflow-hidden rounded-sm bg-muted ring-1 ring-inset ring-border">
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
            :title="`${seg.label} · ${seg.value} (${pctOf(seg.value)})`"
          />
        </div>
        <!-- 0% / 100% anchor labels. -->
        <div class="mt-1.5 flex justify-between text-3xs text-muted-foreground/60 readout">
          <span>0</span>
          <span>25</span>
          <span>50</span>
          <span>75</span>
          <span>100</span>
        </div>
      </div>
    </div>

    <!-- Chip strip — mono numerals, hairline divider, narrative dot. -->
    <div class="grid grid-cols-2 gap-px overflow-hidden rounded-sm border border-border bg-border sm:grid-cols-4">
      <div
        v-for="c in chips"
        :key="c.key"
        class="bg-card px-3 py-3"
      >
        <div class="flex items-center gap-1.5 text-3xs uppercase tracking-section text-muted-foreground readout">
          <span :class="['h-1 w-1 rounded-full', c.dot]" aria-hidden />
          {{ c.label }}
        </div>
        <div class="mt-1.5 flex items-baseline gap-1.5 tabular-nums">
          <span :class="['font-display text-[22px] font-medium leading-none tracking-tight', c.tone]">
            {{ c.value.toLocaleString() }}
          </span>
          <span class="readout text-3xs text-muted-foreground">{{ pctOf(c.value) }}</span>
        </div>
      </div>
    </div>

    <!-- Stage legend — compact, mono. Only stages present. -->
    <div v-if="segments.length > 0" class="flex flex-wrap items-center gap-x-4 gap-y-1.5 readout">
      <span
        v-for="seg in segments"
        :key="seg.state"
        :class="['inline-flex items-center gap-1.5 text-3xs', STAGE[seg.state].chip]"
      >
        <span :class="['h-2 w-2 rounded-sm', STAGE[seg.state].bar]" aria-hidden />
        <span class="text-muted-foreground">{{ seg.label }}</span>
        <span class="tabular-nums">{{ seg.value }}</span>
      </span>
    </div>
  </div>
</template>
