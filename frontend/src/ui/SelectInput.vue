<script setup lang="ts">
defineProps<{
  modelValue: string;
  ariaLabel?: string;
}>();

defineEmits<{ "update:modelValue": [value: string] }>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <select
    v-bind="$attrs"
    :value="modelValue"
    :aria-label="ariaLabel"
    @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    class="h-9 w-full rounded-md border border-border bg-legacy-surface px-3 text-sm text-legacy-text outline-none transition hover:border-legacy-accent/40 focus:border-legacy-accent disabled:cursor-not-allowed disabled:opacity-60"
  >
    <slot />
  </select>
</template>
