<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue?: string;
    ariaLabel?: string;
  }>(),
  { modelValue: "" },
);

defineEmits<{ "update:modelValue": [value: string] }>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <select
    v-bind="$attrs"
    :value="modelValue"
    :aria-label="ariaLabel"
    @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
  >
    <slot />
  </select>
</template>
