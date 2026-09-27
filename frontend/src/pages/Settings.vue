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
import RolloutPanel from "@/components/RolloutPanel.vue";
import Segmented from "@/components/Segmented.vue";
import { Icon } from "@/components/Icon";

const toast = useToast();
const info = useQuery({ queryKey: [...K.orchInfo], queryFn: API.orchestratorInfo });

// Same version check as the sidebar banner — but surfaced inline here so the
// update action sits next to the freshness signal (检查 + 更新 together).
const { latestTag, status, statusLabel, dotClass, isFetching, refresh } = useVersionCheck(
  () => info.data.value?.version,
);
const outdated = computed(() => status.value === "outdated");

const busy = ref(false);

// ── fleet reporting detail (runtime toggle) ───────────────────────────────
// Optimistic: `pendingDetail` shows the operator's pick immediately, then
// clears once the refetch confirms server truth (or reverts on error). No
// watcher loop — the getter just prefers the pending value over the query.
const detailBusy = ref(false);
const pendingDetail = ref<"verbose" | "fast" | null>(null);
const detail = computed<string>({
  get: () => pendingDetail.value ?? info.data.value?.worker_detail ?? "verbose",
  set: (v) => void applyDetail(v as "verbose" | "fast"),
});

async function applyDetail(next: "verbose" | "fast") {
  if (next === (info.data.value?.worker_detail ?? "verbose")) return;
  pendingDetail.value = next;
  detailBusy.value = true;
  try {
    await API.setWorkerDetail(next);
    await info.refetch();
    toast.success(
      next === "fast"
        ? "已切换为精简上报，下次心跳生效"
        : "已切换为详细上报，下次心跳生效",
    );
  } catch (e: any) {
    toast.error(`切换失败：${e.message ?? e}`);
  } finally {
    pendingDetail.value = null;
    detailBusy.value = false;
  }
}

async function confirmUpgrade() {
  const target = latestTag.value.replace(/^v/, "");
  const ok = await requestConfirm({
    title: `升级到 v${target} 并重启？`,
    description:
      "将安装所选版本的前后端程序并重启服务。期间控制台与 API 暂时不可用，完成时间取决于下载和启动情况。",
    confirmText: "确认升级",
    tone: "danger",
  });
  if (!ok) return;
  busy.value = true;
  try {
    await API.upgradeOrchestrator(target);
    toast.success(`正在升级到 v${target} 并重启…`);
  } catch (e: any) {
    toast.error(`升级失败：${e.message ?? e}`);
    busy.value = false;
    return;
  }
  // The SSE stream drops, an overlay shows while it's down, and useLiveStream
  // hard-reloads into the new build once the server returns (see useLiveStream).
}

