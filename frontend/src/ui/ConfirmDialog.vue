<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { confirmInput, confirmRequest, resolveConfirm } from "@/composables/useConfirm";

const inputRef = ref<{ $el?: HTMLInputElement } | null>(null);

const open = computed({
  get: () => !!confirmRequest.value,
  set: (v) => {
    if (!v) resolveConfirm(false);
  },
});

const canConfirm = computed(() => {
  const required = confirmRequest.value?.requireText;
  return !required || confirmInput.value === required;
});

const actionClass = computed(() =>
  cn(
    buttonVariants({
      variant: confirmRequest.value?.tone === "danger" ? "destructive" : "default",
    }),
  ),
);

watch(confirmRequest, (request) => {
  if (request?.requireText) {
    void nextTick(() => inputRef.value?.$el?.focus?.());
  }
});

// reka-ui 的 AlertDialogAction 点击时会先把 dialog 关掉再触发 @click，
// 而 v-model:open 的 setter 在关闭分支里调用 resolveConfirm(false)，
// 把 promise 抢先 resolve 为 false ⇒ 后续 resolveConfirm(true) 变 no-op。
// 改用普通 button 让我们自己掌控 resolve 顺序：先 resolveConfirm(true)
// 清空 confirmRequest → open=false → setter 再次 resolveConfirm(false)
// 时 current 已 null ⇒ 安全 no-op。
function onActionClick() {
  if (!canConfirm.value) return;
  resolveConfirm(true);
}
</script>

<template>
  <AlertDialog v-model:open="open">
    <AlertDialogContent v-if="confirmRequest" class="max-w-[420px]">
      <AlertDialogHeader>
        <AlertDialogTitle>{{ confirmRequest.title }}</AlertDialogTitle>
        <AlertDialogDescription
          v-if="confirmRequest.description"
          class="whitespace-pre-line"
        >
          {{ confirmRequest.description }}
        </AlertDialogDescription>
      </AlertDialogHeader>

      <label v-if="confirmRequest.requireText" class="block">
        <span class="text-xs font-medium">
          {{ confirmRequest.inputLabel ?? `输入 ${confirmRequest.requireText} 确认` }}
        </span>
        <Input
          ref="inputRef"
          v-model="confirmInput"
          class="mt-2"
          :placeholder="confirmRequest.requireText"
          aria-label="确认文本"
        />
      </label>

      <AlertDialogFooter>
        <AlertDialogCancel @click="resolveConfirm(false)">
          {{ confirmRequest.cancelText }}
        </AlertDialogCancel>
        <button
          type="button"
          :class="actionClass"
          :disabled="!canConfirm"
          @click="onActionClick"
        >
          {{ confirmRequest.confirmText }}
        </button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
