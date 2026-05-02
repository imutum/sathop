<script setup lang="ts">
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { requestConfirm } from "@/composables/useConfirm";

const props = withDefaults(
  defineProps<{
    widthClass?: string;
    dirty?: boolean;
    zIndex?: number;
  }>(),
  { widthClass: "w-[520px]", dirty: false, zIndex: 50 },
);

const emit = defineEmits<{ close: [] }>();

async function tryClose(): Promise<boolean> {
  if (!props.dirty) return true;
  return await requestConfirm({
    title: "放弃未保存修改？",
    description: "关闭后，当前表单中尚未保存的内容会丢失。",
    confirmText: "放弃修改",
    tone: "danger",
  });
}

function onUpdateOpen(open: boolean) {
  if (!open) emit("close");
}

async function onEsc(e: Event) {
  if (!(await tryClose())) e.preventDefault();
}

async function onInteractOutside(e: Event) {
  if (!(await tryClose())) e.preventDefault();
}
</script>

<template>
  <Dialog :open="true" @update:open="onUpdateOpen">
    <DialogContent
      :class="cn('block max-h-[90vh] max-w-none gap-0 overflow-auto', widthClass)"
      :style="{ zIndex }"
      @escape-key-down="onEsc"
      @interact-outside="onInteractOutside"
    >
      <slot />
    </DialogContent>
  </Dialog>
</template>
