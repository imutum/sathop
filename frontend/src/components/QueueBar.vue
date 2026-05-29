<script setup lang="ts">
import { computed } from "vue";
import type { WorkerInfo } from "@/api";
import HintTip from "@/components/HintTip.vue";

// 队列 6 阶段缩略条：一根细的水平堆叠条 + 旁边总数。各阶段配不同色调，
// hover 出精确 per-stage 数字。total=0 → 中性空条。
const props = defineProps<{ worker: WorkerInfo }>();

// 顺序、文案、色调与 WorkerCard 的 6 格栅格一致。
const STAGES = [
  { key: "queue_pending_download", label: "待下载", color: "bg-amber-500/70" },
  { key: "queue_downloading", label: "下载中", color: "bg-sky-500/70" },
  { key: "queue_pending_processing", label: "待处理", color: "bg-indigo-400/60" },
  { key: "queue_processing", label: "处理中", color: "bg-indigo-500/80" },
  { key: "queue_pending_upload", label: "待上传", color: "bg-violet-400/60" },
  { key: "queue_uploading", label: "上传中", color: "bg-violet-500/80" },
] as const;

const segs = computed(() => STAGES.map((s) => ({ ...s, n: props.worker[s.key] })));
const total = computed(() => segs.value.reduce((a, s) => a + s.n, 0));
const tip = computed(() => segs.value.map((s) => `${s.label} ${s.n}`).join(" · "));
</script>

<template>
  <HintTip :text="tip">
    <span class="inline-flex items-center gap-1.5">
      <span class="flex h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <template v-if="total > 0">
          <span
            v-for="s in segs"
            v-show="s.n > 0"
            :key="s.key"
            :class="['h-full', s.color]"
            :style="{ width: `${(s.n / total) * 100}%` }"
          />
        </template>
      </span>
      <span class="tabular-nums text-2xs text-muted-foreground">{{ total }}</span>
    </span>
  </HintTip>
</template>
