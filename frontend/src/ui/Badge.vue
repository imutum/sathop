<script setup lang="ts">
import { computed } from "vue";
import { BADGE_TONES, type BadgeTone } from "./format";

const props = defineProps<{
  // Accept any string so callers can pass GranuleState / event level / etc.
  // Unknown tones fall back to muted.
  tone?: BadgeTone | string;
  dot?: boolean;
}>();

const cls = computed(() => {
  const t = props.tone;
  if (t && Object.prototype.hasOwnProperty.call(BADGE_TONES, t)) {
    return BADGE_TONES[t as BadgeTone];
  }
  return "bg-legacy-subtle text-legacy-muted ring-border";
});
</script>

<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
      cls,
    ]"
  >
    <span v-if="dot" class="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
    <slot />
  </span>
</template>
