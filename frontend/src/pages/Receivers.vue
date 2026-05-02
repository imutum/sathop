<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import QueryState from "@/components/QueryState.vue";
import ReceiverCard from "@/features/nodes/components/ReceiverCard.vue";

const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="接收端" description="拉取 Worker 已上传产物的下游消费者" />

    <QueryState :query="receivers">
      <template #loading>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton v-for="n in 3" :key="n" class="h-40 w-full" />
        </div>
      </template>
      <template #error="{ error, retry }">
        <Alert variant="destructive">
          <AlertDescription class="flex items-center justify-between gap-3">
            <span>加载接收端失败：{{ error.message }}</span>
            <Button size="sm" variant="outline" @click="retry">重试</Button>
          </AlertDescription>
        </Alert>
      </template>
      <template #empty>
        <Card>
          <CardContent class="pt-6">
            <EmptyState
              title="暂无已注册的接收端"
              description="启动 receiver 容器后会自动出现在此。"
              illustration="inbox"
            />
          </CardContent>
        </Card>
      </template>
      <template #default="{ data: list }">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <ReceiverCard v-for="r in list" :key="r.receiver_id" :receiver="r" />
        </div>
      </template>
    </QueryState>
  </div>
</template>
