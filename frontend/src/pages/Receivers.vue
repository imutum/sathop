<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";
import { API } from "@/api";
import Card from "@/ui/Card.vue";
import EmptyState from "@/ui/EmptyState.vue";
import PageHeader from "@/ui/PageHeader.vue";
import ReceiverCard from "@/features/nodes/components/ReceiverCard.vue";
import { Icon } from "@/ui/Icon";

const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
const list = computed(() => receivers.data.value ?? []);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="接收端" description="拉取 Worker 已上传产物的下游消费者" />

    <Card v-if="list.length === 0">
      <EmptyState title="暂无已注册的接收端" description="启动 receiver 容器后会自动出现在此。">
        <template #icon>
          <Icon name="receivers" :size="20" />
        </template>
      </EmptyState>
    </Card>

    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <ReceiverCard v-for="r in list" :key="r.receiver_id" :receiver="r" />
    </div>
  </div>
</template>
