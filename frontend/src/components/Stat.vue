<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import Crosshair from "@/components/chrome/Crosshair.vue";

// Mission-control stat tile. Numbered (e.g. "T-01") with mono signature and
// crosshair frame, oversize Fraunces value, mono caption underneath. The
// emphasis here is *typographic contrast* — serif for the number, mono for
// everything else.
const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    /** Optional channel code — e.g. "T-01", rendered top-left. */
    code?: string;
    hint?: string;
    tone?: "default" | "warn" | "bad" | "good";
    to?: string;
  }>(),
  { tone: "default" },
);

const valueCls = computed(
  () =>
    ({
      default: "text-foreground",
      good: "text-success",
      warn: "text-warning",
      bad: "text-danger",
    })[props.tone],
);

const ledCls = computed(
  () =>
    ({
      default: "bg-primary",
      good: "bg-success",
      warn: "bg-warning",
      bad: "bg-danger",
    })[props.tone],
);

const baseCls = computed(
  () =>
    "group/stat relative block overflow-hidden rounded-md border border-border bg-card shadow-card transition" +
    (props.to ? " hover:border-primary/40 hover:shadow-glow" : ""),
);
</script>

<template>
  <component :is="to ? RouterLink : 'div'" :to="to" :class="baseCls">
    <Crosshair :tone="tone === 'default' ? 'muted' : 'primary'" :inset="5" :size="9" />
    <div class="relative px-5 pt-4 pb-5">
      <!-- Channel code + label: "T-01 · 处理中". The dot is a tone LED. -->
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-3xs font-semibold uppercase tracking-section text-muted-foreground">
          <span v-if="code" class="readout text-primary/80">{{ code }}</span>
          <span v-if="code" aria-hidden class="h-2 w-px bg-border" />
          <span class="text-foreground/70">{{ label }}</span>
        </div>
        <span :class="['h-1.5 w-1.5 rounded-full', ledCls]" aria-hidden />
      </div>

      <!-- Hero value — Fraunces serif, optical-sized for headline. -->
      <div :class="['font-display mt-4 text-[44px] font-medium leading-none tracking-tight', valueCls]">
        {{ value }}
      </div>

      <!-- Hint / icon row — mono caption for the eyebrow + an optional icon. -->
      <div class="mt-3 flex items-end justify-between gap-3">
        <div v-if="$slots.hint || hint" class="readout text-2xs text-muted-foreground">
          <slot name="hint">{{ hint }}</slot>
        </div>
        <div v-else class="readout text-2xs text-muted-foreground/60">—</div>
        <span v-if="$slots.icon" class="text-muted-foreground/70 transition group-hover/stat:text-primary">
          <slot name="icon" />
        </span>
      </div>
    </div>

    <!-- Bottom signature bar — flat amber line on hover for `to` cards. -->
    <span
      v-if="to"
      aria-hidden
      class="pointer-events-none absolute inset-x-0 bottom-0 h-[2px] origin-left scale-x-0 bg-primary transition-transform duration-300 group-hover/stat:scale-x-100"
    />
  </component>
</template>
