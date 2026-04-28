<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute } from "vue-router";
import { API } from "../api";
import Card from "../ui/Card.vue";
import EmptyState from "../ui/EmptyState.vue";
import PageHeader from "../ui/PageHeader.vue";
import WorkerCard from "./WorkerCard.vue";
import { Icon } from "../ui/Icon";

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

    <Card v-if="list.length === 0">
      <EmptyState title="暂无已注册的工作节点" description="启动 worker 容器后会自动出现在此。">
        <template #icon>
          <Icon name="workers" :size="20" />
        </template>
      </EmptyState>
    </Card>

    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="w in list" :key="w.worker_id" :ref="(el) => setRef(w.worker_id, el as Element | null)">
        <WorkerCard :worker="w" :focused="focusId === w.worker_id" />
      </div>
    </div>
  </div>
</template>
