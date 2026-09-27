<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <header class="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
    <div class="min-w-0">
      <h1 class="text-balance text-[26px] font-semibold leading-tight tracking-tight text-foreground md:text-[30px]">
        {{ title }}
      </h1>
      <p
        v-if="$slots.description || description"
        class="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground"
      >
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
