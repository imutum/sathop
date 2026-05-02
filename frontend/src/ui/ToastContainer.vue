<script setup lang="ts">
import { toastItems, dismiss, type ToastKind } from "@/composables/useToast";
import { Icon, type IconName } from "./Icon";

type Tone = { wrap: string; icon: string; name: IconName; stroke: number };
const TONES: Record<ToastKind, Tone> = {
  success: { wrap: "border-success/30 bg-success/10 text-legacy-text", icon: "text-success bg-success/15", name: "check", stroke: 2.4 },
  error: { wrap: "border-danger/30 bg-danger/10 text-legacy-text", icon: "text-danger bg-danger/15", name: "alert", stroke: 2.2 },
  info: { wrap: "border-border bg-legacy-surface/95 text-legacy-text", icon: "text-legacy-accent bg-legacy-accent/15", name: "info", stroke: 2.2 },
};
</script>

<template>
  <div
    aria-live="polite"
    aria-atomic="false"
    class="pointer-events-none fixed right-5 bottom-5 z-[100] flex w-[340px] flex-col gap-2.5"
  >
    <div
      v-for="it in toastItems"
      :key="it.id"
      :role="it.kind === 'error' ? 'alert' : 'status'"
      :class="[
        'pointer-events-auto flex items-start gap-2.5 rounded-lg border px-3.5 py-3 text-xs shadow-pop backdrop-blur-md animate-slide-up',
        TONES[it.kind].wrap,
      ]"
    >
      <span
        :class="['grid h-6 w-6 shrink-0 place-items-center rounded-lg', TONES[it.kind].icon]"
        aria-hidden
      >
        <Icon :name="TONES[it.kind].name" :size="13" :stroke-width="TONES[it.kind].stroke" />
      </span>
      <span class="flex-1 break-words whitespace-pre-wrap leading-relaxed text-legacy-text">
        {{ it.text }}
      </span>
      <button
        @click="dismiss(it.id)"
        class="grid h-5 w-5 place-items-center rounded text-legacy-muted transition hover:bg-legacy-subtle hover:text-legacy-text"
        aria-label="关闭通知"
      >
        <Icon name="x" :size="12" :stroke-width="2.2" />
      </button>
    </div>
  </div>
</template>
