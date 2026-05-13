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
      <HintTip :text="enabled ? (disableTitle ?? '禁用此节点（在手任务继续，可点启用恢复）') : '重新启用此节点'">
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
      :title="restartTitle ?? '触发该节点重启（一次心跳内生效，依赖容器 restart 策略恢复）'"
      :disabled="pending"
      @select="emit('restart')"
    >
      重启…
    </DropdownMenuItem>
    <DropdownMenuItem
      :title="enabled ? '请先禁用此节点，再点击此按钮永久移除' : (forgetTitle ?? '永久从注册表中删除（misclick → 重启 receiver/worker 自动重建）')"
      :disabled="pending || enabled"
      class="text-danger focus:bg-danger/10 focus:text-danger data-[disabled]:text-muted-foreground/50"
      @select="emit('forget')"
    >
      永久移除…
    </DropdownMenuItem>
  </RowActions>
</template>
