<script setup lang="ts" generic="T">
import { computed } from "vue";
import type { UseQueryReturnType } from "@tanstack/vue-query";

// Headless 3-state wrapper around a TanStack Query result. Renders exactly
// one of: <loading>, <error>, <empty>, default.
//
// - loading  : initial fetch (no cached data yet). Refetches/background
//              updates keep the data slot mounted so the page doesn't flicker.
// - error    : query rejected and we have no usable data to fall back to.
// - empty    : query resolved but the result is "no data" — array length 0
//              by default; pass `isEmpty` to override for custom shapes.
// - default  : query resolved with data; receives `{ data: T }` as scoped
//              slot props.
const props = defineProps<{
  query: UseQueryReturnType<T, Error>;
  isEmpty?: (data: T) => boolean;
}>();

const showLoading = computed(
  () => props.query.isPending.value && props.query.data.value === undefined,
);
const showError = computed(
  () => !!props.query.error.value && props.query.data.value === undefined,
);
const showEmpty = computed(() => {
  if (showLoading.value || showError.value) return false;
  const d = props.query.data.value;
  if (d === undefined || d === null) return true;
  if (props.isEmpty) return props.isEmpty(d);
  if (Array.isArray(d)) return d.length === 0;
  return false;
});
</script>

<template>
  <slot v-if="showLoading" name="loading" />
  <slot
    v-else-if="showError"
    name="error"
    :error="query.error.value as Error"
    :retry="() => query.refetch()"
  />
  <slot v-else-if="showEmpty" name="empty" />
  <slot v-else :data="query.data.value as T" />
</template>
