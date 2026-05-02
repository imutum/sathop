<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API } from "@/api";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import WorkerCard from "@/features/nodes/components/WorkerCard.vue";
import { Icon } from "@/components/Icon";

const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });
const list = computed(() => workers.data.value ?? []);

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
    <PageHeader title="工作节点" description="集群内已注册的 Worker · 心跳 / 资源 / 队列" />

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
            <EmptyState title="暂无已注册的工作节点" description="启动 worker 容器后会自动出现在此。">
              <template #icon>
                <Icon name="workers" :size="20" />
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
  </div>
</template>
