<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import HintTip from "@/components/HintTip.vue";
import RowActions from "@/components/RowActions.vue";

// 节点生命周期三件套 — 启用 / 重启 / 移除。
// "简约至上 · 转移" 策略：最常用的 启用/禁用 留在外侧 Button，
// 重启 / 移除 这种破坏性 + 低频动作下沉到 ⋯ 菜单。
const props = defineProps<{
  enabled: boolean;
  pending: boolean;
  disableTitle?: string;
  forgetTitle?: string;
  restartTitle?: string;
}>();

const emit = defineEmits<{
  setEnabled: [next: boolean];
  forget: [];
  restart: [];
}>();

function toggle(): void {
  emit("setEnabled", !props.enabled);
}
</script>

<template>
  <RowActions>
    <template #primary>
      <HintTip :text="enabled ? (disableTitle ?? '停止接收新任务，当前任务继续执行') : '重新启用此节点'">
        <Button
          type="button"
          :variant="enabled ? 'outline' : 'default'"
          size="sm"
          :disabled="pending"
          @click="toggle"
        >
          {{ pending ? "…" : enabled ? "禁用" : "启用" }}
        </Button>
      </HintTip>
    </template>
    <DropdownMenuItem
      :title="restartTitle ?? '提交节点更新请求，下次心跳后更新并重启'"
      :disabled="pending"
      @select="emit('restart')"
    >
      更新…
    </DropdownMenuItem>
    <DropdownMenuItem
      :title="enabled ? '请先禁用节点，再删除记录' : (forgetTitle ?? '删除节点记录；仍在运行的节点会重新注册')"
      :disabled="pending || enabled"
      class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
      @select="emit('forget')"
    >
      删除记录…
    </DropdownMenuItem>
  </RowActions>
</template>
