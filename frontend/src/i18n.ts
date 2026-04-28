// 集中的中文文案映射。后端 protocol 字段保持英文 enum（wire format 稳定），
// 仅在 UI 展示层做翻译。

import type { GranuleState, TimingStage } from "./api";

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

export function fmtAge(iso: string): string {
  const t = new Date(iso).getTime();
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
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
