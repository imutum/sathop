<script setup lang="ts">
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import HintTip from "@/components/HintTip.vue";
import { Icon } from "@/components/Icon";

// "简约至上" 的"转移"策略落地：每行只暴露 0-2 个最常用动作，
// 破坏性 / 罕用动作收进 ⋯ 菜单。call site：
//   <RowActions>
//     <template #primary> <Button …>主操作</Button> </template>
//     <DropdownMenuItem …>次级动作</DropdownMenuItem>
//   </RowActions>
defineProps<{
  /** 折叠菜单的解释文案，挂在 ⋯ 触发器上 */
  menuLabel?: string;
  /** 整行容器对齐方式 */
  align?: "start" | "end";
}>();

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
      <HintTip :text="menuLabel ?? '更多操作'">
        <DropdownMenuTrigger as-child>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="更多操作"
          >
            <Icon name="more" :size="14" />
          </Button>
        </DropdownMenuTrigger>
      </HintTip>
      <DropdownMenuContent align="end" class="min-w-44">
        <slot />
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
</template>
