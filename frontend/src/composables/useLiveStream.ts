import { ref, watchEffect } from "vue";
import { useQueryClient } from "@tanstack/vue-query";

import { getToken } from "@/apiClient";
import type { Scope } from "@/apiTypes";
import { SCOPE_KEYS } from "@/queryKeys";

const THROTTLE_MS = 2000;

type Health = { version: string; web_sha: string | null };

export function useLiveStream() {
  const qc = useQueryClient();
  const connected = ref(false);
  const reconnect = ref(0);

  // The UI build seen on first connect. After an orchestrator restart, the SSE
  // reconnect observes a changed version (or web_sha, for a same-version
  // rebuild) and hard-reloads into the new bundle — refetching data alone would
  // keep the stale JS running.
  let baseline: Health | null = null;
  async function reloadIfStale(signal: AbortSignal) {
    let h: Health;
    try {
      const r = await fetch("/api/health", { cache: "no-store", signal });
      if (!r.ok) return;
      h = (await r.json()) as Health;
    } catch {
      return; // network error or aborted (a newer connect cycle superseded this)
    }
    if (signal.aborted) return;
    if (baseline === null) {
      baseline = h;
    } else if (h.version !== baseline.version || h.web_sha !== baseline.web_sha) {
      window.location.reload();
    }
  }

  watchEffect((onCleanup) => {
    void reconnect.value;
    const token = encodeURIComponent(getToken());
    const es = new EventSource(`/api/stream?token=${token}`);
    const healthCtrl = new AbortController();
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
      void reloadIfStale(healthCtrl.signal);
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
      healthCtrl.abort(); // drop an in-flight health probe so it can't act late
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (flushTimer) clearTimeout(flushTimer);
      es.close();
      connected.value = false;
    });
  });

  return { connected };
}
