<script setup lang="ts">
import type { TabsListProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TabsList, useForwardProps } from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<TabsListProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")
const forwarded = useForwardProps(delegatedProps)
</script>

<template>
  <TabsList
    v-bind="forwarded"
    :class="cn(
      'inline-flex h-9 items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5 text-muted-foreground',
      props.class,
    )"
  >
    <slot />
  </TabsList>
</template>
