<script setup lang="ts">
defineProps<{ label: string; mono?: boolean; hint?: string }>();
</script>

<template>
  <div>
    <div class="text-[10.5px] font-medium uppercase tracking-[0.12em] text-muted">
      {{ label }}
    </div>
    <div
      :class="[
        'mt-1.5 flex items-center break-all',
        mono ? 'font-mono text-[11.5px]' : 'text-sm',
      ]"
    >
      <slot />
      <span
        v-if="hint"
        class="ml-2 rounded bg-warning/15 px-1.5 py-0.5 text-[10.5px] font-medium text-warning"
      >
        {{ hint }}
      </span>
    </div>
  </div>
</template>
