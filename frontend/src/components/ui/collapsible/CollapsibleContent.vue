<script setup lang="ts">
import { CollapsibleContent, type CollapsibleContentProps, useForwardProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { cn } from "@/lib/utils"

const props = defineProps<CollapsibleContentProps & { class?: HTMLAttributes["class"] }>()
const delegatedProps = reactiveOmit(props, "class")
const forwarded = useForwardProps(delegatedProps)
</script>

<template>
  <CollapsibleContent
    v-bind="forwarded"
    :class="cn(
      'overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down',
      props.class,
    )"
  >
    <slot />
  </CollapsibleContent>
</template>
