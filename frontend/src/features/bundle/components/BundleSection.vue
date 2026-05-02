<script setup lang="ts">
defineProps<{ title: string; count?: number }>();
</script>

<template>
  <section class="border-t border-border/60 pt-4">
    <div class="mb-2.5 flex items-center gap-1.5 text-mini font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      <span>{{ title }}</span>
      <span
        v-if="count !== undefined"
        class="rounded-full bg-muted px-1.5 py-px text-[10px] tabular-nums text-muted-foreground"
      >
        {{ count }}
      </span>
    </div>
    <slot />
  </section>
</template>
