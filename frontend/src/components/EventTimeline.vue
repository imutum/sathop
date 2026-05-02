<script setup lang="ts">
import { computed } from "vue";
import type { EventRow } from "@/api";
import { fmtAge } from "@/i18n";
import { Icon, type IconName } from "@/components/Icon";

// Telemetry log strip — each row is a single instrument trace: timecode +
// channel code + payload. The status icon is encoded as a tiny
// monogram-style square instead of a chip.
const props = defineProps<{ events: EventRow[] }>();

type Tone = "good" | "warn" | "bad" | "info";

function iconFor(e: EventRow): { tone: Tone; icon: IconName; tag: string } {
  if (e.level === "error") return { tone: "bad", icon: "alert", tag: "ERR" };
  if (e.level === "warn") return { tone: "warn", icon: "alert", tag: "WRN" };
  const src = e.source.toLowerCase();
  if (src.startsWith("worker") || src === "lease") return { tone: "info", icon: "workers", tag: "WRK" };
  if (src.startsWith("receiver")) return { tone: "info", icon: "receivers", tag: "RCV" };
  if (src.startsWith("bundle")) return { tone: "info", icon: "bundles", tag: "BND" };
  return { tone: "good", icon: "check", tag: "OK" };
}

const TILE: Record<Tone, string> = {
  good: "bg-success/10 text-success border-success/30",
  warn: "bg-warning/10 text-warning border-warning/30",
  bad: "bg-danger/10 text-danger border-danger/30",
  info: "bg-primary/10 text-primary border-primary/30",
};

const items = computed(() =>
  props.events.map((e) => ({ e, ...iconFor(e) })),
);
</script>

<template>
  <ul class="divide-y divide-border/60">
    <li
      v-for="{ e, tone, icon, tag } in items"
      :key="e.id"
      class="flex items-start gap-3 px-5 py-3 transition hover:bg-muted/40"
    >
      <span
        :class="['grid h-9 w-9 shrink-0 place-items-center rounded-sm border', TILE[tone]]"
        :title="tag"
        aria-hidden
      >
        <Icon :name="icon" :size="14" :stroke-width="1.6" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2 truncate text-[13px] text-foreground" :title="e.message">
          <span
            :class="[
              'readout shrink-0 rounded-sm border px-1 py-px text-3xs font-semibold uppercase tracking-wider',
              TILE[tone],
            ]"
            aria-hidden
          >
            {{ tag }}
          </span>
          <span class="truncate font-medium">{{ e.message }}</span>
        </div>
        <div class="mt-0.5 flex items-center gap-1.5 truncate text-3xs text-muted-foreground readout">
          <span :title="e.source">{{ e.source }}</span>
          <template v-if="e.granule_id">
            <span aria-hidden class="opacity-50">·</span>
            <span>{{ e.granule_id }}</span>
          </template>
        </div>
      </div>
      <span class="readout shrink-0 text-3xs text-muted-foreground tabular-nums">{{ fmtAge(e.ts) }}</span>
    </li>
  </ul>
</template>
