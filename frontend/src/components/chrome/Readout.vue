<script setup lang="ts">
import { computed } from "vue";

// "Display readout" — the typographic centerpiece. A large value flanked by
// a small unit/suffix and a caption. Pairs Fraunces (display) with mono
// (suffix) for the kind of mixed-typography moment that earns the chrome.
const props = withDefaults(
  defineProps<{
    value: string | number;
    /** Small mono suffix shown after the value — e.g. "条 / batch", "ms". */
    suffix?: string;
    /** Caption rendered below the value. */
    caption?: string;
    /** Color tone for the value glyph. */
    tone?: "default" | "good" | "warn" | "bad" | "primary";
    /** Visual size — `xl` is the dashboard hero size; `md` for inline use. */
    size?: "md" | "lg" | "xl";
  }>(),
  { tone: "default", size: "lg" },
);

const valueCls = computed(() =>
  ({
    default: "text-foreground",
    good: "text-success",
    warn: "text-warning",
    bad: "text-danger",
    primary: "text-primary",
  })[props.tone],
);

const sizeCls = computed(() =>
  ({
    md: "text-[26px] leading-none",
    lg: "text-[40px] leading-[0.95]",
    xl: "text-[56px] leading-[0.95]",
  })[props.size],
);
</script>

<template>
  <div class="space-y-1.5">
    <div class="flex items-baseline gap-2">
      <span :class="['font-display font-medium', sizeCls, valueCls]">
        {{ value }}
      </span>
      <span v-if="suffix" class="readout text-2xs text-muted-foreground">{{ suffix }}</span>
    </div>
    <div v-if="caption || $slots.caption" class="text-mini font-medium uppercase tracking-label text-muted-foreground">
      <slot name="caption">{{ caption }}</slot>
    </div>
  </div>
</template>
