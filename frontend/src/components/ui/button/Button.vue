<script setup lang="ts">
import type { PrimitiveProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import type { ButtonVariants } from "."
import { Loader2Icon } from "lucide-vue-next"
import { Primitive } from "reka-ui"
import { cn } from "@/lib/utils"
import { buttonVariants } from "."

// `pending` + `pendingLabel` are project-level extensions (twins of the old
// ActionButton API). When pending, the button is disabled, shows a spinner,
// and renders `pendingLabel` (default "处理中…") instead of the slot.
interface Props extends PrimitiveProps {
  variant?: ButtonVariants["variant"]
  size?: ButtonVariants["size"]
  class?: HTMLAttributes["class"]
  pending?: boolean
  pendingLabel?: string
  type?: "button" | "submit" | "reset"
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  as: "button",
  type: "button",
})
</script>

<template>
  <Primitive
    :as="as"
    :as-child="asChild"
    :type="type"
    :disabled="disabled || pending"
    :aria-busy="pending || undefined"
    :class="cn(buttonVariants({ variant, size }), props.class)"
  >
    <Loader2Icon v-if="pending" class="size-3.5 animate-spin shrink-0" />
    <template v-if="pending">{{ pendingLabel ?? "处理中…" }}</template>
    <slot v-else />
  </Primitive>
</template>
