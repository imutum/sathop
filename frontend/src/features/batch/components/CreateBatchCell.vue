<script setup lang="ts">
const model = defineModel<string>({ required: true });
defineProps<{
  error?: string;
  placeholder?: string;
  mono?: boolean;
}>();
</script>

<template>
  <div>
    <input
      v-model="model"
      :placeholder="placeholder"
      :title="error"
      :class="[
        'w-full rounded-md border bg-background px-2 py-1 outline-none transition-colors',
        error ? 'border-danger/60' : 'border-border focus:border-primary',
        mono ? 'font-mono text-2xs' : 'text-xs',
      ]"
    />
    <div v-if="error" class="mt-0.5 text-3xs text-danger">{{ error }}</div>
  </div>
</template>
