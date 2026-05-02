<script setup lang="ts">
// `[ TITLE ]` ornament — frames a label between thin square brackets that
// inherit the surrounding text color. Used to anchor card titles and key
// readouts in the Orbital Ops aesthetic.
withDefaults(
  defineProps<{
    /** Color tone for the brackets themselves; the slot keeps inherited color. */
    tone?: "default" | "muted" | "primary";
    /** Optional gap override — defaults to 0.4ch. */
    gap?: string;
  }>(),
  { tone: "default" },
);
</script>

<template>
  <span class="inline-flex items-center" :style="{ gap: gap ?? '0.4ch' }">
    <span
      aria-hidden
      :class="[
        'select-none font-mono leading-none',
        tone === 'primary' && 'text-primary',
        tone === 'muted' && 'text-muted-foreground/70',
        tone === 'default' && 'text-current opacity-60',
      ]"
    >
      [
    </span>
    <slot />
    <span
      aria-hidden
      :class="[
        'select-none font-mono leading-none',
        tone === 'primary' && 'text-primary',
        tone === 'muted' && 'text-muted-foreground/70',
        tone === 'default' && 'text-current opacity-60',
      ]"
    >
      ]
    </span>
  </span>
</template>
