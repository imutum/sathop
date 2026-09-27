<script setup lang="ts">
import { computed, ref } from "vue";
import type { BundleSummary } from "@/api";
import { fmtBytes } from "@/lib/format";
import { fmtAge } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/Icon";
import TextInput from "@/ui/TextInput.vue";

const props = defineProps<{
  bundles: BundleSummary[];
  selected: { name: string; version: string } | null;
}>();
const emit = defineEmits<{ select: [bundle: BundleSummary] }>();
const search = ref("");
const visible = computed(() => {
  const needle = search.value.trim().toLowerCase();
  return props.bundles.filter(b => `${b.name}@${b.version}`.toLowerCase().includes(needle));
});
function isSelected(bundle: BundleSummary) {
  return props.selected?.name === bundle.name && props.selected.version === bundle.version;
}
</script>

<template>
  <div class="border-b border-border/70 p-4">
    <div class="mb-3 flex items-center justify-between gap-3">
      <h2 class="text-sm font-medium">任务包目录</h2>
      <span class="text-2xs tabular-nums text-muted-foreground">{{ visible.length }} / {{ bundles.length }} 个版本</span>
    </div>
    <TextInput v-model="search" aria-label="搜索任务包" placeholder="搜索名称或版本">
      <template #leftIcon><Icon name="search" :size="13" /></template>
    </TextInput>
  </div>
  <ul v-if="visible.length" class="divide-y divide-border/60 xl:max-h-[calc(100dvh-320px)] xl:overflow-y-auto">
    <li v-for="bundle in visible" :key="`${bundle.name}@${bundle.version}`">
      <button
        type="button"
        :aria-label="`${bundle.name}@${bundle.version}`"
        :aria-pressed="isSelected(bundle)"
        :class="[
          'w-full border-l-2 px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
          isSelected(bundle) ? 'border-l-primary bg-accent/60' : 'border-l-transparent hover:bg-muted/50',
        ]"
        @click="emit('select', bundle)"
      >
        <span class="block font-mono text-[12px] font-medium leading-relaxed [overflow-wrap:anywhere]">{{ bundle.name }}</span>
        <span class="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-2xs text-muted-foreground">
          <Badge tone="info" class="font-mono">v{{ bundle.version }}</Badge>
          <span class="whitespace-nowrap tabular-nums">{{ fmtBytes(bundle.size) }}</span>
          <span class="whitespace-nowrap">{{ fmtAge(bundle.uploaded_at) }}上传</span>
          <span v-if="bundle.in_use_count" class="ml-auto whitespace-nowrap text-primary">{{ bundle.in_use_count }} 个批次</span>
        </span>
      </button>
    </li>
  </ul>
  <div v-else class="px-4 py-10 text-center text-sm text-muted-foreground">
    <p>没有匹配的任务包</p>
    <Button variant="ghost" size="sm" class="mt-3" @click="search = ''">清除搜索</Button>
  </div>
</template>
