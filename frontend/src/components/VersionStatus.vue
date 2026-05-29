<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { useVersionCheck } from "@/composables/useVersionCheck";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Icon } from "@/components/Icon";

defineProps<{ collapsed?: boolean }>();

const info = useQuery({
  queryKey: [...K.orchInfo],
  queryFn: API.orchestratorInfo,
  staleTime: 60 * 60 * 1000,
});

// Shared version check — same GitHub query the node cards use.
const { latestTag, status, htmlUrl, isFetching, refresh: refreshLatest } = useVersionCheck(
  () => info.data.value?.version,
);
const currentVersion = computed(() => info.data.value?.version ?? "");
const busy = computed(() => info.isFetching.value || isFetching.value);

const statusLabel = computed(() => {
  switch (status.value) {
    case "current":
      return "已是最新版本";
    case "outdated":
      return `有新版本 ${latestTag.value} 可用`;
    case "loading":
      return "正在检查更新…";
    default:
      return "无法访问 GitHub（网络或限流）";
  }
});

const dotClass = computed(() => {
  switch (status.value) {
    case "current":
      return "bg-success";
    case "outdated":
      return "bg-warning animate-pulse-soft";
    case "loading":
      return "bg-muted-foreground animate-pulse-soft";
    default:
      return "bg-muted-foreground";
  }
});

function refresh() {
  void info.refetch();
  refreshLatest();
}
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <button
        type="button"
        :title="collapsed ? `${currentVersion || '?'} · ${statusLabel}` : undefined"
        :class="[
          'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
          collapsed ? 'justify-center' : '',
        ]"
      >
        <span class="relative grid h-2 w-2 shrink-0 place-items-center">
          <span :class="['absolute inset-0 rounded-full', dotClass]" />
        </span>
        <span v-if="!collapsed" class="truncate font-mono">
          {{ currentVersion ? `v${currentVersion}` : "—" }}
        </span>
        <!-- Outdated is actionable: surface it on the always-visible button too,
             not only inside the popover. -->
        <Icon
          v-if="!collapsed && status === 'outdated'"
          name="alert"
          :size="12"
          class="ml-auto text-warning"
        />
      </button>
    </PopoverTrigger>
    <PopoverContent side="top" align="start" class="w-64">
      <div class="flex items-center justify-between">
        <div class="text-2xs font-medium tracking-label text-muted-foreground">
          当前版本
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          class="h-6 w-6 text-muted-foreground"
          :disabled="busy"
          title="重新检查"
          aria-label="重新检查"
          @click="refresh"
        >
          <Icon name="refresh" :size="13" :class="busy ? 'animate-spin' : ''" />
        </Button>
      </div>

      <div class="mt-2 flex items-baseline gap-2">
        <span class="font-mono text-2xl font-semibold text-foreground">
          {{ currentVersion ? `v${currentVersion}` : "—" }}
        </span>
        <span class="relative grid h-2.5 w-2.5 place-items-center">
          <span :class="['absolute inset-0 rounded-full', dotClass]" />
        </span>
      </div>

      <div class="mt-1 text-xs text-muted-foreground">{{ statusLabel }}</div>

      <div
        v-if="status === 'outdated'"
        class="mt-2 rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-2xs text-warning"
      >
        最新发布版本：<span class="font-mono">{{ latestTag }}</span>
      </div>

      <!-- Check + update live together: when behind, the path to the update
           action is one click away (Settings hosts the orchestrator restart). -->
      <Button
        v-if="status === 'outdated'"
        as-child
        variant="default"
        size="sm"
        class="mt-3 w-full"
      >
        <RouterLink to="/settings">
          <Icon name="download" :size="13" />
          前往更新并重启
        </RouterLink>
      </Button>

      <Button as-child variant="outline" size="sm" class="mt-2 w-full">
        <a :href="htmlUrl" target="_blank" rel="noopener noreferrer">
          <Icon name="github" :size="13" />
          查看发布
          <Icon name="external" :size="11" class="text-muted-foreground" />
        </a>
      </Button>
    </PopoverContent>
  </Popover>
</template>
