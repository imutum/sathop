<script setup lang="ts">
import { ref } from "vue";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { requestConfirm } from "@/composables/useConfirm";

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    widthClass?: string;
    dirty?: boolean;
    zIndex?: number;
  }>(),
  { widthClass: "w-[520px]", dirty: false, zIndex: 50 },
);

const emit = defineEmits<{ close: [] }>();
const confirmingClose = ref(false);

async function close() {
  if (confirmingClose.value) return;
  if (!props.dirty) { emit("close"); return; }
  confirmingClose.value = true;
  try {
    if (await requestConfirm({
      title: "放弃未保存修改？",
      description: "关闭后，当前表单中尚未保存的内容会丢失。",
      confirmText: "放弃修改",
      tone: "danger",
    })) emit("close");
  } finally {
    confirmingClose.value = false;
  }
}

function onDismiss(e: Event) {
  // Reka checks cancellation synchronously, before a confirmation can resolve.
  e.preventDefault();
  void close();
}
</script>

<template>
  <Dialog :open="true" @update:open="(open) => { if (!open) void close(); }">
    <DialogContent
      :class="cn('flex max-h-[90dvh] max-w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0', widthClass)"
      :layer="zIndex"
      v-bind="description ? {} : { 'aria-describedby': undefined }"
      @escape-key-down="onDismiss"
      @interact-outside="onDismiss"
    >
      <header class="shrink-0 border-b border-border/70 px-6 py-5 pr-16">
        <DialogTitle class="text-lg leading-snug">{{ title }}</DialogTitle>
        <DialogDescription v-if="description" class="mt-2 text-sm leading-relaxed">{{ description }}</DialogDescription>
      </header>
      <div class="min-h-0 overflow-y-auto overscroll-contain p-6 [&:has(.modal-actions)]:pb-0">
        <slot :close="close" />
      </div>
    </DialogContent>
  </Dialog>
</template>
