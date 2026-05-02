<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { fmtBytes } from "@/lib/format";
import { Alert, AlertDescription } from "@/components/ui/alert";

const props = defineProps<{ name: string; version: string }>();
const sel = ref("manifest.yaml");

const files = useQuery({
  queryKey: computed(() => ["bundle-files", props.name, props.version]),
  queryFn: () => API.bundleFiles(props.name, props.version),
});

const content = useQuery({
  queryKey: computed(() => ["bundle-file", props.name, props.version, sel.value]),
  queryFn: () => API.bundleFile(props.name, props.version, sel.value),
  enabled: computed(() => !!sel.value),
});

function parts(path: string) {
  const ps = path.split("/");
  return { depth: ps.length - 1, leaf: ps[ps.length - 1], dir: ps.slice(0, -1).join("/") };
}
</script>

<template>
  <div v-if="files.isLoading.value" class="py-4 text-xs text-muted-foreground">加载文件列表…</div>
  <Alert v-else-if="files.isError.value" variant="destructive">
    <AlertDescription>无法列出文件：{{ (files.error.value as Error).message }}</AlertDescription>
  </Alert>
  <div v-else-if="(files.data.value?.length ?? 0) === 0" class="py-4 text-xs text-muted-foreground">
    （包为空）
  </div>
  <div v-else class="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(180px,280px)_1fr]">
    <ul class="max-h-[420px] overflow-auto rounded-lg border border-border bg-muted/40 py-1">
      <li v-for="f in files.data.value ?? []" :key="f.path">
        <button
          @click="sel = f.path"
          :title="f.path"
          :style="{ paddingLeft: `${8 + parts(f.path).depth * 14}px` }"
          :class="[
            'flex w-full items-center justify-between px-2 py-1 text-left font-mono text-2xs transition',
            f.path === sel
              ? 'bg-accent text-primary'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          ]"
        >
          <span class="truncate">
            <span v-if="parts(f.path).depth > 0" class="mr-1 select-none text-muted-foreground/50">└</span>
            {{ parts(f.path).leaf }}
            <span v-if="parts(f.path).dir" class="ml-2 text-3xs text-muted-foreground/60">
              {{ parts(f.path).dir }}/
            </span>
          </span>
          <span class="ml-2 shrink-0 text-3xs text-muted-foreground">{{ fmtBytes(f.size) }}</span>
        </button>
      </li>
    </ul>
    <div class="rounded-lg border border-border bg-muted/30">
      <div v-if="content.isLoading.value" class="p-3 text-xs text-muted-foreground">加载 {{ sel }}…</div>
      <div v-else-if="content.isError.value" class="p-3 text-xs text-danger">
        读取失败：{{ (content.error.value as Error).message }}
      </div>
      <div v-else-if="content.data.value">
        <div class="flex items-center justify-between border-b border-border px-3 py-2 text-2xs text-muted-foreground">
          <span class="font-mono">{{ content.data.value.path }}</span>
          <span class="flex gap-2">
            <span class="tabular-nums">{{ fmtBytes(content.data.value.size) }}</span>
            <span v-if="content.data.value.truncated" class="text-warning">
              已截断（512 KB 上限）
            </span>
          </span>
        </div>
        <div v-if="content.data.value.binary" class="p-3 text-xs text-muted-foreground">
          二进制文件，无法预览。
        </div>
        <pre
          v-else
          class="max-h-[400px] overflow-auto whitespace-pre p-3 font-mono text-2xs leading-relaxed"
        >{{ content.data.value.content }}</pre>
      </div>
    </div>
  </div>
</template>
