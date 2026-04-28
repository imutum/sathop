<script setup lang="ts">
import { ref } from "vue";
import { Icon } from "./Icon";

const props = defineProps<{ value: string; title?: string }>();
const copied = ref(false);

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
  <button
    type="button"
    @click="onCopy"
    :title="title ?? '复制'"
    :aria-label="title ?? '复制'"
    :class="[
      'ml-1 inline-grid h-5 w-5 place-items-center rounded-md transition',
      copied ? 'text-success' : 'text-muted/60 hover:bg-subtle hover:text-text',
    ]"
  >
    <Icon
      :name="copied ? 'check' : 'clipboard'"
      :size="11"
      :stroke-width="copied ? 2.4 : 2"
    />
  </button>
</template>
