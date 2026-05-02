<script setup lang="ts">
import { computed } from "vue";
import type { EventRow } from "@/api";
import { fmtAge } from "@/i18n";
import { Icon, type IconName } from "@/components/Icon";

// Compact event timeline used by Dashboard / Settings / etc. Each row is:
//   ●(tone)  message · source · granule        ageAgo
// Icons + tone derive from the event level + a light keyword match on
// `source`, so worker / receiver / bundle events pick up topical icons
// without requiring a structured kind field on the wire.
const props = defineProps<{ events: EventRow[] }>();

type Tone = "good" | "warn" | "bad" | "info";

function iconFor(e: EventRow): { tone: Tone; icon: IconName } {
  if (e.level === "error") return { tone: "bad", icon: "alert" };
  if (e.level === "warn") return { tone: "warn", icon: "alert" };
  const src = e.source.toLowerCase();
  if (src.startsWith("worker") || src === "lease") return { tone: "info", icon: "workers" };
  if (src.startsWith("receiver")) return { tone: "info", icon: "receivers" };
  if (src.startsWith("bundle")) return { tone: "info", icon: "bundles" };
  return { tone: "good", icon: "check" };
}

const TILE: Record<Tone, string> = {
  good: "bg-success/10 text-success",
  warn: "bg-warning/10 text-warning",
  bad: "bg-danger/10 text-danger",
  info: "bg-primary/10 text-primary",
};

const items = computed(() =>
  props.events.map((e) => ({ e, ...iconFor(e) })),
);
</script>

<template>
  <ul class="divide-y divide-border/60">
    <li
      v-for="{ e, tone, icon } in items"
      :key="e.id"
      class="flex items-start gap-3 px-5 py-3 transition hover:bg-muted/40"
    >
      <span
        :class="['grid h-8 w-8 shrink-0 place-items-center rounded-full', TILE[tone]]"
        aria-hidden
      >
        <Icon :name="icon" :size="14" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="truncate text-sm font-medium text-foreground" :title="e.message">
          {{ e.message }}
        </div>
        <div class="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          <span class="font-mono" :title="e.source">{{ e.source }}</span>
          <template v-if="e.granule_id">
            <span aria-hidden>·</span>
            <span class="font-mono">{{ e.granule_id }}</span>
          </template>
        </div>
      </div>
      <span class="shrink-0 text-xs text-muted-foreground tabular-nums">{{ fmtAge(e.ts) }}</span>
    </li>
  </ul>
</template>
