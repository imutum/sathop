import { type MaybeRefOrGetter, computed, ref, toValue, watch } from "vue";
import type { RowErrors } from "./types";
import { rowHasErrors } from "./validation";

const PAGE_SIZE = 100;

export function usePaginatedRows<T>(
  items: MaybeRefOrGetter<T[]>,
  errors: MaybeRefOrGetter<RowErrors[]>,
) {
  const currentPage = ref(0);

  const totalPages = computed(() => Math.max(1, Math.ceil(toValue(items).length / PAGE_SIZE)));
  const pageStart = computed(() => currentPage.value * PAGE_SIZE);
  const pageEnd = computed(() => Math.min(pageStart.value + PAGE_SIZE, toValue(items).length));
  const pageItems = computed(() => toValue(items).slice(pageStart.value, pageEnd.value));
  const pageErrors = computed(() => toValue(errors).slice(pageStart.value, pageEnd.value));
  const showPagination = computed(() => toValue(items).length > PAGE_SIZE);

  const firstErrorPage = computed(() => {
    if (!showPagination.value) return -1;
    const errs = toValue(errors);
    for (let i = 0; i < errs.length; i++) {
      if (rowHasErrors(errs[i])) return Math.floor(i / PAGE_SIZE);
    }
    return -1;
  });

  function goPage(p: number) {
    currentPage.value = Math.max(0, Math.min(p, totalPages.value - 1));
  }

  watch(() => toValue(items).length, () => {
    if (currentPage.value >= totalPages.value) {
      currentPage.value = Math.max(0, totalPages.value - 1);
    }
  });

  function globalIdx(localIdx: number): number {
    return pageStart.value + localIdx;
  }

  return {
    currentPage,
    totalPages,
    pageStart,
    pageEnd,
    pageItems,
    pageErrors,
    showPagination,
    firstErrorPage,
    goPage,
    globalIdx,
  };
}
