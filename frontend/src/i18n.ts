// 集中的中文文案映射。后端 protocol 字段保持英文 enum（wire format 稳定），
// 仅在 UI 展示层做翻译。

import { ref } from "vue";

import type { GranuleState, TimingStage } from "./api";

// Reactive "wall clock" so relative-time renders (fmtAge / nodeStatusBadge)
// re-evaluate as time passes — Date.now() alone is invisible to Vue, so a
// row showing "8 秒前" would freeze until the next data refetch. 10 s ticks
// match the granularity of "秒前 / 分钟前".
const now = ref(Date.now());
if (typeof window !== "undefined") {
  setInterval(() => (now.value = Date.now()), 10_000);
}

export function useNow() {
  return now;
}

export const GRANULE_STATE_ZH: Record<GranuleState, string> = {
  pending: "待处理",
  downloading: "下载中",
  downloaded: "下载完成",
  processing: "处理中",
  processed: "处理完成",
  uploaded: "已上传",
  acked: "已确认",
  deleted: "已清理",
  failed: "失败",
  blacklisted: "已拉黑",
};

export const EVENT_LEVEL_ZH: Record<string, string> = {
  info: "信息",
  warn: "警告",
  error: "错误",
};

export const PLATFORM_ZH: Record<string, string> = {
  linux: "Linux",
  windows: "Windows",
};

export const TIMING_STAGE_ZH: Record<TimingStage, string> = {
  download: "下载",
  process: "处理",
  upload: "上传",
};

export function stateLabel(s: GranuleState): string {
  return GRANULE_STATE_ZH[s] ?? s;
}

export function levelLabel(l: string): string {
  return EVENT_LEVEL_ZH[l] ?? l;
}

// Wire-format progress step → display string. The bundle reports per-file
// progress as `download:<filename>` (file granularity beyond the bare
// TimingStage enum), so we expand the prefix here.
export function fmtProgressStep(step: string): string {
  return step.startsWith("download:") ? `下载 ${step.slice(9)}` : step;
}

export function fmtAge(iso: string): string {
  const t = new Date(iso).getTime();
  const s = Math.max(0, Math.floor((now.value - t) / 1000));
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} 小时前`;
  return `${(s / 86400).toFixed(1)} 天前`;
}

export function fmtMs(ms: number): string {
  if (!ms) return "0";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s - m * 60);
  return `${m}m${rs.toString().padStart(2, "0")}s`;
}

// Long-form wall clock for batch end-to-end times. Splits to h+m once over an
// hour; uses fmtMs's m+s format below.
export function fmtDuration(ms: number): string {
  if (ms < 3_600_000) return fmtMs(ms);
  const h = Math.floor(ms / 3_600_000);
  const m = Math.round((ms - h * 3_600_000) / 60_000);
  return `${h}h${m.toString().padStart(2, "0")}m`;
}

// Throughput per minute; rounds to the nearest 0.1 below 10/min, integer above.
export function fmtPerMinute(count: number, ms: number): string {
  if (ms <= 0 || count <= 0) return "—";
  const perMin = (count * 60_000) / ms;
  return perMin >= 10 ? `${perMin.toFixed(0)}/min` : `${perMin.toFixed(1)}/min`;
}
