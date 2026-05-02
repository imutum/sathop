<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    /** `inbox` for genuine "no items" silence; `signal` is mission-control
        themed (a small antenna with a soft amber sweep). */
    illustration?: "none" | "inbox" | "signal";
  }>(),
  { illustration: "none" },
);
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-4 py-14 text-center">
    <!-- Inbox: papered tray, neutral. -->
    <svg
      v-if="illustration === 'inbox'"
      width="92"
      height="68"
      viewBox="0 0 120 88"
      fill="none"
      class="text-muted-foreground/55"
      aria-hidden
    >
      <path
        d="M44 6 L74 6 A4 4 0 0 1 78 10 L78 36 L40 36 L40 10 A4 4 0 0 1 44 6 Z"
        fill="hsl(var(--muted))"
        stroke="currentColor"
        stroke-width="1.4"
      />
      <line x1="48" y1="16" x2="70" y2="16" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
      <line x1="48" y1="22" x2="66" y2="22" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
      <line x1="48" y1="28" x2="62" y2="28" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
      <path
        d="M16 50 L34 32 L86 32 L104 50 L104 74 A4 4 0 0 1 100 78 L20 78 A4 4 0 0 1 16 74 Z"
        fill="hsl(var(--background))"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linejoin="round"
      />
      <path
        d="M16 50 L46 50 L52 58 L68 58 L74 50 L104 50"
        fill="hsl(var(--muted))"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linejoin="round"
      />
    </svg>

    <!-- Signal: little antenna with concentric arcs — mission-themed. -->
    <svg
      v-else-if="illustration === 'signal'"
      width="92"
      height="80"
      viewBox="0 0 120 100"
      fill="none"
      class="text-muted-foreground/55"
      aria-hidden
    >
      <path d="M60 70 L60 32" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      <path d="M48 84 L72 84 L66 70 L54 70 Z" fill="hsl(var(--muted))" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
      <circle cx="60" cy="30" r="3" fill="hsl(var(--primary))" />
      <path d="M40 30 a20 20 0 0 1 40 0" stroke="hsl(var(--primary) / 0.5)" stroke-width="1.4" fill="none" />
      <path d="M28 30 a32 32 0 0 1 64 0" stroke="hsl(var(--primary) / 0.3)" stroke-width="1.2" fill="none" />
      <path d="M16 30 a44 44 0 0 1 88 0" stroke="hsl(var(--primary) / 0.18)" stroke-width="1" fill="none" />
    </svg>

    <div
      v-else-if="$slots.icon"
      class="grid h-12 w-12 place-items-center rounded-md border border-border bg-muted text-muted-foreground"
    >
      <slot name="icon" />
    </div>

    <div class="space-y-1">
      <div class="text-[13px] font-medium text-foreground">{{ title }}</div>
      <div v-if="$slots.description || description" class="readout max-w-md text-3xs text-muted-foreground">
        <slot name="description">{{ description }}</slot>
      </div>
    </div>
    <div v-if="$slots.action" class="mt-1"><slot name="action" /></div>
  </div>
</template>
