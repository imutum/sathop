<script setup lang="ts">
import { computed } from "vue";

type ActionTone = "primary" | "default" | "danger" | "ghost" | "outline";

const props = withDefaults(
  defineProps<{
    tone?: ActionTone;
    pending?: boolean;
    pendingLabel?: string;
    size?: "sm" | "md";
    disabled?: boolean;
    type?: "button" | "submit" | "reset";
  }>(),
  { tone: "default", size: "md", pending: false, pendingLabel: "处理中…", type: "button" },
);

defineOptions({ inheritAttrs: true });

const sizeCls = computed(() =>
  props.size === "sm" ? "h-7 px-2.5 text-[11px] gap-1" : "h-8 px-3 text-xs gap-1.5",
);

const TONE_CLS: Record<ActionTone, string> = {
  primary: "bg-legacy-accent text-legacy-accent-fg shadow-soft hover:bg-legacy-accent/90",
  default:
    "border border-border bg-legacy-surface text-legacy-text hover:border-legacy-accent/40 hover:bg-legacy-subtle",
  danger: "border border-danger/30 bg-danger/10 text-danger hover:bg-danger/15",
  ghost: "text-legacy-muted hover:bg-legacy-subtle hover:text-legacy-text",
  outline: "border border-legacy-accent/40 bg-transparent text-legacy-accent hover:bg-legacy-accent-soft",
};

const base =
  "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition " +
  "disabled:cursor-not-allowed disabled:opacity-50 active:translate-y-px";
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || pending"
    :aria-busy="pending || undefined"
    :class="[base, sizeCls, TONE_CLS[tone]]"
  >
    <span
      v-if="pending"
      aria-hidden
      class="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border border-current border-t-transparent"
    />
    <template v-if="pending">{{ pendingLabel }}</template>
    <slot v-else />
  </button>
</template>
