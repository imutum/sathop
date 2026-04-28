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
  <div class="relative">
    <span
      v-if="$slots.leftIcon"
      class="pointer-events-none absolute inset-y-0 left-2.5 grid place-items-center text-muted"
    >
      <slot name="leftIcon" />
    </span>
    <input
      v-bind="$attrs"
      :value="modelValue"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :class="[
        'h-8 w-full rounded-lg border border-border bg-surface text-xs text-text outline-none transition placeholder:text-muted/70 hover:border-accent/40 focus:border-accent',
        $slots.leftIcon ? 'pl-8 pr-3' : 'px-3',
      ]"
    />
  </div>
</template>
