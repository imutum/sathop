<script setup lang="ts">
import type { EventRow } from "@/api";
import { fmtAge, levelLabel } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import EmptyState from "@/components/EmptyState.vue";

const props = defineProps<{
  events: EventRow[];
  batchId: string;
}>();

function stripBatchPrefix(gid: string) {
  return gid.startsWith(`${props.batchId}:`) ? gid.slice(props.batchId.length + 1) : gid;
}
</script>

<template>
  <div class="max-h-[50vh] overflow-auto font-mono">
    <EmptyState v-if="events.length === 0" title="暂无该批次的事件" />
    <ul v-else class="divide-y divide-border/50">
      <li
        v-for="e in events"
        :key="e.id"
        class="flex items-start gap-3 px-5 py-2 text-[11.5px] transition hover:bg-muted/40"
      >
        <span class="w-20 shrink-0 text-muted-foreground">{{ fmtAge(e.ts) }}</span>
        <Badge :tone="e.level" dot>{{ levelLabel(e.level) }}</Badge>
        <span class="w-24 shrink-0 truncate text-muted-foreground">{{ e.source }}</span>
        <span
          v-if="e.granule_id"
          class="w-40 shrink-0 truncate text-muted-foreground"
          :title="e.granule_id"
        >
          {{ stripBatchPrefix(e.granule_id) }}
        </span>
        <span v-else class="w-40 shrink-0 text-muted-foreground">—</span>
        <span class="flex-1 break-all">{{ e.message }}</span>
      </li>
    </ul>
  </div>
</template>
