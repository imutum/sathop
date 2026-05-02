import type { BadgeTone } from "@/components/ui/badge";

export function fmtGB(n: number): string {
  if (n >= 1024) return `${(n / 1024).toFixed(1)} TB`;
  return `${n.toFixed(1)} GB`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtRate(bps: number): string {
  if (bps <= 0) return "—";
  if (bps < 1024) return `${bps} B/s`;
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
  if (bps < 1024 * 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(2)} MB/s`;
  return `${(bps / 1024 / 1024 / 1024).toFixed(2)} GB/s`;
}

import { useNow } from "@/i18n";

// Heartbeat freshness → badge tone/label, used by Workers + Receivers cards.
//
// Reads the shared reactive `now` so callers that wrap this in computed()
// re-evaluate every tick — otherwise an absent worker stays "在线" until the
// next data refetch.
export function nodeStatusBadge(
  enabled: boolean,
  lastSeenISO: string,
): { tone: BadgeTone; label: string } {
  if (!enabled) return { tone: "error", label: "已禁用" };
  const sec = (useNow().value - new Date(lastSeenISO).getTime()) / 1000;
  if (sec < 60) return { tone: "acked", label: "在线" };
  if (sec < 300) return { tone: "warn", label: "待机" };
  return { tone: "error", label: "离线" };
}
