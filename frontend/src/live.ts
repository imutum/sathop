// SSE live updates. Opens one EventSource to /api/stream, dispatches
// {scope} nudges to matching TanStack Query keys.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

type Scope =
  | "batches"
  | "workers"
  | "receivers"
  | "events"
  | "progress"
  | "bundles"
  | "shared";

const SCOPE_TO_KEYS: Record<Scope, string[][]> = {
  batches: [["batches"], ["overview"], ["batch"], ["granules"], ["in-flight"]],
  workers: [["workers"], ["overview"]],
  receivers: [["receivers"], ["overview"]],
  events: [["events"], ["overview"], ["batch-events"]],
  progress: [["granule-progress"], ["batch-progress-latest"]],
  bundles: [["bundles"], ["bundle-detail"]],
  shared: [["shared-files"]],
};

function getToken(): string {
  return localStorage.getItem("sathop.token") ?? "";
}

export function useLiveStream(): void {
  const qc = useQueryClient();

  useEffect(() => {
    let es: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let stopped = false;

    const open = () => {
      if (stopped) return;
      const token = encodeURIComponent(getToken());
      es = new EventSource(`/api/stream?token=${token}`);

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
        es?.close();
        es = null;
        if (stopped) return;
        // backoff then reconnect; browser sometimes closes after proxy timeout
        reconnectTimer = window.setTimeout(open, 3000);
      };
    };

    open();
    return () => {
      stopped = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      es?.close();
    };
  }, [qc]);
}
