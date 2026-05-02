<script setup lang="ts">
defineProps<{ required?: boolean }>();
</script>

<template>
  <span class="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
    <slot />
    <span v-if="required" class="ml-0.5 text-danger" aria-hidden>*</span>
  </span>
</template>
