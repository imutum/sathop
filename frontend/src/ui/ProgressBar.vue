<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    value: number;
    max: number;
    tone?: "accent" | "good" | "warn" | "bad";
  }>(),
  { tone: "accent" },
);

const pct = computed(() =>
  props.max > 0 ? Math.min(100, (props.value / props.max) * 100) : 0,
);

const color = computed(
  () =>
    ({
      accent: "bg-legacy-accent",
      good: "bg-success",
      warn: "bg-warning",
      bad: "bg-danger",
    })[props.tone],
);
</script>

<template>
  <div class="h-1.5 w-full overflow-hidden rounded-full bg-legacy-subtle">
    <div
      :class="['h-full transition-[width] duration-500 ease-out', color]"
      :style="{ width: `${pct}%` }"
    />
  </div>
</template>
