<script setup lang="ts">
import { computed, ref } from "vue";
import HintTip from "@/components/HintTip.vue";
import { Icon } from "./Icon";

const props = defineProps<{ value: string; title?: string }>();
const copied = ref(false);

// Tooltip text mirrors the prior native title= behavior, but flips to
// "已复制" briefly after a successful copy so the visible feedback matches
// the screen-reader live-region announcement below.
const hint = computed(() => (copied.value ? "已复制" : props.title ?? "复制"));

function onCopy(e: MouseEvent) {
  e.preventDefault();
  e.stopPropagation();
  void navigator.clipboard.writeText(props.value).then(() => {
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 1400);
  });
}
</script>

<template>
  <HintTip :text="hint">
    <button
      type="button"
      @click="onCopy"
      :aria-label="title ?? '复制'"
      :class="[
        'ml-1 inline-grid h-5 w-5 place-items-center rounded-md transition',
        copied ? 'text-success' : 'text-muted-foreground/60 hover:bg-muted hover:text-foreground',
      ]"
    >
      <Icon
        :name="copied ? 'check' : 'clipboard'"
        :size="11"
        :stroke-width="copied ? 2.4 : 2"
      />
      <!-- Live-region announcement so screen readers confirm the copy. -->
      <span class="sr-only" aria-live="polite">{{ copied ? "已复制" : "" }}</span>
    </button>
  </HintTip>
</template>