async function confirmRestart() {
  const ok = await requestConfirm({
    title: "重启调度服务？",
    description: "将以当前版本重启并重新读取配置。期间控制台与 API 暂时不可用。",
    confirmText: "确认重启",
    tone: "danger",
  });
  if (!ok) return;
  busy.value = true;
  try {
    await API.restartOrchestrator();
  } catch {
    // Connection drop is expected — the process is shutting down.
  }
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="设置" description="查看系统信息，管理上报方式与版本升级">
      <template #actions>
        <div class="flex items-center gap-3">
          <div class="hidden items-center gap-2 text-2xs text-muted-foreground sm:flex">
            <span class="relative grid h-2 w-2 place-items-center">
              <span :class="['absolute inset-0 rounded-full', dotClass]" aria-hidden />
            </span>
            <span class="font-mono text-foreground">v{{ info.data.value?.version ?? "?" }}</span>
            <span :class="outdated ? 'text-warning' : ''">{{ statusLabel }}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              class="h-6 w-6 text-muted-foreground"
              :disabled="isFetching"
              title="检查更新"
              aria-label="检查更新"
              @click="refresh"
            >
              <Icon name="refresh" :size="12" :class="isFetching ? 'animate-spin' : ''" />
            </Button>
          </div>
          <Button
            v-if="outdated"
            variant="default"
            size="sm"
            :pending="busy"
            pending-label="升级中…"
            @click="confirmUpgrade"
          >
            升级到 {{ latestTag }} 并重启
          </Button>
          <Button
            variant="outline"
            size="sm"
            :pending="busy"
            pending-label="重启中…"
            @click="confirmRestart"
          >
            重启
          </Button>
        </div>
      </template>
    </PageHeader>

    <Alert v-if="info.data.value?.auth_open" variant="warning">
      <AlertDescription>
        <span class="font-semibold">未启用 API 鉴权。</span>
        调度服务尚未设置 <code class="font-mono">SATHOP_TOKEN</code>，
        任何能访问网络地址的人都可以调用 <code class="font-mono">/api/*</code> 接口。
        生产环境请在容器环境变量中设置该值后重启。
      </AlertDescription>
    </Alert>

    <div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <CardSection
        title="系统信息"
        description="当前运行配置"
      >
        <div v-if="info.data.value" class="grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2">
          <Field label="调度服务版本">{{ info.data.value.version }}</Field>
          <Field label="Python 版本">{{ info.data.value.python_version }}</Field>
          <Field label="运行平台" mono>{{ info.data.value.platform }}</Field>
          <Field label="开发模式">{{ info.data.value.dev_mode ? "开启" : "关闭" }}</Field>
          <Field label="数据库路径" mono>{{ info.data.value.db_path }}</Field>
          <Field label="事件保留">
            {{ info.data.value.retain_events_days === 0 ? "永久保留" : `${info.data.value.retain_events_days} 天` }}
          </Field>
          <Field label="已完成数据粒保留">
            {{ info.data.value.retain_deleted_days === 0 ? "永久保留" : `${info.data.value.retain_deleted_days} 天` }}
          </Field>
          <Field label="保留扫描周期">
            {{ info.data.value.retention_sweep_sec === 0 ? "已禁用" : `${info.data.value.retention_sweep_sec} 秒` }}
          </Field>
          <Field label="单节点任务上限" hint="SATHOP_MAX_INFLIGHT_PER_WORKER">
            {{
              info.data.value.max_inflight_per_worker === 0
                ? "不限（仍受磁盘空间限制）"
                : `${info.data.value.max_inflight_per_worker} 条`
            }}
          </Field>
          <Field label="自动重试上限" hint="SATHOP_MAX_RETRIES">
            失败 {{ info.data.value.max_retries }} 次后停止自动重试
          </Field>
          <Field label="产物拉取重试上限" hint="SATHOP_MAX_PULL_FAILURES">
            单个产物拉取失败 {{ info.data.value.max_pull_failures }} 次后停止交付，可在批次详情页恢复
          </Field>
          <Field label="进度超时阈值">
            数据粒超过 {{ info.data.value.stuck_age_hours }} 小时未推进时，计入超时统计
          </Field>
        </div>
        <div v-else class="py-6 text-sm text-muted-foreground">加载中…</div>
      </CardSection>

      <div class="space-y-5">
        <CardSection
          title="进度上报"
          description="设置所有工作节点的上报方式，下次心跳生效，无需重启"
        >
          <div class="space-y-4">
            <div class="flex flex-wrap items-center gap-3">
              <Segmented
                v-model="detail"
                :options="[
                  { value: 'verbose', label: '详细' },
                  { value: 'fast', label: '精简' },
                ]"
                aria-label="进度上报方式"
              />
              <span
                v-if="detailBusy"
                class="flex items-center gap-1.5 text-2xs text-muted-foreground"
              >
                <Icon name="refresh" :size="12" class="animate-spin" />
                应用中…
              </span>
            </div>
            <dl class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <div
                class="rounded-lg border p-3 transition-colors"
                :class="detail === 'verbose' ? 'border-foreground/20 bg-muted/40' : 'border-border'"
              >
                <dt class="text-xs font-medium text-foreground">
                  详细上报
                </dt>
                <dd class="mt-1 text-2xs leading-relaxed text-muted-foreground">
                  上报各阶段状态和实时进度，便于跟踪任务与排查问题。
                </dd>
              </div>
              <div
                class="rounded-lg border p-3 transition-colors"
                :class="detail === 'fast' ? 'border-foreground/20 bg-muted/40' : 'border-border'"
              >
                <dt class="text-xs font-medium text-foreground">
                  精简上报
                </dt>
                <dd class="mt-1 text-2xs leading-relaxed text-muted-foreground">
                  仅上报最终状态与阶段耗时，减少写入开销。控制台不再显示各阶段的实时进度。
                </dd>
              </div>
            </dl>
          </div>
        </CardSection>

        <CardSection title="凭证说明">
          <p class="text-sm leading-relaxed text-muted-foreground">
            在“新建批次”中填写任务包所需的凭证。凭证随批次保存，并随任务提供给工作节点。
            更新凭证请创建新批次。
          </p>
        </CardSection>
      </div>
    </div>

    <CardSection
      title="节点分阶段升级"
      description="将工作节点分批升级至当前调度服务版本。每批确认上线后继续，超时则暂停。"
    >
      <RolloutPanel />
    </CardSection>

  </div>
</template>
