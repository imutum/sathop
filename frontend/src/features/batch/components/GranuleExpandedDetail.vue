<script setup lang="ts">
import { useGranuleDetail } from "@/features/batch/useGranuleDetail";
import StageTimingStrip from "@/features/batch/components/StageTimingStrip.vue";
import ProgressTimeline from "@/features/batch/components/ProgressTimeline.vue";
import GranuleEvents from "@/features/batch/components/GranuleEvents.vue";

const props = defineProps<{ granuleId: string; batchId: string }>();

// One composable owns all three queries → one loading/error gate instead of
// three children each flashing their own.
const { timingRows, progressRows, eventRows, isLoading, isError } = useGranuleDetail(
  () => props.granuleId,
);
</script>

<template>
  <div class="space-y-3">
    <div v-if="isLoading" class="text-xs text-muted-foreground">加载中…</div>
    <div v-else-if="isError" class="text-2xs text-danger">加载数据粒详情失败，请稍后重试</div>
    <template v-else>
      <StageTimingStrip :stages="timingRows" />
      <ProgressTimeline :rows="progressRows" />
      <GranuleEvents :rows="eventRows" :granule-id="granuleId" :batch-id="batchId" />
    </template>
  </div>
</template>
