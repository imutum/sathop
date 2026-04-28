// SSE live updates: one EventSource → fan out scope nudges to TanStack Query
// cache keys, plus expose connection state for the topbar's live badge.

import { onBeforeUnmount, onMounted, ref } from "vue";
import { useQueryClient } from "@tanstack/vue-query";

type Scope =
  | "batches"
  | "workers"
  | "receivers"
  | "events"
  | "progress"
  | "bundles"
  | "shared";

const SCOPE_TO_KEYS: Record<Scope, string[][]> = {
  batches: [["batches"], ["overview"], ["batch"], ["granules"], ["in-flight"], ["stuck"]],
  workers: [["workers"], ["overview"]],
  receivers: [["receivers"], ["overview"]],
  events: [["events"], ["overview"], ["batch-events"], ["granule-events"]],
  progress: [["granule-progress"], ["batch-progress-latest"]],
  bundles: [["bundles"], ["bundle-detail"]],
  shared: [["shared-files"]],
};

function getToken(): string {
  return localStorage.getItem("sathop.token") ?? "";
}

export function useLiveStream() {
  const qc = useQueryClient();
  const connected = ref(false);
  let es: EventSource | null = null;
  let reconnectTimer: number | null = null;
  let stopped = false;

  function open() {
    if (stopped) return;
    const token = encodeURIComponent(getToken());
    es = new EventSource(`/api/stream?token=${token}`);

    es.onopen = () => {
      connected.value = true;
    };

    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as { scope?: Scope };
        if (!evt.scope || !(evt.scope in SCOPE_TO_KEYS)) return;
        for (const key of SCOPE_TO_KEYS[evt.scope]) {
          qc.invalidateQueries({ queryKey: key });
        }
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      connected.value = false;
      es?.close();
      es = null;
      if (stopped) return;
      // Browser sometimes closes after a proxy timeout; back off and reopen.
      reconnectTimer = window.setTimeout(open, 3000);
    };
  }

  onMounted(open);
  onBeforeUnmount(() => {
    stopped = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    es?.close();
  });

  return { connected };
}
