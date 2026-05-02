<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { requestConfirm } from "../composables/useConfirm";

const props = withDefaults(
  defineProps<{
    widthClass?: string;
    dirty?: boolean;
    zIndex?: number;
  }>(),
  { widthClass: "w-[520px]", dirty: false, zIndex: 50 },
);

const emit = defineEmits<{ close: [] }>();

async function tryClose() {
  if (
    props.dirty &&
    !(await requestConfirm({
      title: "放弃未保存修改？",
      description: "关闭后，当前表单中尚未保存的内容会丢失。",
      confirmText: "放弃修改",
      tone: "danger",
    }))
  ) {
    return;
  }
  emit("close");
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.stopPropagation();
    void tryClose();
  }
}

onMounted(() => window.addEventListener("keydown", onKeyDown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeyDown));
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm"
      :style="{ zIndex }"
      @click="void tryClose()"
      role="dialog"
      aria-modal="true"
    >
      <div
        :class="[
          widthClass,
          'relative max-h-[90vh] overflow-auto rounded-lg border border-border bg-elevated p-6 shadow-pop animate-scale-in',
        ]"
        @click.stop
      >
        <slot />
      </div>
    </div>
  </Teleport>
</template>
