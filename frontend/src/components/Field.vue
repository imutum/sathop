<script setup lang="ts">
defineProps<{ label: string; mono?: boolean; hint?: string }>();
</script>

<template>
  <div>
    <div class="text-mini font-medium uppercase tracking-[0.12em] text-muted-foreground">
      {{ label }}
    </div>
    <div
      :class="[
        'mt-1.5 flex items-center break-all',
        mono ? 'font-mono text-cell' : 'text-sm',
      ]"
    >
      <slot />
      <span
        v-if="hint"
        class="ml-2 rounded bg-warning/15 px-1.5 py-0.5 text-mini font-medium text-warning"
      >
        {{ hint }}
      </span>
    </div>
  </div>
</template>
