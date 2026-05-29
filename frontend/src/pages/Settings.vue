<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useVersionCheck } from "@/composables/useVersionCheck";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import CardSection from "@/components/CardSection.vue";
import Field from "@/components/Field.vue";
import PageHeader from "@/components/PageHeader.vue";
import { Icon } from "@/components/Icon";

const toast = useToast();
const info = useQuery({ queryKey: [...K.orchInfo], queryFn: API.orchestratorInfo });

// Same version check as the sidebar banner — but surfaced inline here so the
// update action sits next to the freshness signal (检查 + 更新 together).
const { latestTag, status, isFetching, refresh } = useVersionCheck(
  () => info.data.value?.version,
);
const outdated = computed(() => status.value === "outdated");
const versionLabel = computed(() => {
  switch (status.value) {
    case "current":
      return "已是最新版本";
    case "outdated":
      return `有新版本 ${latestTag.value} 可用`;
    case "loading":
      return "正在检查更新…";
    default:
      return "无法检查最新版本";
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

const updating = ref(false);

async function confirmUpdateAndRestart() {
  const ok = await requestConfirm({
    title: "更新并重启 Orchestrator？",
    description: "将更新前端资源、拉取最新代码并重启进程。期间服务短暂不可用（约 3-5 秒）。",
    confirmText: "确认更新",
    tone: "danger",
  });
  if (!ok) return;

  updating.value = true;
  try {
    const r = await API.updateFrontend();
    if (r.action === "downloaded") {
      toast.success(`前端 v${r.version} 下载完成，正在重启…`);
    } else {
      toast.success("前端已是最新，正在重启…");
    }
  } catch (e: any) {
    toast.error(`前端更新失败：${e.message ?? e}`);
    updating.value = false;
    return;
  }
  try {
    await API.restartOrchestrator();
  } catch {
    // Connection drop is expected — SIGTERM kills the process
  }
  // Page will reload when the server comes back via SSE reconnect
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="设置" description="Orchestrator 当前运行时配置（只读）">
      <template #actions>
        <div class="flex items-center gap-3">
          <div class="hidden items-center gap-2 text-2xs text-muted-foreground sm:flex">
            <span class="relative grid h-2 w-2 place-items-center">
              <span :class="['absolute inset-0 rounded-full', dotClass]" aria-hidden />
            </span>
            <span class="font-mono text-foreground">v{{ info.data.value?.version ?? "?" }}</span>
            <span :class="outdated ? 'text-warning' : ''">{{ versionLabel }}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              class="h-6 w-6 text-muted-foreground"
              :disabled="isFetching"
              title="重新检查最新版本"
              aria-label="重新检查"
              @click="refresh"
            >
              <Icon name="refresh" :size="12" :class="isFetching ? 'animate-spin' : ''" />
            </Button>
          </div>
          <Button
            :variant="outdated ? 'default' : 'outline'"
            size="sm"
            :pending="updating"
            pending-label="更新中…"
            @click="confirmUpdateAndRestart"
          >
            更新并重启
          </Button>
        </div>
      </template>
    </PageHeader>

    <Alert v-if="info.data.value?.auth_open" variant="warning">
      <AlertDescription>
        <span class="font-semibold">未启用 API 鉴权。</span>
        此 Orchestrator 当前未设置 <code class="font-mono">SATHOP_TOKEN</code>，
        任何能访问网络地址的人都可以调用 <code class="font-mono">/api/*</code> 接口。
        生产环境请在容器环境变量中设置该值后重启。
      </AlertDescription>
    </Alert>

    <CardSection
      title="系统信息"
      description="由 GET /api/admin/settings/info 提供"
    >
      <div v-if="info.data.value" class="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2">
        <Field label="Orchestrator 版本">{{ info.data.value.version }}</Field>
        <Field label="Python 版本">{{ info.data.value.python_version }}</Field>
        <Field label="运行平台" mono>{{ info.data.value.platform }}</Field>
        <Field label="开发模式">{{ info.data.value.dev_mode ? "开启" : "关闭" }}</Field>
        <Field label="数据库路径" mono>{{ info.data.value.db_path }}</Field>
        <Field label="事件保留">
          {{ info.data.value.retain_events_days === 0 ? "永久保留" : `${info.data.value.retain_events_days} 天` }}
        </Field>
        <Field label="已删除数据粒保留">
          {{ info.data.value.retain_deleted_days === 0 ? "永久保留" : `${info.data.value.retain_deleted_days} 天` }}
        </Field>
        <Field label="保留扫描周期">
          {{ info.data.value.retention_sweep_sec === 0 ? "已禁用" : `${info.data.value.retention_sweep_sec} 秒` }}
        </Field>
        <Field label="单 worker 在手上限" hint="SATHOP_MAX_INFLIGHT_PER_WORKER">
          {{
            info.data.value.max_inflight_per_worker === 0
              ? "不限（仅磁盘水位反压）"
              : `${info.data.value.max_inflight_per_worker} 条（队列反压）`
          }}
        </Field>
        <Field label="自动重试上限" hint="SATHOP_MAX_RETRIES">
          失败 {{ info.data.value.max_retries }} 次后转为「已拉黑」
        </Field>
        <Field label="receiver 拉取重试上限" hint="SATHOP_MAX_PULL_FAILURES">
          单产物拉取失败 {{ info.data.value.max_pull_failures }} 次后停止派发（可在批次详情页一键重置）
        </Field>
        <Field label="卡住告警阈值">
          数据粒在非终态停留超过 {{ info.data.value.stuck_age_hours }} 小时计入"卡住"统计
        </Field>
      </div>
      <div v-else class="py-6 text-sm text-muted-foreground">加载中…</div>
    </CardSection>

    <CardSection title="凭证说明">
      <p class="text-sm leading-relaxed text-muted-foreground">
        凭证已改为<strong class="text-foreground">按批次指定</strong>——在「新建任务」对话框里，基于任务包所需的凭证名称填入用户名/密码或 Token。
        凭证随批次落库，随 lease 分发给 worker，一次性使用；不再有全局注册表。
        轮换 = 创建新批次。
      </p>
    </CardSection>
  </div>
</template>
