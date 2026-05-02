<script setup lang="ts">
import { computed } from "vue";
import Crosshair from "./Crosshair.vue";

// "Mission panel" — opinionated card variant for the redesigned console.
// Pairs the existing shadcn Card aesthetic with corner crosshairs and an
// optional "live" affordance (faint amber edge glow). Think of it as a
// shadcn Card with a uniform on.
const props = withDefaults(
  defineProps<{
    /** Show corner crosshairs. */
    crosshair?: boolean;
    /** Add a faint signature-amber edge glow — for "live" panels. */
    live?: boolean;
    /** Padding preset. */
    padding?: "none" | "sm" | "md" | "lg";
    /** Extra utility classes. */
    class?: string;
  }>(),
  { crosshair: true, live: false, padding: "none" },
);

const padCls = computed(() =>
  ({
    none: "",
    sm: "p-4",
    md: "p-5",
    lg: "p-6",
  })[props.padding],
);
</script>

<template>
  <section
    :class="[
      'group relative rounded-md border bg-card text-card-foreground shadow-card',
      live
        ? 'border-primary/30 shadow-glow'
        : 'border-border',
      padCls,
      props.class,
    ]"
  >
    <Crosshair v-if="crosshair" :tone="live ? 'primary' : 'muted'" />
    <slot />
  </section>
</template>
