<script setup lang="ts">
import { Textarea } from "@/components/ui/textarea";

// defineModel keeps this in line with TextInput / SelectInput (no manual
// modelValue prop + update emit pair).
const model = defineModel<string>({ default: "" });
defineProps<{
  placeholder?: string;
  ariaLabel?: string;
}>();
defineOptions({ inheritAttrs: false });
</script>

<template>
  <Textarea
    v-bind="$attrs"
    v-model="model"
    :placeholder="placeholder"
    :aria-label="ariaLabel"
  />
</template>
