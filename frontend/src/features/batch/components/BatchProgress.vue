<script setup lang="ts">
import { computed } from "vue";
import type { BatchSummary } from "@/api";
import PipelineHealth from "@/features/batch/components/PipelineHealth.vue";
import DeliveryStats from "@/features/batch/components/DeliveryStats.vue";

// 进度页签：默认视图。与总览同一个 PipelineHealth（大阶段 + 小阶段分级，卡点定位
// 器，用户自己读），只是数据是单批次；再补 PipelineHealth 没有的交付吞吐/ETA。
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
