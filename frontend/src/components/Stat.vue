<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import HintTip from "@/components/HintTip.vue";

// Compact stat tile used by Dashboard and elsewhere. Tone-tints both the
// value glyph and the icon-tile so the eye locks onto bad/warn cards
// without scanning. Tooltip support lets the caller explain *what the
// number means* — operators who don't live in this codebase shouldn't
// have to guess.
const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    /** Single-line caption shown beneath the value. */
    hint?: string;
    /** Optional extra explanation surfaced on hover (Tooltip). */
    tooltip?: string;
    tone?: "default" | "warn" | "bad" | "good";
    /** When set, the whole tile is a router link. */
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

// Soft icon tile — colored fill at low alpha; signals tone without
// shouting. Plain `default` uses muted so it stays visually quiet.
const tileCls = computed(
  () =>
    ({
      default: "bg-muted text-muted-foreground",
      good: "bg-success/10 text-success",
      warn: "bg-warning/10 text-warning",
      bad: "bg-danger/10 text-danger",
    })[props.tone],
);
</script>

<template>
  <HintTip :text="tooltip ?? null">
    <component
      :is="to ? RouterLink : 'div'"
      :to="to"
      :class="[
        'group relative block overflow-hidden rounded-xl border border-border bg-card p-5 shadow-card transition',
        to && 'hover:border-primary/40 hover:shadow-pop',
      ]"
    >
      <div class="flex items-start gap-4">
        <span
          v-if="$slots.icon"
          :class="['grid h-11 w-11 shrink-0 place-items-center rounded-lg', tileCls]"
          aria-hidden
        >
          <slot name="icon" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-xs font-medium text-muted-foreground">{{ label }}</div>
          <div
            :class="[
              'mt-2 text-[28px] font-semibold leading-none tabular-nums',
              valueCls,
            ]"
          >
            {{ value }}
          </div>
          <div v-if="$slots.hint || hint" class="mt-2 text-xs text-muted-foreground">
            <slot name="hint">{{ hint }}</slot>
          </div>
        </div>
      </div>
    </component>
  </HintTip>
</template>
