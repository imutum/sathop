<script setup lang="ts">
import { computed } from "vue";
import type { BatchSummary } from "@/api";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import DeliveryStats from "@/features/batch/components/DeliveryStats.vue";

// 进度页签：默认视图。各阶段实时 WIP 分布（卡点定位器，用户自己读）+ 交付吞吐/ETA。
// 已交付/失败/在途计数已在 PipelineHealth 的 chip 里，这里只补它没有的两个数。
const props = defineProps<{ summary: BatchSummary }>();

// ETA 仅实时：按最近窗口交付速率外推；无近窗交付即不显示（交付停滞信号）。
const etaSeconds = computed(() => props.summary.eta_realtime);
</script>

<template>
  <div class="space-y-5">
    <PipelineHealth :counts="summary.counts" />
    <DeliveryStats :throughput-per-min="summary.throughput_per_min" :eta-seconds="etaSeconds" />
  </div>
</template>
