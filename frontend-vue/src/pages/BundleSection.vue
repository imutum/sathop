<script setup lang="ts">
defineProps<{ title: string; count?: number }>();
</script>

<template>
  <section class="border-t border-border/60 pt-4">
    <div class="mb-2.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted">
      <span>{{ title }}</span>
      <span
        v-if="count !== undefined"
        class="rounded-full bg-subtle px-1.5 py-px text-[10px] tabular-nums text-muted"
      >
        {{ count }}
      </span>
    </div>
    <slot />
  </section>
</template>
