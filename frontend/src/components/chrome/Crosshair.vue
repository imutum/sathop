<script setup lang="ts">
// Four corner brackets that decorate cards, panels, and key call-outs.
// Pure CSS — no extra DOM cost. Apply to any positioned parent; brackets
// inset by 6px from each corner.
withDefaults(
  defineProps<{
    /** Bracket arm length in px. Default 10. */
    size?: number;
    /** Inset from corner in px. Default 6. */
    inset?: number;
    /** Tone of the brackets. */
    tone?: "muted" | "primary" | "foreground";
    /** Stroke width. Default 1. */
    weight?: number;
  }>(),
  { size: 10, inset: 6, tone: "muted", weight: 1 },
);
</script>

<template>
  <span
    aria-hidden
    class="pointer-events-none absolute inset-0 z-[1]"
  >
    <!-- top-left -->
    <span
      :class="[
        'absolute',
        tone === 'primary' && 'text-primary',
        tone === 'foreground' && 'text-foreground',
        tone === 'muted' && 'text-muted-foreground/55',
      ]"
      :style="{
        top: inset + 'px',
        left: inset + 'px',
        width: size + 'px',
        height: size + 'px',
        borderTop: weight + 'px solid currentColor',
        borderLeft: weight + 'px solid currentColor',
      }"
    />
    <!-- top-right -->
    <span
      :class="[
        'absolute',
        tone === 'primary' && 'text-primary',
        tone === 'foreground' && 'text-foreground',
        tone === 'muted' && 'text-muted-foreground/55',
      ]"
      :style="{
        top: inset + 'px',
        right: inset + 'px',
        width: size + 'px',
        height: size + 'px',
        borderTop: weight + 'px solid currentColor',
        borderRight: weight + 'px solid currentColor',
      }"
    />
    <!-- bottom-left -->
    <span
      :class="[
        'absolute',
        tone === 'primary' && 'text-primary',
        tone === 'foreground' && 'text-foreground',
        tone === 'muted' && 'text-muted-foreground/55',
      ]"
      :style="{
        bottom: inset + 'px',
        left: inset + 'px',
        width: size + 'px',
        height: size + 'px',
        borderBottom: weight + 'px solid currentColor',
        borderLeft: weight + 'px solid currentColor',
      }"
    />
    <!-- bottom-right -->
    <span
      :class="[
        'absolute',
        tone === 'primary' && 'text-primary',
        tone === 'foreground' && 'text-foreground',
        tone === 'muted' && 'text-muted-foreground/55',
      ]"
      :style="{
        bottom: inset + 'px',
        right: inset + 'px',
        width: size + 'px',
        height: size + 'px',
        borderBottom: weight + 'px solid currentColor',
        borderRight: weight + 'px solid currentColor',
      }"
    />
  </span>
</template>
