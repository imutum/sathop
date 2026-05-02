<script setup lang="ts">
// Thin wrapper around shadcn's Tooltip primitives — hides the four-element
// boilerplate (Tooltip / TooltipTrigger / TooltipContent + as-child) and
// renders only when there is text to show, so call sites can stay close to
// the native `title=""` ergonomics they're replacing.
//
// Usage:
//   <HintTip text="复制 batch ID">
//     <CopyButton :value="b.batch_id" />
//   </HintTip>
//
// The trigger is `as-child`, so the slotted element keeps its tag/role/
// attributes and the tooltip just attaches behavior. Empty `text` collapses
// to a passthrough so the wrapper is safe to leave in place when the label
// is conditional.

import { computed } from "vue";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const props = withDefaults(
  defineProps<{
    text?: string | null;
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    /** Skip the tooltip wrapper entirely when text is falsy (default true). */
    passthroughEmpty?: boolean;
  }>(),
  { side: "top", align: "center", passthroughEmpty: true },
);

const enabled = computed(() => !(props.passthroughEmpty && !props.text));
</script>

<template>
  <slot v-if="!enabled" />
  <Tooltip v-else>
    <TooltipTrigger as-child>
      <slot />
    </TooltipTrigger>
    <TooltipContent :side="side" :align="align">
      {{ text }}
    </TooltipContent>
  </Tooltip>
</template>
