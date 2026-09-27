<script setup lang="ts">
import { computed } from "vue";
import type { WorkerInfo } from "@/api";
import HintTip from "@/components/HintTip.vue";
import { WORKER_QUEUE_STAGES } from "@/features/nodes/workerQueue";

// 队列 6 阶段缩略条：一根细的水平堆叠条 + 旁边总数。各阶段配不同色调，
// hover 出精确 per-stage 数字。total=0 → 中性空条。
const props = defineProps<{ worker: WorkerInfo }>();

const segs = computed(() => WORKER_QUEUE_STAGES.map((stage) => ({ ...stage, n: props.worker[stage.key] })));
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
