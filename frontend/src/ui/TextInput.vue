<script setup lang="ts">
import { ref } from "vue";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const model = defineModel<string>({ required: true });
defineProps<{
  placeholder?: string;
  ariaLabel?: string;
}>();
defineOptions({ inheritAttrs: false });

const inputRef = ref<{ $el?: HTMLInputElement } | null>(null);
defineExpose({ focus: () => inputRef.value?.$el?.focus?.() });
</script>

<template>
  <div :class="$slots.leftIcon ? 'relative' : ''">
    <span
      v-if="$slots.leftIcon"
      class="pointer-events-none absolute inset-y-0 left-2.5 z-10 grid place-items-center text-muted-foreground"
    >
      <slot name="leftIcon" />
    </span>
    <Input
      ref="inputRef"
      v-bind="$attrs"
      v-model="model"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :class="cn($slots.leftIcon ? 'pl-8' : '')"
    />
  </div>
</template>
