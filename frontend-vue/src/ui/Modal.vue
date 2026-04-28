<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";

const props = withDefaults(
  defineProps<{
    widthClass?: string;
    dirty?: boolean;
    zIndex?: number;
  }>(),
  { widthClass: "w-[520px]", dirty: false, zIndex: 50 },
);

const emit = defineEmits<{ close: [] }>();

function tryClose() {
  if (props.dirty && !confirm("表单有未保存的修改，放弃并关闭？")) return;
  emit("close");
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.stopPropagation();
    tryClose();
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
      @click="tryClose"
      role="dialog"
      aria-modal="true"
    >
      <div
        :class="[
          widthClass,
          'relative max-h-[90vh] overflow-auto rounded-2xl border border-border bg-elevated p-6 shadow-pop animate-scale-in',
        ]"
        @click.stop
      >
        <slot />
      </div>
    </div>
  </Teleport>
</template>
