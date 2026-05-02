<script setup lang="ts">
defineProps<{
  modelValue: string;
  placeholder?: string;
  ariaLabel?: string;
}>();

defineEmits<{ "update:modelValue": [value: string] }>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <textarea
    v-bind="$attrs"
    :value="modelValue"
    :placeholder="placeholder"
    :aria-label="ariaLabel"
    @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    class="w-full rounded-md border border-border bg-legacy-surface px-3 py-2 text-sm text-legacy-text outline-none transition placeholder:text-legacy-muted/70 hover:border-legacy-accent/40 focus:border-legacy-accent disabled:cursor-not-allowed disabled:opacity-60"
  />
</template>
