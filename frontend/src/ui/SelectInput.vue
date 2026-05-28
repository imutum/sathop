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
    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
  >
    <slot />
  </select>
</template>
