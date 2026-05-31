<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { Button } from "@/components/ui/button";

const toast = useToast();
const info = useQuery({
  queryKey: [...K.orchInfo],
  queryFn: API.orchestratorInfo,
  staleTime: 60 * 60 * 1000,
});
// Live-updates via the SSE `rollout` scope; the interval is a safety net + the
// wave-deadline progress ticker.
const rollout = useQuery({ queryKey: [...K.rollout], queryFn: API.rolloutStatus, refetchInterval: 5000 });

const r = computed(() => rollout.data.value);
const orchVersion = computed(() => info.data.value?.version ?? "");
const active = computed(() => r.value?.active ?? false);
const halted = computed(() => r.value?.phase === "halted");
const busy = ref(false);

const WAVE_CN: Record<string, string> = { canary: "金丝雀", batch: "批量", fleet: "全量" };
const phaseLabel = computed(() => {
  const v = r.value;
  if (!v?.phase) return "—";
  switch (v.phase) {
    case "pending":
      return "准备中";
    case "running":
      return `进行中 · ${WAVE_CN[v.wave ?? ""] ?? v.wave ?? ""}波`;
    case "halted":
      return "已暂停（本波超时未确认）";
    case "done":
      return "已完成";
    case "aborted":
      return "已中止";
    default:
      return v.phase;
  }
});

async function start() {
  const target = orchVersion.value;
  if (!target) {
    toast.error("无法读取 Orchestrator 版本");
    return;
  }
  const ok = await requestConfirm({
    title: `分阶段升级机群到 v${target}？`,
    description:
      "先升 1 台金丝雀，确认它按新版本回报存活后再放量到批量、最后全量。" +
      "任一波在时限内未确认即暂停（不自动回滚——单机崩溃由本地 A/B 槽兜底）。",
    confirmText: "开始升级",
  });
  if (!ok) return;
  busy.value = true;
  try {
    await API.startRollout({ target_version: target });
    toast.success(`已开始分阶段升级到 v${target}`);
    await rollout.refetch();
  } catch (e: any) {
    toast.error(`无法开始：${e.message ?? e}`);
  } finally {
    busy.value = false;
  }
}

async function abort() {
  const ok = await requestConfirm({
    title: "中止当前升级？",
    description: "停止继续放量；已升级的 worker 保持新版本（不回滚）。",
    confirmText: "中止",
    tone: "danger",
  });
  if (!ok) return;
  busy.value = true;
  try {
    await API.abortRollout();
    toast.success("已中止升级");
    await rollout.refetch();
  } catch (e: any) {
    toast.error(`中止失败：${e.message ?? e}`);
  } finally {
    busy.value = false;
  }
}

async function resume() {
  busy.value = true;
  try {
    await API.resumeRollout();
    toast.success("已恢复，重新放量");
    await rollout.refetch();
  } catch (e: any) {
    toast.error(`恢复失败：${e.message ?? e}`);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <!-- Inactive: offer to roll the fleet up to the orchestrator's own version
       (always satisfies orch-before-worker). -->
  <div v-if="!active" class="flex flex-wrap items-center gap-3">
    <Button
      variant="default"
      size="sm"
      :pending="busy"
      pending-label="启动中…"
      :disabled="!orchVersion"
      @click="start"
    >
      分阶段升级机群到 v{{ orchVersion || "?" }}
    </Button>
    <span v-if="r?.phase" class="text-2xs text-muted-foreground">
      上次：v{{ r.target_version }} · {{ phaseLabel }}
    </span>
  </div>

  <!-- Active: live status + abort / resume. -->
  <div v-else class="space-y-3">
    <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      <div class="flex items-baseline gap-2">
        <span class="text-2xs tracking-label text-muted-foreground">目标</span>
        <span class="font-mono text-foreground">v{{ r?.target_version }}</span>
        <span
          v-if="r?.channel"
          class="rounded bg-warning/15 px-1 py-0.5 font-mono text-2xs text-warning"
          >{{ r.channel }}</span
        >
      </div>
      <div class="flex items-baseline gap-2">
        <span class="text-2xs tracking-label text-muted-foreground">阶段</span>
        <span :class="halted ? 'text-warning' : 'text-foreground'">{{ phaseLabel }}</span>
      </div>
      <div v-if="r?.members" class="flex items-baseline gap-2">
        <span class="text-2xs tracking-label text-muted-foreground">本波</span>
        <span class="text-success">{{ r.members.confirmed }} 已确认</span>
        <span class="text-muted-foreground">·</span>
        <span :class="r.members.pending ? 'text-warning' : 'text-muted-foreground'"
          >{{ r.members.pending }} 待确认</span
        >
        <span v-if="r.members.excused" class="text-muted-foreground">· {{ r.members.excused }} 已豁免</span>
      </div>
    </div>

    <div
      v-if="halted && r?.halt_reason"
      class="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-2xs text-warning"
    >
      {{ r.halt_reason }}
    </div>

    <div class="flex items-center gap-2">
      <Button v-if="halted" variant="default" size="sm" :pending="busy" pending-label="恢复中…" @click="resume">
        恢复并继续
      </Button>
      <Button variant="outline" size="sm" :pending="busy" pending-label="中止中…" @click="abort">中止</Button>
    </div>
  </div>
</template>
