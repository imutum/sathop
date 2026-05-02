<script setup lang="ts">
import { computed } from "vue";

// Generic options keyed by string. Caller picks the union via the modelValue
// type (e.g. v-model holding "all" | "warn" | "error"). Vue's runtime doesn't
// preserve the generic but TS does at the call site.

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: { value: string; label: string; count?: number; dim?: boolean }[];
    size?: "sm" | "md";
  }>(),
  { size: "md" },
);

defineEmits<{ "update:modelValue": [value: string] }>();

const heightCls = computed(() =>
  props.size === "sm" ? "h-7 text-[11px] px-2.5" : "h-8 text-xs px-3",
);
</script>

<template>
  <div
    role="tablist"
    class="inline-flex items-center gap-0.5 rounded-lg border border-border bg-legacy-subtle p-0.5"
  >
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      role="tab"
      :aria-selected="o.value === modelValue"
      @click="$emit('update:modelValue', o.value)"
      :class="[
        heightCls,
        'inline-flex items-center gap-1.5 rounded-md font-medium transition',
        o.value === modelValue
          ? 'bg-legacy-surface text-legacy-text shadow-soft'
          : o.dim
            ? 'text-legacy-muted/50 hover:text-legacy-muted'
            : 'text-legacy-muted hover:text-legacy-text',
      ]"
    >
      {{ o.label }}
      <span
        v-if="o.count !== undefined"
        :class="[
          'tabular-nums text-[10.5px]',
          o.value === modelValue ? 'text-legacy-muted' : 'text-legacy-muted/70',
        ]"
      >
        {{ o.count }}
      </span>
    </button>
  </div>
</template>
