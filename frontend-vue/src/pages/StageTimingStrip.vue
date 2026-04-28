<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "../api";
import { TIMING_STAGE_ZH, fmtMs } from "../i18n";

const props = defineProps<{ granuleId: string }>();

const q = useQuery({
  queryKey: computed(() => ["granule-timing", props.granuleId]),
  queryFn: () => API.granuleTiming(props.granuleId),
});

const rows = computed(() => q.data.value ?? []);
</script>

<template>
  <div v-if="rows.length > 0" class="flex flex-wrap gap-2">
    <span
      v-for="r in rows"
      :key="r.id"
      class="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1 font-mono text-[11px] shadow-soft"
    >
      <span class="text-muted">{{ TIMING_STAGE_ZH[r.stage] }}</span>
      <span class="text-text">{{ fmtMs(r.duration_ms) }}</span>
    </span>
  </div>
</template>
