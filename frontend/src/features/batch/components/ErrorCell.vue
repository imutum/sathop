<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{ error: string | null }>();
const open = ref(false);

const isLong = computed(() => {
  const e = props.error;
  return !!e && (e.length > 80 || e.includes("\n"));
});
</script>

<template>
  <template v-if="error">
    <span v-if="!isLong">{{ error }}</span>
    <span v-else-if="!open" class="block">
      <span class="block truncate" title="点击查看完整错误">{{ error }}</span>
      <button
        type="button"
        @click="open = true"
        class="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger transition hover:bg-danger/25"
      >
        展开完整错误（{{ error.length }} 字符）
      </button>
    </span>
    <span v-else class="block">
      <pre class="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-danger/30 bg-danger/5 p-2.5 text-[11px]">{{ error }}</pre>
      <button
        type="button"
        @click="open = false"
        class="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger transition hover:bg-danger/25"
      >
        收起
      </button>
    </span>
  </template>
</template>
