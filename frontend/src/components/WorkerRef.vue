<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API } from "@/api";
import { K } from "@/queryKeys";

// Renders a granule's leased_by worker reference. Resolves the id against the
// known worker set (active OR history — both are linkable; the Workers page
// deep-link auto-selects the right tab). A leased_by that resolves to nothing —
// the worker was physically deleted, or aged out by the retention sweep — is
// rendered as a muted, non-clickable "已删除节点" label instead of a dead link.
const props = defineProps<{ workerId: string | null }>();

const workers = useQuery({ queryKey: [...K.workers], queryFn: API.workers });

type Kind = "none" | "link" | "deleted";
const kind = computed<Kind>(() => {
  if (!props.workerId) return "none";
  // Stay optimistic until the worker list has loaded — avoids a flash of
  // "已删除节点" for valid workers on first paint.
  if (workers.data.value === undefined) return "link";
  return workers.data.value.some((w) => w.worker_id === props.workerId) ? "link" : "deleted";
});
</script>

<template>
  <template v-if="kind === 'none'">—</template>
  <RouterLink
    v-else-if="kind === 'link'"
    :to="`/workers?id=${encodeURIComponent(workerId!)}`"
    class="transition-colors hover:text-primary"
    title="跳转到该 worker 卡片"
  >
    {{ workerId }}
  </RouterLink>
  <span
    v-else
    class="text-muted-foreground/60"
    title="该节点已被删除（物理移除或保留期过期）"
  >
    已删除节点 {{ workerId }}
  </span>
</template>
