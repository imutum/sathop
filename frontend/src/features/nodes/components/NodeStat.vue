<script setup lang="ts">
import { computed } from "vue";
import Crosshair from "@/components/chrome/Crosshair.vue";

// Node tile — fleet-aware: shows online/total ratio + status chip with the
// signature LED. Mono numerals throughout for instrument legibility.
const props = defineProps<{
  label: string;
  value: number;
  total: number;
  caption?: string;
}>();
defineEmits<{ click: [] }>();

type Tone = "muted" | "success" | "warning" | "danger";

const tone = computed<Tone>(() => {
  if (props.total === 0) return "muted";
  const ratio = props.value / props.total;
  if (ratio === 1) return "success";
  if (ratio >= 0.5) return "warning";
  return "danger";
});

const valueCls = computed(
  () =>
    ({
      muted: "text-muted-foreground",
      success: "text-success",
      warning: "text-warning",
      danger: "text-danger",
    })[tone.value],
);

const ledCls = computed(
  () =>
    ({
      muted: "bg-muted-foreground/40",
      success: "bg-success",
      warning: "bg-warning",
      danger: "bg-danger",
    })[tone.value],
);

const statusLabel = computed(
  () =>
    ({
      muted: "STANDBY",
      success: "NOMINAL",
      warning: "DEGRADED",
      danger: "ANOMALY",
    })[tone.value],
);

const statusCls = computed(
  () =>
    ({
      muted: "text-muted-foreground border-border",
      success: "text-success border-success/40",
      warning: "text-warning border-warning/40",
      danger: "text-danger border-danger/40",
    })[tone.value],
);
</script>

<template>
  <button
    type="button"
    @click="$emit('click')"
    class="group relative flex w-full items-center justify-between gap-4 overflow-hidden rounded-md border border-border bg-card p-4 text-left transition hover:border-primary/40 hover:shadow-glow"
  >
    <Crosshair tone="muted" :inset="5" :size="8" />

    <div class="relative flex min-w-0 items-center gap-3">
      <span
        class="grid h-10 w-10 shrink-0 place-items-center rounded-md border border-border bg-background text-foreground/80 transition group-hover:border-primary/40 group-hover:text-primary"
        aria-hidden
      >
        <slot name="icon" />
      </span>
      <div class="min-w-0">
        <div class="truncate text-[13px] font-medium text-foreground">{{ label }}</div>
        <div class="readout mt-0.5 text-2xs text-muted-foreground">
          {{ caption ?? "ONLINE / REGISTERED" }}
        </div>
      </div>
    </div>

    <div class="relative flex shrink-0 flex-col items-end gap-2">
      <div class="flex items-baseline gap-1">
        <span :class="['font-display text-[26px] font-medium leading-none tracking-tight', valueCls]">
          {{ value }}
        </span>
        <span class="readout text-sm text-muted-foreground">/{{ total }}</span>
      </div>
      <span
        :class="['inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-section readout', statusCls]"
      >
        <span :class="['h-1 w-1 rounded-full', ledCls]" aria-hidden />
        {{ statusLabel }}
      </span>
    </div>
  </button>
</template>
