<script setup lang="ts">
const props = defineProps<{
  enabled: boolean;
  pending: boolean;
  disableTitle?: string;
  forgetTitle?: string;
}>();

const emit = defineEmits<{
  setEnabled: [next: boolean];
  forget: [];
}>();

// Both ops are soft-reversible — disable flips back via the same button;
// forget only deletes the DB row, a live receiver/worker re-registers on
// next heartbeat (misclick recovery = restart the container). Parent owns
// the confirm flow on forget.
function toggle(): void {
  emit("setEnabled", !props.enabled);
}
function forget(): void {
  emit("forget");
}
</script>

<template>
  <span class="flex items-center gap-1.5">
    <button
      type="button"
      :disabled="pending"
      @click="toggle"
      :title="enabled ? (disableTitle ?? '禁用此节点') : '重新启用此节点'"
      :class="[
        'rounded-md border px-2 py-0.5 text-mini font-medium transition disabled:opacity-50',
        enabled
          ? 'border-border bg-background text-muted-foreground hover:border-danger/40 hover:text-danger'
          : 'border-success/30 bg-success/10 text-success hover:bg-success/15',
      ]"
    >
      {{ pending ? "…" : enabled ? "禁用" : "启用" }}
    </button>
    <button
      type="button"
      :disabled="pending || enabled"
      @click="forget"
      :title="enabled ? '请先禁用此节点，再点击此按钮永久移除' : (forgetTitle ?? '永久从注册表中删除（misclick → 重启 receiver/worker 自动重建）')"
      :class="[
        'rounded-md border px-2 py-0.5 text-mini font-medium transition disabled:cursor-not-allowed',
        enabled
          ? 'border-border bg-muted/40 text-muted-foreground/60 disabled:opacity-60'
          : 'border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 disabled:opacity-50',
      ]"
    >
      {{ pending ? "…" : "移除" }}
    </button>
  </span>
</template>
