<script setup lang="ts">
import type { ProgressRow } from "@/api";
import { fmtAge, fmtProgressStep } from "@/i18n";

// Pure presentational — fed by useGranuleDetail via GranuleExpandedDetail.
defineProps<{ rows: ProgressRow[] }>();
</script>

<template>
  <div v-if="rows.length === 0" class="text-cell text-muted-foreground">
    暂无进度上报（bundle 可能未接入 $SATHOP_PROGRESS_URL）
  </div>
  <ol v-else class="space-y-1.5 border-l border-border pl-4 text-xs">
    <li v-for="p in rows" :key="p.id" class="relative">
      <span class="absolute -left-[1.4rem] top-1.5 h-2 w-2 rounded-full bg-primary shadow-soft" />
      <span class="w-20 text-muted-foreground">{{ fmtAge(p.ts) }}</span>
      <span class="ml-3 font-medium">{{ fmtProgressStep(p.step) }}</span>
      <span v-if="p.pct != null" class="ml-2 text-muted-foreground tabular-nums">
        {{ p.pct.toFixed(0) }}%
      </span>
      <span v-if="p.detail" class="ml-2 text-muted-foreground">— {{ p.detail }}</span>
    </li>
  </ol>
</template>
