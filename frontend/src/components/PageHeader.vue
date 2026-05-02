<script setup lang="ts">
import { computed } from "vue";

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    /** Optional ordinal — e.g. "01" — rendered as the section number above the title. */
    n?: string | number;
    /** Optional kicker — small uppercase label rendered above the title in
        place of (or alongside) the section number. e.g. "TELEMETRY". */
    kicker?: string;
  }>(),
  {},
);

defineSlots<{
  description: () => unknown;
  actions: () => unknown;
  meta: () => unknown;
}>();

const ord = computed<string | null>(() => {
  return null; // placeholder — keep API symmetric, but rendering uses props.n
});
void ord;
</script>

<template>
  <header class="space-y-3">
    <div class="flex items-end justify-between gap-4 flex-wrap">
      <div class="min-w-0">
        <!-- Kicker / ordinal — section ribbon above the title. -->
        <div class="mb-2 flex items-center gap-2.5 text-3xs font-semibold uppercase tracking-section text-muted-foreground">
          <span v-if="n" class="readout text-primary">§ {{ String(n).padStart(2, '0') }}</span>
          <span v-if="n && kicker" aria-hidden class="text-muted-foreground/50">/</span>
          <span v-if="kicker">{{ kicker }}</span>
          <span v-if="n || kicker" aria-hidden class="ml-1 h-px w-12 bg-border" />
        </div>

        <h1 class="font-display text-balance text-[34px] font-medium leading-[1.05] text-foreground tracking-tight">
          {{ title }}
        </h1>
        <p
          v-if="$slots.description || description"
          class="mt-2 max-w-2xl text-sm text-muted-foreground"
        >
          <slot name="description">{{ description }}</slot>
        </p>
      </div>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <!-- Hairline ruling beneath the header, with optional inline meta on the
         right edge — used to slot live counts, last-updated timestamps, etc.
         Pure decoration when no #meta slot is provided. -->
    <div class="flex items-center gap-3">
      <span aria-hidden class="h-px flex-1 bg-border" />
      <div v-if="$slots.meta" class="text-3xs text-muted-foreground readout">
        <slot name="meta" />
      </div>
      <span v-if="$slots.meta" aria-hidden class="h-px w-8 bg-border" />
    </div>
  </header>
</template>
