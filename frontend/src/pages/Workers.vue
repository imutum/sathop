<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API } from "@/api";
import { K } from "@/queryKeys";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import WorkerCard from "@/features/nodes/components/WorkerCard.vue";
import OnboardWorkerModal from "@/features/onboarding/components/OnboardWorkerModal.vue";
import { Icon } from "@/components/Icon";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";

const qc = useQueryClient();
const toast = useToast();
const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });
const list = computed(() => workers.data.value ?? []);
const activeCount = computed(() => list.value.filter((w) => w.removed_at == null).length);

const updateAll = useMutation({
  mutationFn: () => API.updateAllWorkers(),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: [...K.workers] });
    toast.success(`已向 ${r.count} 个活跃节点发送更新信号`);
  },
  onError: (e: Error) => toast.error(`全部更新失败：${e.message}`),
});

async function onUpdateAll() {
  const ok = await requestConfirm({
    title: "更新全部工作节点？",
    description:
      "向所有活跃（未暂停）的 worker 发送更新信号。\n" +
      "它们会依次排空在手任务、拉取最新代码后重新启动。",
    confirmText: "全部更新",
  });
  if (ok) updateAll.mutate();
}

const removeAll = useMutation({
  mutationFn: () => API.removeAllWorkers(),
  onSuccess: (r) => {
    qc.invalidateQueries({ queryKey: [...K.workers] });
    toast.success(`已移除 ${r.count} 个工作节点`);
  },
  onError: (e: Error) => toast.error(`全部移除失败：${e.message}`),
});

async function onRemoveAll() {
  const ok = await requestConfirm({
    title: "移除全部工作节点？",
    description:
      "所有 worker 将在排空在手任务后自动停止，容器不再重启。\n" +
      "移除后节点 ID 不可再注册 — 如需恢复集群，需启动新的 worker。",
    confirmText: "全部移除",
    tone: "danger",
  });
  if (ok) removeAll.mutate();
}

const showOnboard = ref(false);

// Deep-link: /workers?id=<worker_id> scrolls + ring-highlights one card. Used
// by leased_by cells in BatchDetail / Dashboard.
const route = useRoute();
const focusId = computed(() => (route.query.id as string | undefined) ?? null);
const cardRefs = ref<Record<string, HTMLElement | null>>({});

let lastScrolled: string | null = null;
function maybeScroll() {
  const id = focusId.value;
  if (!id || lastScrolled === id) return;
  const el = cardRefs.value[id];
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  lastScrolled = id;
}

watch([focusId, list], () => void nextTick(maybeScroll), { immediate: true });

function setRef(id: string, el: Element | null) {
  cardRefs.value[id] = el as HTMLElement | null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="工作节点" description="集群内已注册的 Worker · 心跳 / 资源 / 队列">
      <template #actions>
        <Button
          v-if="activeCount > 0"
          variant="outline"
          class="gap-1.5"
          :disabled="updateAll.isPending.value"
          @click="onUpdateAll"
        >
          全部更新
        </Button>
        <Button
          v-if="activeCount > 0"
          variant="outline"
          class="gap-1.5 text-destructive hover:bg-destructive/10"
          :disabled="removeAll.isPending.value"
          @click="onRemoveAll"
        >
          全部移除
        </Button>
        <Button variant="default" class="gap-1.5" @click="showOnboard = true">
          <Icon name="plus" :size="13" />
          接入工作节点
        </Button>
      </template>
    </PageHeader>

    <QueryState :query="workers">
      <template #loading>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton v-for="n in 3" :key="n" class="h-48 w-full" />
        </div>
      </template>
      <template #error="{ error, retry }">
        <Alert variant="destructive">
          <AlertDescription class="flex items-center justify-between gap-3">
            <span>加载工作节点失败：{{ error.message }}</span>
            <Button size="sm" variant="outline" @click="retry">重试</Button>
          </AlertDescription>
        </Alert>
      </template>
      <template #empty>
        <Card>
          <CardContent class="pt-6">
            <EmptyState
              title="暂无已注册的工作节点"
              description="点下方按钮生成接入命令，复制到目标机器执行即可。"
              illustration="inbox"
            >
              <template #action>
                <Button variant="default" class="gap-1.5" @click="showOnboard = true">
                  <Icon name="plus" :size="13" />
                  接入工作节点
                </Button>
              </template>
            </EmptyState>
          </CardContent>
        </Card>
      </template>
      <template #default>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="w in list" :key="w.worker_id" :ref="(el) => setRef(w.worker_id, el as Element | null)">
            <WorkerCard :worker="w" :focused="focusId === w.worker_id" />
          </div>
        </div>
      </template>
    </QueryState>

    <OnboardWorkerModal v-if="showOnboard" @close="showOnboard = false" />
  </div>
</template>
