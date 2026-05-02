<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import ActionButton from "./ActionButton.vue";
import TextInput from "./TextInput.vue";
import { confirmInput, confirmRequest, resolveConfirm } from "../composables/useConfirm";

const inputRef = ref<InstanceType<typeof TextInput> | null>(null);

const canConfirm = computed(() => {
  const required = confirmRequest.value?.requireText;
  return !required || confirmInput.value === required;
});

watch(confirmRequest, (request) => {
  if (request?.requireText) void nextTick(() => inputRef.value?.focus?.());
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="confirmRequest"
      class="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 px-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      @click="resolveConfirm(false)"
      @keydown.esc="resolveConfirm(false)"
    >
      <div
        class="w-full max-w-[420px] rounded-lg border border-border bg-elevated p-5 shadow-pop animate-scale-in"
        @click.stop
      >
        <h2 class="font-display text-base font-semibold text-text">
          {{ confirmRequest.title }}
        </h2>
        <p
          v-if="confirmRequest.description"
          class="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted"
        >
          {{ confirmRequest.description }}
        </p>

        <label v-if="confirmRequest.requireText" class="mt-4 block">
          <span class="text-xs font-medium text-text">
            {{ confirmRequest.inputLabel ?? `输入 ${confirmRequest.requireText} 确认` }}
          </span>
          <TextInput
            ref="inputRef"
            v-model="confirmInput"
            class="mt-2"
            :placeholder="confirmRequest.requireText"
            aria-label="确认文本"
          />
        </label>

        <div class="mt-5 flex justify-end gap-2">
          <ActionButton tone="default" @click="resolveConfirm(false)">
            {{ confirmRequest.cancelText }}
          </ActionButton>
          <ActionButton
            :tone="confirmRequest.tone === 'danger' ? 'danger' : 'primary'"
            :disabled="!canConfirm"
            @click="resolveConfirm(true)"
          >
            {{ confirmRequest.confirmText }}
          </ActionButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>
