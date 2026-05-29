<script setup lang="ts">
import { computed } from "vue";
import { useVersionCheck } from "@/composables/useVersionCheck";
import { Button } from "@/components/ui/button";
import HintTip from "@/components/HintTip.vue";
import { Icon } from "@/components/Icon";

// One visual anchor that fuses "检查 + 更新": the running version, a status dot
// comparing it to the latest GitHub release, a re-check button, and — only when
// behind — an inline 更新 action. Replaces the old passive version badge plus
// the update item buried two menus deep in the card footer.
const props = withDefaults(
  defineProps<{
    version: string;
    pending?: boolean;
    // Removed/disabled nodes show the version read-only (no check/update).
    actionable?: boolean;
    updateTitle?: string;
  }>(),
  { actionable: true },
);

const emit = defineEmits<{ (e: "update"): void }>();

const { latestTag, status, isFetching, refresh } = useVersionCheck(() => props.version);

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

const label = computed(() => {
  switch (status.value) {
    case "current":
      return "已是最新";
    case "outdated":
      return `有新版 ${latestTag.value}`;
    case "loading":
      return "检查中…";
    default:
      return "无法检查最新版本";
  }
});
</script>

<template>
  <div class="flex items-center gap-2 text-2xs">
    <HintTip :text="`节点运行版本（来自 sathop 包元数据）· ${label}`">
      <span class="inline-flex items-center gap-1.5">
        <span class="relative grid h-2 w-2 place-items-center">
          <span :class="['absolute inset-0 rounded-full', dotClass]" aria-hidden />
        </span>
        <span class="font-mono font-semibold text-foreground">v{{ version || "?" }}</span>
      </span>
    </HintTip>
    <span
      :class="['truncate', status === 'outdated' ? 'text-warning' : 'text-muted-foreground']"
    >
      {{ label }}
    </span>

    <div v-if="actionable" class="ml-auto flex items-center gap-1">
      <HintTip text="重新检查 GitHub 上的最新版本">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          class="h-6 w-6 text-muted-foreground hover:text-foreground"
          :disabled="isFetching"
          aria-label="检查更新"
          @click="refresh"
        >
          <Icon name="refresh" :size="12" :class="isFetching ? 'animate-spin' : ''" />
        </Button>
      </HintTip>
      <Button
        v-if="status === 'outdated'"
        type="button"
        variant="default"
        size="xs"
        :disabled="pending"
        :title="updateTitle ?? '拉取最新代码并重启该节点'"
        @click="emit('update')"
      >
        <Icon name="download" :size="11" />
        更新
      </Button>
    </div>
  </div>
</template>
