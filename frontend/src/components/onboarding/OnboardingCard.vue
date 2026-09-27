<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import CardSection from "@/components/CardSection.vue";
import { Icon, type IconName } from "@/components/Icon";

// Reflects real cluster state: each step gets a ✓ once satisfied, the first
// incomplete step is highlighted as "next". Dashboard passes live status; with
// no status it degrades to a plain 3-step checklist (all pending).
const props = defineProps<{
  status?: { worker: boolean; bundle: boolean; batch: boolean };
}>();

type Step = {
  key: "worker" | "bundle" | "batch";
  icon: IconName;
  title: string;
  cta: { to: string; label: string };
};

const STEPS: Step[] = [
  { key: "worker", icon: "workers", title: "接入工作节点", cta: { to: "/workers", label: "前往工作节点" } },
  { key: "bundle", icon: "bundles", title: "上传任务包", cta: { to: "/bundles", label: "前往任务包" } },
  { key: "batch", icon: "pulse", title: "新建批次", cta: { to: "/batches", label: "前往批次" } },
];

const isDone = (k: Step["key"]) => props.status?.[k] ?? false;
const doneCount = computed(() => STEPS.filter((s) => isDone(s.key)).length);
// First not-yet-done step → the "next action"; -1 once everything is done.
const activeIndex = computed(() => STEPS.findIndex((s) => !isDone(s.key)));
</script>

<template>
  <CardSection
    title="开始使用"
    :description="`完成基础配置并创建首个批次 · ${doneCount}/3`"
  >
    <ol class="grid gap-4 md:grid-cols-3">
      <li
        v-for="(s, i) in STEPS"
        :key="s.key"
        :class="[
          'flex h-full flex-col rounded-lg border bg-muted/40 p-4 transition-colors',
          i === activeIndex
            ? 'border-primary/40 ring-1 ring-primary/30'
            : 'border-border hover:border-primary/30 hover:bg-muted/60',
          isDone(s.key) ? 'opacity-70' : '',
        ]"
      >
        <div class="flex items-center gap-2.5">
          <Badge
            v-if="isDone(s.key)"
            tone="acked"
            class="h-7 w-7 justify-center rounded-lg px-0"
            title="已完成"
          >
            <Icon name="check" :size="14" />
          </Badge>
          <Badge
            v-else
            variant="info"
            :class="[
              'h-7 w-7 justify-center rounded-lg px-0 text-[12.5px] font-semibold tabular-nums',
              i === activeIndex ? 'bg-primary/15 text-primary' : '',
            ]"
          >
            {{ i + 1 }}
          </Badge>
          <span class="text-muted-foreground"><Icon :name="s.icon" /></span>
          <span class="text-sm font-semibold text-foreground">{{ s.title }}</span>
        </div>
        <p class="mt-3 flex-1 text-xs leading-relaxed text-muted-foreground">
          <template v-if="i === 0">
            生成接入命令，在目标机器执行并完成注册。
          </template>
          <template v-else-if="i === 1">上传处理脚本、依赖与输入输出配置。</template>
          <template v-else>选择任务包，填写凭证并提交数据。</template>
        </p>
        <div class="mt-3">
          <span v-if="isDone(s.key)" class="text-2xs font-medium text-success">✓ 已完成</span>
          <Button v-else as-child :variant="i === activeIndex ? 'default' : 'outline'" size="sm">
            <RouterLink :to="s.cta.to">{{ s.cta.label }}</RouterLink>
          </Button>
        </div>
      </li>
    </ol>
  </CardSection>
</template>
