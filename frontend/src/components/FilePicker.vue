<script setup lang="ts">
import { fmtBytes } from "@/lib/format";
import { Icon } from "@/components/Icon";

defineOptions({ inheritAttrs: false });

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
  <div class="group relative rounded-xl border border-dashed border-input bg-muted/30 p-5 transition-colors hover:border-primary/50 hover:bg-accent/30 focus-within:ring-2 focus-within:ring-ring">
    <input
      aria-label="选择文件"
      v-bind="$attrs"
      type="file"
      :accept="accept"
      @change="onChange"
      class="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
    />
    <div class="flex items-center gap-4" aria-hidden="true">
      <span class="grid size-11 shrink-0 place-items-center rounded-xl border border-border bg-card text-primary"><Icon name="upload" :size="20" /></span>
      <div class="min-w-0">
        <div class="truncate text-sm font-medium">{{ modelValue?.name ?? '选择文件' }}</div>
        <div class="mt-1 text-xs text-muted-foreground">{{ modelValue ? `${fmtBytes(modelValue.size)} · 点击更换` : accept ? `支持 ${accept}` : '从本机选择要上传的文件' }}</div>
      </div>
    </div>
  </div>
</template>
