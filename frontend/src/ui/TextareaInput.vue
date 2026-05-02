<script setup lang="ts">
import { Textarea } from "@/components/ui/textarea";

defineProps<{
  modelValue: string;
  placeholder?: string;
  ariaLabel?: string;
}>();

defineEmits<{ "update:modelValue": [value: string] }>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <Textarea
    v-bind="$attrs"
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', String($event))"
    :placeholder="placeholder"
    :aria-label="ariaLabel"
  />
</template>
