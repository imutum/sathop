<script setup lang="ts">
import { Badge } from "@/components/ui/badge";
defineProps<{ label: string; mono?: boolean; hint?: string }>();
</script>

<template>
  <div class="min-w-0">
    <div class="text-mini font-medium tracking-label text-muted-foreground">
      {{ label }}
    </div>
    <div
      :class="[
        'mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1',
        mono ? 'font-mono text-cell' : 'text-sm',
      ]"
    >
      <span class="min-w-0 break-words"><slot /></span>
      <Badge v-if="hint" tone="warn" class="font-mono text-mini">
        {{ hint }}
      </Badge>
    </div>
  </div>
</template>
