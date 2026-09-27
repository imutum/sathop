<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { X } from "lucide-vue-next"
import {
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = withDefaults(defineProps<DialogContentProps & { class?: HTMLAttributes["class"]; layer?: number }>(), { layer: 50 })
const emits = defineEmits<DialogContentEmits>()

const delegatedProps = reactiveOmit(props, "class", "layer")

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <DialogPortal>
    <DialogOverlay
      :style="{ zIndex: layer }"
      class="surface-overlay data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
    />
    <DialogContent
      v-bind="forwarded"
      :style="{ zIndex: layer }"
      :class="
        cn(
          'fixed left-1/2 top-1/2 grid w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-5 rounded-2xl border border-border bg-card p-6 text-card-foreground shadow-pop duration-150 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
          props.class,
        )"
    >
      <slot />

      <DialogClose
        class="dialog-close"
      >
        <X class="w-4 h-4" />
        <span class="sr-only">关闭弹窗</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
