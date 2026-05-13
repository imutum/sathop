<script setup lang="ts">
import type { ProgressRow } from "@/api";
import { fmtProgressStep } from "@/i18n";
import { Icon } from "@/components/Icon";

defineProps<{ row: ProgressRow }>();
</script>

<template>
  <div class="ml-4 mt-0.5 flex items-center gap-1 text-2xs text-muted-foreground">
    <Icon name="chevronRight" :size="10" :stroke-width="2.2" />
    <span>{{ fmtProgressStep(row.step) }}</span>
    <template v-if="row.pct != null"><span aria-hidden>·</span>{{ row.pct.toFixed(0) }}%</template>
    <template v-if="row.detail"><span aria-hidden>·</span>{{ row.detail }}</template>
  </div>
</template>
