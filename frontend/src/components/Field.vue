<script setup lang="ts">
defineProps<{ label: string; mono?: boolean; hint?: string }>();
</script>

<template>
  <div class="min-w-0">
    <div class="text-mini font-medium tracking-label text-muted-foreground">
      {{ label }}
    </div>
    <div
      :class="[
        'mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 break-all',
        mono ? 'font-mono text-cell' : 'text-sm',
      ]"
    >
      <span class="min-w-0 break-all"><slot /></span>
      <span
        v-if="hint"
        class="rounded bg-warning/15 px-1.5 py-0.5 text-mini font-medium text-warning"
      >
        {{ hint }}
      </span>
    </div>
  </div>
</template>
