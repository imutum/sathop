<script setup lang="ts">
import { fmtDuration } from "@/i18n";
import ProgressBar from "@/components/ProgressBar.vue";

defineProps<{
  done: number;
  total: number;
  pct: number;
  etaRealtime: number | null;
  inFlight: number;
  errors: number;
  exhausted: number;
}>();
</script>

<template>
  <div>
    <div class="mb-1 flex flex-wrap items-center justify-between gap-2 text-cell">
      <span class="tabular-nums">
        <span class="font-medium text-foreground">{{ done }}</span>
        <span class="text-muted-foreground"> / {{ total }}</span>
        <span class="ml-1 text-muted-foreground">({{ pct }}%)</span>
      </span>
      <span class="flex items-center gap-2">
        <span
          v-if="etaRealtime != null"
          class="text-muted-foreground tabular-nums"
          :title="`按最近 1 分钟交付速率估算，未上传完成 ${inFlight} 条`"
        >
          ≈ {{ fmtDuration(etaRealtime * 1000) }}
        </span>
        <span v-if="errors > 0" class="text-danger">失败 / 已停止 {{ errors }}</span>
        <span
          v-if="exhausted > 0"
          class="text-danger"
          title="产物已达到拉取重试上限，可在批次详情中恢复交付"
        >
          交付受阻 {{ exhausted }}
        </span>
      </span>
    </div>
    <ProgressBar
      :value="done"
      :max="total"
      :tone="errors > 0 || exhausted > 0 ? 'warn' : 'good'"
    />
  </div>
</template>
