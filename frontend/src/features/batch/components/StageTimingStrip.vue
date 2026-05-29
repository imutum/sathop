<script setup lang="ts">
import type { TimingRow } from "@/api";
import { TIMING_STAGE_ZH, fmtMs } from "@/i18n";

// Pure presentational — fed by useGranuleDetail via GranuleExpandedDetail.
defineProps<{ stages: TimingRow[] }>();
</script>

<template>
  <div v-if="stages.length > 0" class="flex flex-wrap gap-2">
    <span
      v-for="r in stages"
      :key="r.id"
      class="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1 font-mono text-2xs shadow-soft"
    >
      <span class="text-muted-foreground">{{ TIMING_STAGE_ZH[r.stage] }}</span>
      <span class="text-foreground">{{ fmtMs(r.duration_ms) }}</span>
    </span>
  </div>
</template>
