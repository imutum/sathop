<script setup lang="ts">
import { fmtBytes } from "./format";

defineProps<{
  modelValue: File | null;
  accept?: string;
}>();

const emit = defineEmits<{ "update:modelValue": [f: File | null] }>();

function onChange(e: Event) {
  emit("update:modelValue", (e.target as HTMLInputElement).files?.[0] ?? null);
}
</script>

<template>
  <div>
    <input
      type="file"
      :accept="accept"
      @change="onChange"
      class="mt-2 block w-full cursor-pointer rounded-lg border border-dashed border-border bg-subtle/40 px-3 py-3 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-accent-fg hover:border-accent/40"
    />
    <div v-if="modelValue" class="mt-1.5 text-[10.5px] text-muted">
      已选：<span class="font-mono">{{ modelValue.name }}</span> · {{ fmtBytes(modelValue.size) }}
    </div>
  </div>
</template>
