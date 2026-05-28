import { ref, watchEffect } from "vue";
import { useQueryClient } from "@tanstack/vue-query";

import { getToken } from "@/apiClient";

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

export function useLiveStream() {
  const qc = useQueryClient();
  const connected = ref(false);
  const reconnect = ref(0);

  watchEffect((onCleanup) => {
    void reconnect.value;
    const token = encodeURIComponent(getToken());
    const es = new EventSource(`/api/stream?token=${token}`);
    let timer: ReturnType<typeof setTimeout> | undefined;

    es.onopen = () => {
      connected.value = true;
    };

    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as { scope?: Scope };
        if (evt.scope && evt.scope in SCOPE_TO_KEYS) {
          for (const key of SCOPE_TO_KEYS[evt.scope]) {
            qc.invalidateQueries({ queryKey: key });
          }
        }
      } catch {
        // malformed SSE payload
      }
    };

    es.onerror = () => {
      connected.value = false;
      es.close();
      timer = setTimeout(() => {
        reconnect.value++;
      }, 3000);
    };

    onCleanup(() => {
      if (timer) clearTimeout(timer);
      es.close();
      connected.value = false;
    });
  });

  return { connected };
}
