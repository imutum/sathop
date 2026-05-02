<script setup lang="ts">
import { requestConfirm } from "../composables/useConfirm";

const props = defineProps<{
  enabled: boolean;
  pending: boolean;
  disableConfirm: string;
  forgetConfirm: string;
  disableTitle?: string;
  forgetTitle?: string;
}>();

const emit = defineEmits<{
  setEnabled: [next: boolean];
  forget: [];
}>();

async function toggle() {
  if (
    props.enabled &&
    !(await requestConfirm({
      title: "禁用节点？",
      description: props.disableConfirm,
      confirmText: "禁用",
      tone: "danger",
    }))
  ) {
    return;
  }
  emit("setEnabled", !props.enabled);
}

async function forget() {
  const ok = await requestConfirm({
    title: "移除节点？",
    description: props.forgetConfirm,
    confirmText: "移除",
    tone: "danger",
  });
  if (!ok) return;
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
        'rounded-md border px-2 py-0.5 text-[10.5px] font-medium transition disabled:opacity-50',
        enabled
          ? 'border-border bg-surface text-muted hover:border-danger/40 hover:text-danger'
          : 'border-success/30 bg-success/10 text-success hover:bg-success/15',
      ]"
    >
      {{ pending ? "…" : enabled ? "禁用" : "启用" }}
    </button>
    <button
      v-if="!enabled"
      type="button"
      :disabled="pending"
      @click="forget"
      :title="forgetTitle ?? '永久从注册表中删除'"
      class="rounded-md border border-danger/30 bg-danger/10 px-2 py-0.5 text-[10.5px] font-medium text-danger transition hover:bg-danger/15 disabled:opacity-50"
    >
      {{ pending ? "…" : "移除" }}
    </button>
  </span>
</template>
