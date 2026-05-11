// After the operator copies an onboarding snippet we want to confirm the
// target node actually registered with the orchestrator. The host-side
// useQuery is already kept fresh by useLiveStream (SSE invalidates the
// workers/receivers cache on each scope nudge), so we just observe the
// query's data and flip state when our ID appears.
//
// Lifecycle:
//   idle       → not started (initial)
//   waiting    → started; pinging cache for ID
//   registered → ID found in list
//   timeout    → 60s elapsed without a match; operator should check logs

import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";

export type WatchState = "idle" | "waiting" | "registered" | "timeout";

const TIMEOUT_MS = 60_000;

export function useRegistrationWatch<T>(
  id: Ref<string>,
  list: Ref<T[] | undefined>,
  match: (item: T, id: string) => boolean,
) {
  const state = ref<WatchState>("idle");
  let timer: number | null = null;

  const matched = computed(() =>
    state.value === "idle" ? false : (list.value ?? []).some((x) => match(x, id.value)),
  );

  watch(matched, (now) => {
    // Honour late registrations too — operator may have been slow to run the
    // command and we don't want the panel stuck on `timeout` once the node
    // eventually appears. Only `idle` (never started) and `registered`
    // (already terminal) skip the flip.
    if (now && (state.value === "waiting" || state.value === "timeout")) {
      state.value = "registered";
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    }
  });

  function start() {
    state.value = "waiting";
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (state.value === "waiting") state.value = "timeout";
    }, TIMEOUT_MS);
  }

  onBeforeUnmount(() => {
    if (timer) window.clearTimeout(timer);
  });

  return { state, start };
}
