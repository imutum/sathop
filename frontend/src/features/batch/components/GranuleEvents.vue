<script setup lang="ts">
import { computed } from "vue";
import type { EventRow } from "@/api";
import { fmtAge, levelLabel } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { stripBatchPrefix } from "@/lib/utils";

// Pure presentational — fed by useGranuleDetail via GranuleExpandedDetail.
// granuleId/batchId kept only for the stripped label + the "全屏" deep link.
const props = defineProps<{ rows: EventRow[]; granuleId: string; batchId: string }>();

const stripped = computed(() => stripBatchPrefix(props.granuleId, props.batchId));
</script>

<template>
  <div>
    <div class="mb-1.5 flex items-baseline gap-2">
      <span class="stat-label">
        事件 · 仅本数据粒
      </span>
      <RouterLink
        :to="`/events?q=${encodeURIComponent(stripped)}`"
        class="text-mini text-muted-foreground transition-colors hover:text-primary"
      >
        全屏 →
      </RouterLink>
    </div>
    <div v-if="rows.length === 0" class="text-2xs text-muted-foreground">暂无事件</div>
    <ul
      v-else
      class="max-h-56 space-y-1 overflow-auto rounded-lg border border-border/60 bg-background/40 p-2 font-mono"
    >
      <li v-for="e in rows" :key="e.id" class="flex items-start gap-2 text-2xs">
        <span class="w-16 shrink-0 text-muted-foreground">{{ fmtAge(e.ts) }}</span>
        <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
        <span class="w-24 shrink-0 truncate text-muted-foreground" :title="e.source">{{ e.source }}</span>
        <span class="flex-1 break-all whitespace-pre-wrap">{{ e.message }}</span>
      </li>
    </ul>
  </div>
</template>
