<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { computed } from "vue"
import type { BadgeTone, BadgeVariants } from "."
import { cn } from "@/lib/utils"
import { BADGE_TONES, badgeVariants } from "."

// `tone` is the project-level extension: state-driven color (GranuleState,
// EventLevel, etc.) — when set, it overrides the variant's bg/text via
// tailwind-merge while keeping the cva base (border-transparent, sizing).
// `dot` prepends a same-color status dot (Shadboard convention).
const props = defineProps<{
  variant?: BadgeVariants["variant"]
  tone?: BadgeTone | string
  dot?: boolean
  class?: HTMLAttributes["class"]
}>()

const toneClass = computed(() => {
  if (!props.tone) return undefined
  return Object.prototype.hasOwnProperty.call(BADGE_TONES, props.tone)
    ? BADGE_TONES[props.tone as BadgeTone]
    : BADGE_TONES.info
})
</script>

<template>
  <div :class="cn(badgeVariants({ variant }), toneClass, props.class)">
    <span v-if="dot" aria-hidden class="size-1.5 rounded-full bg-current opacity-70" />
    <slot />
  </div>
</template>
