<script setup lang="ts">
import { computed } from "vue";
import { fmtDuration, fmtThroughputPerMin } from "@/i18n";

// 交付吞吐 + 预计剩余两块。批次进度页与首页系统级共用，口径一致。
const props = defineProps<{ throughputPerMin: number | null; etaSeconds: number | null }>();

const etaLabel = computed(() =>
  props.etaSeconds == null ? "—" : `≈ ${fmtDuration(props.etaSeconds * 1000)}`,
);
const throughputLabel = computed(() => fmtThroughputPerMin(props.throughputPerMin));
</script>

<template>
  <div class="grid grid-cols-2 gap-3 sm:max-w-sm">
    <div
      class="rounded-lg border border-border bg-muted/40 px-4 py-3"
      title="最近 1 分钟内接收端确认的交付速率；0 表示该时段无新增交付"
    >
      <div class="text-xs text-muted-foreground">交付速率</div>
      <div class="mt-1 text-xl font-semibold tabular-nums">{{ throughputLabel }}</div>
    </div>
    <div
      class="rounded-lg border border-border bg-muted/40 px-4 py-3"
      title="按最近 1 分钟交付速率估算；无新增交付或样本不足时不显示"
    >
      <div class="text-xs text-muted-foreground">预计剩余</div>
      <div class="mt-1 text-xl font-semibold tabular-nums">{{ etaLabel }}</div>
    </div>
  </div>
</template>
