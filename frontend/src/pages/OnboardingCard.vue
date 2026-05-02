<script setup lang="ts">
import ActionButton from "../ui/ActionButton.vue";
import Card from "../ui/Card.vue";
import { Icon, type IconName } from "../ui/Icon";

type Step = {
  icon: IconName;
  title: string;
  cta?: { to: string; label: string; tone: "primary" | "outline" };
};

const STEPS: Step[] = [
  { icon: "workers", title: "启动 worker" },
  { icon: "bundles", title: "上传任务包", cta: { to: "/bundles", label: "前往任务包", tone: "primary" } },
  { icon: "pulse", title: "新建批次", cta: { to: "/batches", label: "前往批次", tone: "outline" } },
];
</script>

<template>
  <Card
    title="首次使用 SatHop？"
    description="集群里还没有任务包或工作节点。三步完成首个批次："
  >
    <ol class="grid gap-4 md:grid-cols-3">
      <li
        v-for="(s, i) in STEPS"
        :key="s.title"
        class="flex h-full flex-col rounded-lg border border-border bg-subtle/40 p-4"
      >
        <div class="flex items-center gap-2.5">
          <span class="font-display grid h-7 w-7 place-items-center rounded-lg bg-accent/15 text-[12.5px] font-semibold text-accent tabular-nums">
            {{ i + 1 }}
          </span>
          <span class="text-muted"><Icon :name="s.icon" /></span>
          <span class="text-sm font-semibold text-text">{{ s.title }}</span>
        </div>
        <p class="mt-3 flex-1 text-xs leading-relaxed text-muted">
          <template v-if="i === 0">
            在 worker 主机上配置
            <code class="rounded bg-subtle px-1.5 py-0.5 font-mono text-[10.5px] text-text">deploy/worker/.env</code>，
            <br />
            <code class="rounded bg-subtle px-1.5 py-0.5 font-mono text-[10.5px] text-text">docker compose up -d</code>
            拉起即可注册。
          </template>
          <template v-else-if="i === 1">用户脚本入口、依赖、输入/输出契约。</template>
          <template v-else>选定任务包 + 凭证，提交首组数据粒。</template>
        </p>
        <div v-if="s.cta" class="mt-3">
          <RouterLink :to="s.cta.to">
            <ActionButton :tone="s.cta.tone">{{ s.cta.label }}</ActionButton>
          </RouterLink>
        </div>
      </li>
    </ol>
  </Card>
</template>
