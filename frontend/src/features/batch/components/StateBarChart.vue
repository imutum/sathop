<script setup lang="ts">
import { computed } from "vue";
import { STATE_ORDER, type GranuleState } from "@/api";
import { stateLabel } from "@/i18n";

const props = defineProps<{ counts: Partial<Record<GranuleState, number>> }>();

const TONE: Record<GranuleState, string> = {
  pending: "bg-legacy-muted",
  queued: "bg-amber-500",
  downloading: "bg-sky-500",
  downloaded: "bg-sky-600",
  processing: "bg-indigo-500",
  processed: "bg-indigo-600",
  uploaded: "bg-violet-500",
  acked: "bg-success",
  deleted: "bg-success",
  failed: "bg-danger",
  blacklisted: "bg-danger",
};

const rows = computed(() => {
  const visible = STATE_ORDER.map((state) => ({
    state,
    label: stateLabel(state),
    value: props.counts[state] ?? 0,
  })).filter((row) => row.value > 0);
  const max = Math.max(...visible.map((row) => row.value), 1);
  return visible.reverse().map((row) => ({
    ...row,
    pct: Math.max((row.value / max) * 100, 3),
  }));
});
</script>

<template>
  <div class="h-[280px] space-y-3 py-2">
    <div
      v-for="row in rows"
      :key="row.state"
      class="grid grid-cols-[74px_minmax(0,1fr)_54px] items-center gap-3"
    >
      <div class="truncate text-xs text-legacy-muted">{{ row.label }}</div>
      <div class="h-7 rounded-md bg-legacy-subtle">
        <div
          :class="['h-full rounded-md transition-[width]', TONE[row.state]]"
          :style="{ width: `${row.pct}%` }"
        />
      </div>
      <div class="text-right font-mono text-xs tabular-nums text-legacy-text">
        {{ row.value.toLocaleString() }}
      </div>
    </div>
  </div>
</template>
