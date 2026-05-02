<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ label: string; value: number; total: number }>();
defineEmits<{ click: [] }>();

const tone = computed(() => {
  const ratio = props.total > 0 ? props.value / props.total : 0;
  if (props.total === 0) return "muted";
  if (ratio === 1) return "success";
  if (ratio >= 0.5) return "warning";
  return "danger";
});

const colorCls = computed(
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
  <button
    type="button"
    @click="$emit('click')"
    class="group flex w-full items-center justify-between rounded-lg border border-border bg-muted/40 p-3.5 text-left transition hover:border-primary/40 hover:bg-muted"
  >
    <div class="flex items-center gap-3">
      <span
        class="grid h-9 w-9 place-items-center rounded-lg bg-background text-muted-foreground shadow-soft transition group-hover:text-primary"
      >
        <slot name="icon" />
      </span>
      <div>
        <div class="text-2xs font-medium uppercase tracking-widest text-muted-foreground">{{ label }}</div>
        <div class="mt-1 text-[13px] text-foreground">在线 / 已注册</div>
      </div>
    </div>
    <div class="flex items-baseline gap-1.5 tabular-nums">
      <span :class="['font-display text-2xl font-semibold', colorCls]">
        {{ value }}
      </span>
      <span class="text-sm text-muted-foreground">/ {{ total }}</span>
    </div>
  </button>
</template>
