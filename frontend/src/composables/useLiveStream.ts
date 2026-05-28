import { ref, watchEffect } from "vue";
import { useQueryClient } from "@tanstack/vue-query";

import { getToken } from "@/apiClient";
import type { Scope } from "@/apiTypes";
import { SCOPE_KEYS } from "@/queryKeys";

const THROTTLE_MS = 2000;

export function useLiveStream() {
  const qc = useQueryClient();
  const connected = ref(false);
  const reconnect = ref(0);

  watchEffect((onCleanup) => {
    void reconnect.value;
    const token = encodeURIComponent(getToken());
    const es = new EventSource(`/api/stream?token=${token}`);
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const pending = new Set<Scope>();
    let flushTimer: ReturnType<typeof setTimeout> | undefined;
    let lastFlush = 0;

    function flush() {
      flushTimer = undefined;
      lastFlush = Date.now();
      const seen = new Set<string>();
      for (const scope of pending) {
        for (const key of SCOPE_KEYS[scope]) {
          const k = key.join(",");
          if (!seen.has(k)) {
            seen.add(k);
            qc.invalidateQueries({ queryKey: [...key] });
          }
        }
      }
      pending.clear();
    }

    es.onopen = () => {
      connected.value = true;
    };

    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as { scope?: Scope };
        if (evt.scope && evt.scope in SCOPE_KEYS) {
          pending.add(evt.scope);
          if (!flushTimer) {
            const elapsed = Date.now() - lastFlush;
            const delay = elapsed >= THROTTLE_MS ? 0 : THROTTLE_MS - elapsed;
            flushTimer = setTimeout(flush, delay);
          }
        }
      } catch {
        // malformed SSE payload
      }
    };

    es.onerror = () => {
      connected.value = false;
      es.close();
      reconnectTimer = setTimeout(() => {
        reconnect.value++;
      }, 3000);
    };

    onCleanup(() => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (flushTimer) clearTimeout(flushTimer);
      es.close();
      connected.value = false;
    });
  });

  return { connected };
}
