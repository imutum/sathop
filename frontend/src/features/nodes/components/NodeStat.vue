<script setup lang="ts">
import { computed } from "vue";
import HintTip from "@/components/HintTip.vue";

// Node summary tile — bigger icon tile + value/total + plain Chinese
// status chip. Tone derives from the value/total ratio so the operator
// sees "全员在线" vs "部分异常" at a glance without reading the badge.
const props = withDefaults(
  defineProps<{
    label: string;
    value: number;
    total: number;
    /** Optional secondary line, defaults to "在线 / 已注册". */
    caption?: string;
    /** Hover explanation — e.g. "几台 worker 当前在线 / 共注册了多少". */
    tooltip?: string;
  }>(),
  {},
);
defineEmits<{ click: [] }>();

type Tone = "muted" | "success" | "warning" | "danger";

const tone = computed<Tone>(() => {
  if (props.total === 0) return "muted";
  const ratio = props.value / props.total;
  if (ratio === 1) return "success";
  if (ratio >= 0.5) return "warning";
  return "danger";
});

const valueCls = computed(
  () =>
    ({
      muted: "text-muted-foreground",
      success: "text-success",
      warning: "text-warning",
      danger: "text-danger",
    })[tone.value],
);

const tileCls = computed(
  () =>
    ({
      muted: "bg-muted text-muted-foreground",
      success: "bg-success/10 text-success",
      warning: "bg-warning/10 text-warning",
      danger: "bg-danger/10 text-danger",
    })[tone.value],
);

const statusLabel = computed(
  () =>
    ({
      muted: "未注册",
      success: "健康",
      warning: "降级",
      danger: "异常",
    })[tone.value],
);

const statusCls = computed(
  () =>
    ({
      muted: "text-muted-foreground",
      success: "text-success",
      warning: "text-warning",
      danger: "text-danger",
    })[tone.value],
);
</script>

<template>
  <HintTip :text="tooltip ?? null">
    <button
      type="button"
      @click="$emit('click')"
      class="group flex w-full items-center justify-between gap-4 rounded-xl border border-border bg-card p-4 text-left transition hover:border-primary/40 hover:shadow-soft"
    >
      <div class="flex min-w-0 items-center gap-3">
        <span
          :class="['grid h-11 w-11 shrink-0 place-items-center rounded-lg transition', tileCls]"
          aria-hidden
        >
          <slot name="icon" />
        </span>
        <div class="min-w-0">
          <div class="truncate text-sm font-medium text-foreground">{{ label }}</div>
          <div class="mt-0.5 text-xs text-muted-foreground">
            {{ caption ?? "在线 / 已注册" }}
          </div>
        </div>
      </div>
      <div class="flex shrink-0 flex-col items-end gap-1">
        <div class="flex items-baseline gap-1 tabular-nums">
          <span :class="['text-2xl font-semibold leading-none', valueCls]">
            {{ value }}
          </span>
          <span class="text-sm text-muted-foreground">/ {{ total }}</span>
        </div>
        <span :class="['text-xs font-medium', statusCls]">{{ statusLabel }}</span>
      </div>
    </button>
  </HintTip>
</template>
