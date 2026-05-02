<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";

// Live mission clock — UTC HH:MM:SS in mono, paired with a signal LED. Updates
// every second via a single shared interval per mounted instance. Used in the
// app top bar to make the console feel alive even on idle pages. We render
// UTC because all SatHop timestamps internally are UTC ISO; aligning the
// chrome avoids the operator having to mentally translate.

const props = withDefaults(
  defineProps<{
    /** When false, renders the LED in idle state (gray, no breathing). */
    live?: boolean;
    /** Hide the LED dot — pure clock. */
    bare?: boolean;
  }>(),
  { live: true, bare: false },
);

function fmt(): string {
  const d = new Date();
  const h = String(d.getUTCHours()).padStart(2, "0");
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  const s = String(d.getUTCSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

const now = ref(fmt());
const handle = window.setInterval(() => {
  now.value = fmt();
}, 1000);
onBeforeUnmount(() => window.clearInterval(handle));
</script>

<template>
  <span class="inline-flex items-center gap-2">
    <span
      v-if="!bare"
      :class="['signal-led', !props.live && 'signal-led--idle']"
      aria-hidden
    />
    <span class="readout text-2xs font-medium text-foreground/85">
      <span class="text-muted-foreground">UTC</span>
      <span class="ml-1.5 tabular-nums">{{ now }}</span>
    </span>
  </span>
</template>
