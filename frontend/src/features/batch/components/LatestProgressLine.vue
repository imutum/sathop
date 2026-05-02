<script setup lang="ts">
import type { ProgressRow } from "@/api";
import { fmtProgressStep } from "@/i18n";

defineProps<{ row: ProgressRow }>();
</script>

<template>
  <div class="ml-4 mt-0.5 text-2xs text-muted-foreground">
    ▸ {{ fmtProgressStep(row.step) }}
    <template v-if="row.pct != null">· {{ row.pct.toFixed(0) }}%</template>
    <template v-if="row.detail">· {{ row.detail }}</template>
  </div>
</template>
