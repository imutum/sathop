import { computed, ref, watch, type Ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { API, type EventRow } from "@/api";
import { K } from "@/queryKeys";

const PAGE_SIZE = 200;
const RECENT_LIMIT = 500;

export function useEventFeed(source: Ref<string>) {
  const rows = ref<EventRow[]>([]);
  const loadingOlder = ref(false);
  const hasMoreOlder = ref(true);
  const olderError = ref<string | null>(null);
  let generation = 0;

  // Older requests may still finish after switching away and back to a source.
  watch(source, () => {
    generation += 1;
    rows.value = [];
    loadingOlder.value = false;
    hasMoreOlder.value = true;
    olderError.value = null;
  }, { flush: "sync" });

  const query = useQuery({
    queryKey: computed(() => [...K.events, source.value] as const),
    queryFn: async ({ queryKey: [, requestedSource] }) => ({
      source: requestedSource,
      events: await API.events(
        requestedSource === source.value ? rows.value[0]?.id ?? 0 : 0,
        PAGE_SIZE, undefined, requestedSource || undefined,
      ),
    }),
  });

  function unseen(events: EventRow[]): EventRow[] {
    const seen = new Set(rows.value.map((event) => event.id));
    return events.filter((event) => !seen.has(event.id));
  }

  watch(query.data, (result) => {
    if (!result || result.source !== source.value) return;
    const fresh = unseen(result.events);
    if (!fresh.length) return;
    const merged = [...fresh, ...rows.value];
    // A refreshed window must still allow paging back to discarded history.
    if (merged.length > RECENT_LIMIT) hasMoreOlder.value = true;
    rows.value = merged.slice(0, RECENT_LIMIT);
  }, { immediate: true });

  async function loadOlder() {
    const oldest = rows.value.at(-1)?.id;
    if (oldest === undefined || loadingOlder.value || !hasMoreOlder.value) return;
    const requestedGeneration = generation;
    loadingOlder.value = true;
    olderError.value = null;
    try {
      const older = await API.events(0, PAGE_SIZE, oldest, source.value || undefined);
      if (requestedGeneration !== generation) return;
      rows.value = [...rows.value, ...unseen(older)];
      hasMoreOlder.value = older.length === PAGE_SIZE;
    } catch (error) {
      if (requestedGeneration === generation) {
        olderError.value = error instanceof Error ? error.message : String(error);
      }
    } finally {
      if (requestedGeneration === generation) loadingOlder.value = false;
    }
  }

  return { query, rows, loadingOlder, hasMoreOlder, olderError, loadOlder };
}
