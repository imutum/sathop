<script setup lang="ts">
import { computed } from "vue";
import type { BatchSummary, GranuleState } from "@/api";
import { Button } from "@/components/ui/button";
import { operationStatus } from "../operationStatus";

const props = defineProps<{ summary: BatchSummary; restoring: boolean }>();
const emit = defineEmits<{ inspect: [state: GranuleState]; restore: [] }>();
const status = computed(() => operationStatus(props.summary));
</script>

<template>
  <div class="rounded-lg border border-border bg-muted/30 p-5">
    <div class="font-medium">{{ status.label }}</div>
    <p class="mt-1 text-sm leading-relaxed text-muted-foreground">{{ status.detail }}</p>
    <div class="mt-3 flex flex-wrap gap-2">
      <Button v-if="summary.objects_exhausted > 0" size="sm" :pending="restoring" @click="emit('restore')">恢复交付</Button>
      <Button v-if="(summary.counts.failed ?? 0) > 0" size="sm" variant="outline" @click="emit('inspect', 'failed')">查看失败 ({{ summary.counts.failed }})</Button>
      <Button v-if="(summary.counts.blacklisted ?? 0) > 0" size="sm" variant="outline" @click="emit('inspect', 'blacklisted')">核对已停止 ({{ summary.counts.blacklisted }})</Button>
      <Button v-if="(summary.counts.uploaded ?? 0) > 0" size="sm" variant="outline" @click="emit('inspect', 'uploaded')">查看待交付 ({{ summary.counts.uploaded }})</Button>
      <RouterLink v-if="(summary.counts.uploaded ?? 0) > 0" to="/receivers" class="inline-flex items-center px-2 text-sm text-primary hover:underline">检查接收端</RouterLink>
      <RouterLink v-if="(summary.counts.pending ?? 0) > 0 && summary.status !== 'paused'" to="/workers" class="inline-flex items-center px-2 text-sm text-primary hover:underline">检查工作节点</RouterLink>
    </div>
  </div>
</template>
