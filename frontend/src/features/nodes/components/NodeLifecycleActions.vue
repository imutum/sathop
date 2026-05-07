<script setup lang="ts">
import { ref, watch } from "vue";

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

// Disable / enable is a soft, reversible op — emit synchronously, no confirm.
function toggle(): void {
  emit("setEnabled", !props.enabled);
}

// Forget is destructive (permanent registry removal); use inline two-step
// confirm — clicking "移除" flips the button group into a "确认移除 / 取消"
// pair right there. Earlier we used a portal-rendered AlertDialog; some
// browser extensions tampered with the portal and swallowed the promise,
// leaving the button dead. Pure inline DOM is immune.
const confirming = ref(false);

function startForget(): void {
  confirming.value = true;
}
function cancelForget(): void {
  confirming.value = false;
}
function confirmForget(): void {
  confirming.value = false;
  emit("forget");
}

// If the node gets re-enabled (or unmounted), drop the confirm state so the
// next time the operator returns to it the button is back to its idle face.
watch(
  () => props.enabled,
  (e) => {
    if (e) confirming.value = false;
  },
);
</script>

<template>
  <span class="flex items-center gap-1.5">
    <template v-if="!confirming">
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
        @click="startForget"
        :title="enabled ? '请先禁用此节点，再点击此按钮永久移除' : (forgetTitle ?? '永久从注册表中删除')"
        :class="[
          'rounded-md border px-2 py-0.5 text-mini font-medium transition disabled:cursor-not-allowed',
          enabled
            ? 'border-border bg-muted/40 text-muted-foreground/60 disabled:opacity-60'
            : 'border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 disabled:opacity-50',
        ]"
      >
        {{ pending ? "…" : "移除" }}
      </button>
    </template>
    <template v-else>
      <span class="text-2xs font-medium text-danger">确定永久移除？</span>
      <button
        type="button"
        :disabled="pending"
        @click="cancelForget"
        class="rounded-md border border-border bg-background px-2 py-0.5 text-mini font-medium text-muted-foreground transition hover:border-primary/40 hover:text-foreground disabled:opacity-50"
      >
        取消
      </button>
      <button
        type="button"
        :disabled="pending"
        @click="confirmForget"
        class="rounded-md border border-danger/60 bg-danger/20 px-2 py-0.5 text-mini font-semibold text-danger transition hover:bg-danger/30 disabled:opacity-50"
      >
        {{ pending ? "…" : "确认移除" }}
      </button>
    </template>
  </span>
</template>
