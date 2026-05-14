<script setup lang="ts">
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/Icon";

// "简约至上" 的"转移"策略落地：每行只暴露 0-2 个最常用动作，
// 破坏性 / 罕用动作收进 ⋯ 菜单。call site：
//   <RowActions>
//     <template #primary> <Button …>主操作</Button> </template>
//     <DropdownMenuItem …>次级动作</DropdownMenuItem>
//   </RowActions>
//
// Tooltip 改走 Button 的原生 `title` 属性 —— reka-ui 的 TooltipTrigger
// 与 DropdownMenuTrigger 双层 `as-child` 嵌套时事件 listeners 无法都合并
// 到同一 Button，会出现"点击不触发菜单"的隐性 bug。
withDefaults(
  defineProps<{
    /** 挂在 ⋯ 触发器上的 native tooltip 文案 */
    menuLabel?: string;
    /** 整行容器对齐方式 */
    align?: "start" | "end";
  }>(),
  { menuLabel: "更多操作" },
);

defineSlots<{
  /** 行内可见的 0-2 个主要动作（建议 Button size=sm） */
  primary?: () => unknown;
  /** ⋯ 下拉菜单内的次级 / 危险动作（DropdownMenuItem） */
  default?: () => unknown;
}>();
</script>

<template>
  <div
    :class="[
      'flex flex-wrap items-center gap-1.5',
      align === 'end' ? 'justify-end' : 'justify-start',
    ]"
  >
    <slot name="primary" />
    <DropdownMenu v-if="$slots.default">
      <DropdownMenuTrigger as-child>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          :title="menuLabel"
          :aria-label="menuLabel"
        >
          <Icon name="more" :size="14" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" class="min-w-44">
        <slot />
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
</template>
