<script setup lang="ts">
import HintTip from "@/components/HintTip.vue";
import { Icon } from "@/components/Icon";
defineProps<{ label: string; mono?: boolean; hint?: string }>();
</script>

<template>
  <div class="min-w-0">
    <div class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      {{ label }}
      <HintTip v-if="hint" :text="`环境变量：${hint}`">
        <button type="button" class="rounded text-muted-foreground/70 hover:text-foreground" :aria-label="`${label}的环境变量：${hint}`">
          <Icon name="info" :size="13" />
        </button>
      </HintTip>
    </div>
    <div
      :class="[
        'mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1',
        mono ? 'font-mono text-cell' : 'text-sm',
      ]"
    >
      <span class="min-w-0 break-words"><slot /></span>
    </div>
  </div>
</template>
