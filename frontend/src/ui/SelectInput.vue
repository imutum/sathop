<script setup lang="ts">
const model = defineModel<string>({ default: "" });
defineProps<{ ariaLabel?: string }>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <select
    v-bind="$attrs"
    v-model="model"
    :aria-label="ariaLabel"
    class="flex h-10 w-full min-w-0 rounded-lg border border-input bg-card px-3 text-sm transition-colors hover:border-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50"
  >
    <slot />
  </select>
</template>
