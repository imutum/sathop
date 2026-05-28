import { ref, watchEffect } from "vue";
import { useQueryClient } from "@tanstack/vue-query";

import { getToken } from "@/apiClient";
import type { Scope } from "@/apiTypes";
import { SCOPE_KEYS } from "@/queryKeys";

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
        if (evt.scope && evt.scope in SCOPE_KEYS) {
          for (const key of SCOPE_KEYS[evt.scope]) {
            qc.invalidateQueries({ queryKey: [...key] });
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
