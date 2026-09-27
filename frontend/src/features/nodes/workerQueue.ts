import type { WorkerInfo } from "@/api";

/** The same six stages drive queue totals, compact bars and drawer details. */
export const WORKER_QUEUE_STAGES = [
  { key: "queue_pending_download", label: "待下载", color: "bg-amber-500/70", tip: "已领取，等待下载资源" },
  { key: "queue_downloading", label: "下载中", color: "bg-sky-500/70", tip: "正在下载源数据" },
  { key: "queue_pending_processing", label: "待处理", color: "bg-indigo-400/60", tip: "已下载，等待处理资源" },
  { key: "queue_processing", label: "处理中", color: "bg-indigo-500/80", tip: "正在执行任务包脚本" },
  { key: "queue_pending_upload", label: "待上传", color: "bg-violet-400/60", tip: "已处理完成，等待上传资源" },
  { key: "queue_uploading", label: "上传中", color: "bg-violet-500/80", tip: "正在上传产物到节点存储" },
] as const;

type WorkerQueue = Pick<WorkerInfo, (typeof WORKER_QUEUE_STAGES)[number]["key"]>;

export function workerQueueTotal(worker: WorkerQueue | null): number {
  return worker ? WORKER_QUEUE_STAGES.reduce((sum, stage) => sum + worker[stage.key], 0) : 0;
}
