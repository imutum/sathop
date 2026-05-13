<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{
  error: string | null;
  stdoutTail?: string | null;
  stderrTail?: string | null;
}>();

type View = "error" | "stdout" | "stderr";

const open = ref(false);
const view = ref<View>("error");

const hasStdout = computed(() => !!props.stdoutTail);
const hasStderr = computed(() => !!props.stderrTail);
const hasAnyOutput = computed(() => hasStdout.value || hasStderr.value);

// Short = single-line, ≤80 chars, no extra streams. Treat anything with
// stdout/stderr tails as "long" — even if the error string itself is short,
// the operator probably wants to inspect bundle output.
const isLong = computed(() => {
  const e = props.error;
  if (hasAnyOutput.value) return true;
  return !!e && (e.length > 80 || e.includes("\n"));
});

const totalChars = computed(() => {
  return (
    (props.error?.length ?? 0) +
    (props.stdoutTail?.length ?? 0) +
    (props.stderrTail?.length ?? 0)
  );
});

const currentText = computed(() => {
  if (view.value === "stdout") return props.stdoutTail ?? "";
  if (view.value === "stderr") return props.stderrTail ?? "";
  return props.error ?? "";
});

const currentEmpty = computed(() => currentText.value.length === 0);

function setView(v: View) {
  view.value = v;
}

const tabClass = (active: boolean) =>
  active
    ? "rounded-md bg-danger/25 px-2 py-0.5 text-3xs font-medium text-danger"
    : "rounded-md px-2 py-0.5 text-3xs font-medium text-muted-foreground transition-colors hover:text-foreground";
</script>

<template>
  <template v-if="error || hasAnyOutput">
    <span v-if="!isLong">{{ error }}</span>
    <span v-else-if="!open" class="block">
      <span class="block truncate" title="点击查看完整错误">{{ error || "(无摘要 — 点击查看输出)" }}</span>
      <button
        type="button"
        @click="open = true"
        class="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-3xs font-medium text-danger transition-colors hover:bg-danger/25"
      >
        展开完整错误（{{ totalChars }} 字符）
      </button>
    </span>
    <span v-else class="block">
      <div v-if="hasAnyOutput" class="mb-1 flex items-center gap-1">
        <button type="button" :class="tabClass(view === 'error')" @click="setView('error')">
          错误摘要{{ error ? ` (${error.length})` : "" }}
        </button>
        <button
          v-if="hasStdout"
          type="button"
          :class="tabClass(view === 'stdout')"
          @click="setView('stdout')"
        >
          stdout ({{ stdoutTail!.length }})
        </button>
        <button
          v-if="hasStderr"
          type="button"
          :class="tabClass(view === 'stderr')"
          @click="setView('stderr')"
        >
          stderr ({{ stderrTail!.length }})
        </button>
      </div>
      <pre
        class="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-danger/30 bg-danger/5 p-2.5 text-2xs"
      ><template v-if="!currentEmpty">{{ currentText }}</template><span v-else class="text-muted-foreground">(空)</span></pre>
      <button
        type="button"
        @click="open = false"
        class="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-3xs font-medium text-danger transition-colors hover:bg-danger/25"
      >
        收起
      </button>
    </span>
  </template>
</template>
