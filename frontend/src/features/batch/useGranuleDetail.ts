import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";

// The three "expanded granule" queries (timing / progress / events) in one
// composable, so GranuleExpandedDetail owns a single loading+error gate and
// feeds pure presentational children — instead of each child running its own
// query and flashing its own loading state. Queries are keyed per granule and
// only run while a row is expanded (the detail component is v-if'd), so they
// stay lazy. granuleProgress / granuleEvents ride their SSE scopes; granuleTiming
// changes once per stage and rides staleTime — same freshness as before.
export function useGranuleDetail(granuleId: MaybeRefOrGetter<string>) {
  const gid = computed(() => toValue(granuleId));

  const timing = useQuery({
    queryKey: computed(() => [...K.granuleTiming, gid.value]),
    queryFn: () => API.granuleTiming(gid.value),
  });
  const progress = useQuery({
    queryKey: computed(() => [...K.granuleProgress, gid.value]),
    queryFn: () => API.granuleProgress(gid.value),
  });
  const events = useQuery({
    queryKey: computed(() => [...K.granuleEvents, gid.value]),
    queryFn: () => API.granuleEvents(gid.value, 50),
  });

  const timingRows = computed(() => timing.data.value ?? []);
  const progressRows = computed(() => progress.data.value ?? []);
  const eventRows = computed(() => events.data.value ?? []);

  // First-load only (isPending flips false after the first success and stays
  // false on SSE-driven refetches, so this never re-flashes mid-stream).
  const isLoading = computed(
    () => timing.isPending.value || progress.isPending.value || events.isPending.value,
  );
  const isError = computed(
    () => timing.isError.value || progress.isError.value || events.isError.value,
  );

  return { timing, progress, events, timingRows, progressRows, eventRows, isLoading, isError };
}
