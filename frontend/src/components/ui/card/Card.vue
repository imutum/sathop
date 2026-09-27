<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
</script>

<template>
  <div
    :class="
      cn(
      'min-w-0 rounded-2xl border border-border bg-card text-card-foreground shadow-soft',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
