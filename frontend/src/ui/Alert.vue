<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ tone?: "danger" | "warn" | "info" }>(),
  { tone: "danger" },
);

const cls = computed(
  () =>
    ({
      danger: "border-danger/30 bg-danger/10 text-danger",
      warn: "border-warning/30 bg-warning/10 text-warning",
      info: "border-border bg-legacy-subtle text-legacy-text",
    })[props.tone],
);
</script>

<template>
  <div :class="['rounded-lg border px-3 py-2 text-xs', cls]">
    <slot />
  </div>
</template>
