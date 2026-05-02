<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    /** Two-digit ordinal — e.g. "01", "02". Auto-pads single digits. */
    n?: string | number;
    /** Section name; rendered uppercase, wide-tracked. */
    label: string;
    /** Optional small caption rendered after the label, en-dash separated. */
    caption?: string;
    /** Variant — `quiet` is just the section number + label (default);
        `live` adds a breathing signal LED at the start. */
    variant?: "quiet" | "live";
    /** Render as `<h2>` instead of `<div>` when used as a real heading. */
    as?: "div" | "h2" | "h3";
  }>(),
  { variant: "quiet", as: "div" },
);

const ord = computed(() => {
  if (props.n === undefined || props.n === null || props.n === "") return null;
  const s = String(props.n);
  return s.length === 1 ? `0${s}` : s;
});
</script>

<template>
  <component
    :is="as"
    class="flex items-center gap-2 text-mini font-medium uppercase tracking-section text-muted-foreground"
  >
    <span v-if="variant === 'live'" class="signal-led" aria-hidden />
    <span
      v-if="ord"
      class="readout text-3xs font-semibold text-primary/80"
      aria-hidden
    >
      §&nbsp;{{ ord }}
    </span>
    <span class="text-foreground/70">{{ label }}</span>
    <template v-if="caption">
      <span aria-hidden class="text-muted-foreground/60">—</span>
      <span class="font-normal normal-case tracking-normal text-muted-foreground">
        {{ caption }}
      </span>
    </template>
  </component>
</template>
