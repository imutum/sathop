<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    className?: string;
    bodyClassName?: string;
    padded?: boolean;
  }>(),
  { padded: true },
);
</script>

<template>
  <section
    :class="['rounded-2xl border border-border bg-surface shadow-card', className]"
  >
    <header
      v-if="title || description || $slots.title || $slots.description || $slots.action"
      class="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4"
    >
      <div class="min-w-0">
        <h3
          v-if="$slots.title || title"
          class="font-display text-[13.5px] font-semibold tracking-tight text-text"
        >
          <slot name="title">{{ title }}</slot>
        </h3>
        <p
          v-if="$slots.description || description"
          class="mt-0.5 text-xs text-muted"
        >
          <slot name="description">{{ description }}</slot>
        </p>
      </div>
      <div v-if="$slots.action" class="shrink-0"><slot name="action" /></div>
    </header>
    <div :class="[padded ? 'p-5' : '', bodyClassName]">
      <slot />
    </div>
  </section>
</template>
