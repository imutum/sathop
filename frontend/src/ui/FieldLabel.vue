<script setup lang="ts">
defineProps<{ required?: boolean }>();
</script>

<template>
  <span class="text-[11px] font-medium uppercase tracking-[0.10em] text-legacy-muted">
    <slot />
    <span v-if="required" class="ml-0.5 text-danger" aria-hidden>*</span>
  </span>
</template>
