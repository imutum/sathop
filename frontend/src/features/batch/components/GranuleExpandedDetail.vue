<script setup lang="ts">
import StageTimingStrip from "@/features/batch/components/StageTimingStrip.vue";
import ProgressTimeline from "@/features/batch/components/ProgressTimeline.vue";
import GranuleEvents from "@/features/batch/components/GranuleEvents.vue";

defineProps<{ granuleId: string; batchId: string }>();
</script>

<template>
  <div class="space-y-3">
    <StageTimingStrip :granule-id="granuleId" />
    <ProgressTimeline :granule-id="granuleId" />
    <GranuleEvents :granule-id="granuleId" :batch-id="batchId" />
  </div>
</template>
