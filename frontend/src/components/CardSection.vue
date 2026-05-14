<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// 统一所有卡片的"标题 / 副标题 / 右侧元数据 / 内容"节奏 ——
// 此前每页手写 `flex-row items-start justify-between space-y-0 gap-4` 的样板
// 已替换为这个组件。
//
// `padded`=true 时内容套 CardContent（默认有水平内边距），
// 表格内容应传 padded=false 让 <Table> 自己撑满边到边。
withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    /** 是否在内容外包 CardContent（默认 true）。表格/列表传 false。 */
    padded?: boolean;
    /** Card 容器额外类。 */
    class?: string;
  }>(),
  { padded: true },
);
</script>

<template>
  <Card :class="$props.class">
    <CardHeader
      v-if="title || $slots.title || description || $slots.description || $slots.meta"
      class="flex-row items-start justify-between space-y-0 gap-4"
    >
      <div class="min-w-0 space-y-1.5">
        <CardTitle v-if="title || $slots.title">
          <slot name="title">{{ title }}</slot>
        </CardTitle>
        <CardDescription v-if="description || $slots.description">
          <slot name="description">{{ description }}</slot>
        </CardDescription>
      </div>
      <div v-if="$slots.meta" class="flex shrink-0 items-center gap-2">
        <slot name="meta" />
      </div>
    </CardHeader>
    <CardContent v-if="padded">
      <slot />
    </CardContent>
    <template v-else>
      <slot />
    </template>
  </Card>
</template>
