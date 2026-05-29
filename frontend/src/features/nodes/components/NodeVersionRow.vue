<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { compareSemver } from "@/lib/semver";
import { Button } from "@/components/ui/button";
import HintTip from "@/components/HintTip.vue";
import { Icon } from "@/components/Icon";

// One visual anchor fusing "运行版本 + 是否与控制端一致 + 更新动作". The control
// plane (orchestrator) is the version anchor: a node is compared against the
// orchestrator's running version, NOT GitHub. The single global "is a newer
// release available?" check lives only in the sidebar VersionStatus, so there
// is no per-card GitHub re-check button here. Equal → 一致; differs → 不一致 +
// an inline 更新 action (drift remediation).
const props = withDefaults(
  defineProps<{
    version: string;
    pending?: boolean;
    // Removed/disabled nodes show the version read-only (no update action).
    actionable?: boolean;
    updateTitle?: string;
  }>(),
  { actionable: true },
);

const emit = defineEmits<{ (e: "update"): void }>();

// Shared, deduped, long-staleTime query — the orchestrator version is the anchor.
const orch = useQuery({
  queryKey: [...K.orchInfo],
  queryFn: API.orchestratorInfo,
  staleTime: 60 * 60 * 1000,
});
const target = computed(() => orch.data.value?.version ?? "");

type NodeVersionStatus = "match" | "drift" | "unknown";
// Equality judgment (not ordering): a node either matches the control plane or
// it doesn't. compareSemver tolerates a stray leading `v` / suffix; a node that
// somehow runs ahead of the orchestrator is still surfaced as 不一致.
const status = computed<NodeVersionStatus>(() => {
  if (!props.version || !target.value) return "unknown";
  return compareSemver(props.version, target.value) === 0 ? "match" : "drift";
});

const dotClass = computed(() => {
  switch (status.value) {
    case "match":
      return "bg-success";
    case "drift":
      return "bg-warning animate-pulse-soft";
    default:
      return "bg-muted-foreground";
  }
});

const label = computed(() => {
  switch (status.value) {
    case "match":
      return "与控制端一致";
    case "drift":
      return `与控制端不一致 v${target.value}`;
    default:
      return "版本未知";
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
      :class="['truncate', status === 'drift' ? 'text-warning' : 'text-muted-foreground']"
    >
      {{ label }}
    </span>

    <Button
      v-if="actionable && status === 'drift'"
      type="button"
      variant="default"
      size="xs"
      class="ml-auto"
      :disabled="pending"
      :title="updateTitle ?? '拉取最新代码并重启该节点'"
      @click="emit('update')"
    >
      <Icon name="download" :size="11" />
      更新
    </Button>
  </div>
</template>
