<script setup lang="ts">
import { CollapsibleTrigger, type CollapsibleTriggerProps, useForwardProps } from "reka-ui"

const props = defineProps<CollapsibleTriggerProps>()
const forwarded = useForwardProps(props)
</script>

<template>
  <CollapsibleTrigger v-bind="forwarded">
    <slot />
  </CollapsibleTrigger>
</template>
