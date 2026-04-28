<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{ size?: number }>(), { size: 14 });
const borderWidth = computed(() => Math.max(1, Math.round(props.size / 7)));
</script>

<template>
  <span
    class="inline-block animate-spin rounded-full border-2 border-current border-t-transparent"
    :style="{ width: `${size}px`, height: `${size}px`, borderWidth: `${borderWidth}px` }"
    aria-hidden
  />
</template>
