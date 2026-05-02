<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";

const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    hint?: string;
    tone?: "default" | "warn" | "bad" | "good";
    to?: string;
  }>(),
  { tone: "default" },
);

const dotCls = computed(
  () =>
    ({
      default: "bg-legacy-accent",
      good: "bg-success",
      warn: "bg-warning",
      bad: "bg-danger",
    })[props.tone],
);

const valueCls = computed(
  () =>
    ({
      default: "text-legacy-text",
      good: "text-success",
      warn: "text-warning",
      bad: "text-danger",
    })[props.tone],
);

const baseCls = computed(
  () =>
    "group relative block overflow-hidden rounded-lg border border-border bg-legacy-surface p-5 shadow-card transition" +
    (props.to ? " hover:border-legacy-accent/40 hover:shadow-pop" : ""),
);
</script>

<template>
  <component :is="to ? RouterLink : 'div'" :to="to" :class="baseCls">
    <div class="flex items-center justify-between">
      <span class="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-legacy-muted">
        <span :class="['h-1.5 w-1.5 rounded-full', dotCls]" aria-hidden />
        {{ label }}
      </span>
      <span v-if="$slots.icon" class="text-legacy-muted/70 transition group-hover:text-legacy-accent">
        <slot name="icon" />
      </span>
    </div>
    <div
      :class="[
        'font-display mt-3 text-[32px] font-semibold leading-none tabular-nums',
        valueCls,
      ]"
    >
      {{ value }}
    </div>
    <div v-if="$slots.hint || hint" class="mt-2 text-xs text-legacy-muted">
      <slot name="hint">{{ hint }}</slot>
    </div>
    <span
      v-if="to"
      aria-hidden
      class="pointer-events-none absolute inset-x-0 -bottom-px h-px bg-legacy-accent/30 opacity-0 transition group-hover:opacity-100"
    />
  </component>
</template>
