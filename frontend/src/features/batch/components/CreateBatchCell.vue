<script setup lang="ts">
defineProps<{
  modelValue: string;
  error?: string;
  placeholder?: string;
  mono?: boolean;
}>();
defineEmits<{ "update:modelValue": [v: string] }>();
</script>

<template>
  <div>
    <input
      :value="modelValue"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      :placeholder="placeholder"
      :title="error"
      :class="[
        'w-full rounded-md border bg-background px-2 py-1 outline-none transition',
        error ? 'border-danger/60' : 'border-border focus:border-primary',
        mono ? 'font-mono text-2xs' : 'text-xs',
      ]"
    />
    <div v-if="error" class="mt-0.5 text-[10px] text-danger">{{ error }}</div>
  </div>
</template>
