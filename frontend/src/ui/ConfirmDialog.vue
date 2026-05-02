<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  AlertDialog,
  AlertDialogAction,
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

function onActionClick(e: Event) {
  if (!canConfirm.value) {
    e.preventDefault();
    return;
  }
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
        <AlertDialogAction
          :class="actionClass"
          :disabled="!canConfirm"
          @click="onActionClick"
        >
          {{ confirmRequest.confirmText }}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
