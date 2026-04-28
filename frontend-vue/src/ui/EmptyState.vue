<script setup lang="ts">
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 py-12 text-center">
    <div
      v-if="$slots.icon"
      class="grid h-12 w-12 place-items-center rounded-2xl border border-border bg-subtle text-muted"
    >
      <slot name="icon" />
    </div>
    <div class="text-sm font-medium text-text">{{ title }}</div>
    <div v-if="$slots.description || description" class="max-w-md text-xs text-muted">
      <slot name="description">{{ description }}</slot>
    </div>
    <div v-if="$slots.action" class="mt-1"><slot name="action" /></div>
  </div>
</template>
