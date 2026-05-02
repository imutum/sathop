<script setup lang="ts">
import { computed, ref } from "vue";

// Generic options keyed by string. Caller picks the union via the modelValue
// type (e.g. v-model holding "all" | "warn" | "error"). Vue's runtime doesn't
// preserve the generic but TS does at the call site.
//
// ARIA: this is a radio group (single-select toggle), not a tab list — there
// are no associated panels, so role="radiogroup" + role="radio" is the
// faithful mapping. Arrow keys move the focused radio; Home/End jump to
// extremes; only the checked option is in the tab order (roving tabindex).

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: { value: string; label: string; count?: number; dim?: boolean }[];
    size?: "sm" | "md";
    ariaLabel?: string;
  }>(),
  { size: "md" },
);

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const heightCls = computed(() =>
  props.size === "sm" ? "h-7 text-[11px] px-2.5" : "h-8 text-xs px-3",
);

const refs = ref<Array<HTMLButtonElement | null>>([]);

function activeIndex(): number {
  const i = props.options.findIndex((o) => o.value === props.modelValue);
  return i >= 0 ? i : 0;
}

function focusAt(i: number) {
  refs.value[i]?.focus();
}

function onKeydown(e: KeyboardEvent, i: number) {
  const last = props.options.length - 1;
  let next: number | null = null;
  if (e.key === "ArrowRight" || e.key === "ArrowDown") next = i === last ? 0 : i + 1;
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = i === 0 ? last : i - 1;
  else if (e.key === "Home") next = 0;
  else if (e.key === "End") next = last;
  if (next === null) return;
  e.preventDefault();
  emit("update:modelValue", props.options[next].value);
  void Promise.resolve().then(() => focusAt(next!));
}
</script>

<template>
  <div
    role="radiogroup"
    :aria-label="ariaLabel"
    class="inline-flex items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5"
  >
    <button
      v-for="(o, i) in options"
      :key="o.value"
      :ref="(el) => (refs[i] = el as HTMLButtonElement | null)"
      type="button"
      role="radio"
      :aria-checked="o.value === modelValue"
      :tabindex="o.value === modelValue || (i === activeIndex()) ? 0 : -1"
      @click="emit('update:modelValue', o.value)"
      @keydown="onKeydown($event, i)"
      :class="[
        heightCls,
        'inline-flex items-center gap-1.5 rounded-md font-medium transition',
        o.value === modelValue
          ? 'bg-background text-foreground shadow-soft'
          : o.dim
            ? 'text-muted-foreground/50 hover:text-muted-foreground'
            : 'text-muted-foreground hover:text-foreground',
      ]"
    >
      {{ o.label }}
      <span
        v-if="o.count !== undefined"
        :class="[
          'tabular-nums text-[10.5px]',
          o.value === modelValue ? 'text-muted-foreground' : 'text-muted-foreground/70',
        ]"
      >
        {{ o.count }}
      </span>
    </button>
  </div>
</template>
