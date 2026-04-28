// Tones map shared by Badge / Stat / Alert. Keep the keys identical to React
// version so page-level tone strings (worker state enums, event levels) map
// straight through.
export const BADGE_TONES = {
  pending: "bg-subtle text-muted ring-border",
  queued: "bg-amber-500/10 text-amber-600 ring-amber-500/25 dark:text-amber-300",
  downloading: "bg-sky-500/10 text-sky-500 ring-sky-500/25 dark:text-sky-300",
  downloaded: "bg-sky-500/10 text-sky-500 ring-sky-500/25 dark:text-sky-300",
  processing: "bg-indigo-500/10 text-indigo-500 ring-indigo-500/25 dark:text-indigo-300",
  processed: "bg-indigo-500/10 text-indigo-500 ring-indigo-500/25 dark:text-indigo-300",
  uploaded: "bg-violet-500/10 text-violet-500 ring-violet-500/25 dark:text-violet-300",
  acked: "bg-success/10 text-success ring-success/25",
  deleted: "bg-success/10 text-success ring-success/25",
  failed: "bg-danger/10 text-danger ring-danger/25",
  blacklisted: "bg-danger/15 text-danger ring-danger/30",
  info: "bg-subtle text-muted ring-border",
  warn: "bg-warning/12 text-warning ring-warning/30",
  error: "bg-danger/12 text-danger ring-danger/30",
} as const;

export type BadgeTone = keyof typeof BADGE_TONES;

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

import { useNow } from "../i18n";

// Heartbeat freshness → badge tone/label, used by Workers + Receivers cards.
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
