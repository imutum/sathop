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
      title="最近一分钟交付（receiver 确认）速率，滚动窗口。0 = 交付停滞"
    >
      <div class="text-xs text-muted-foreground">交付吞吐</div>
      <div class="mt-1 text-xl font-semibold tabular-nums">{{ throughputLabel }}</div>
    </div>
    <div
      class="rounded-lg border border-border bg-muted/40 px-4 py-3"
      title="按近一分钟交付速率外推的剩余时间；交付停滞或样本不足时为 —"
    >
      <div class="text-xs text-muted-foreground">预计剩余</div>
      <div class="mt-1 text-xl font-semibold tabular-nums">{{ etaLabel }}</div>
    </div>
  </div>
</template>
