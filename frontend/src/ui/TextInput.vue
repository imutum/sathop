<script setup lang="ts">
import { ref } from "vue";

defineProps<{
  modelValue: string;
  placeholder?: string;
  ariaLabel?: string;
}>();

defineEmits<{ "update:modelValue": [value: string] }>();
defineOptions({ inheritAttrs: false });

const inputEl = ref<HTMLInputElement | null>(null);
defineExpose({ focus: () => inputEl.value?.focus() });
</script>

<template>
  <div class="relative">
    <span
      v-if="$slots.leftIcon"
      class="pointer-events-none absolute inset-y-0 left-2.5 grid place-items-center text-legacy-muted"
    >
      <slot name="leftIcon" />
    </span>
    <input
      ref="inputEl"
      v-bind="$attrs"
      :value="modelValue"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :class="[
        'h-8 w-full rounded-lg border border-border bg-legacy-surface text-xs text-legacy-text outline-none transition placeholder:text-legacy-muted/70 hover:border-legacy-accent/40 focus:border-legacy-accent',
        $slots.leftIcon ? 'pl-8 pr-3' : 'px-3',
      ]"
    />
  </div>
</template>
