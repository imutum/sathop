import type { BatchSummary } from "@/api";
import { completedTotal, inFlightTotal, totalCount } from "./summary";

export function operationStatus(b: BatchSummary): { label: string; detail: string } {
  const total = totalCount(b.counts);
  if (!total) return { label: "等待提交", detail: "批次还没有数据粒。" };
  if (completedTotal(b) === total) return { label: "全部已交付", detail: "接收端已确认全部数据粒，可导出交付报告并核对实际文件。" };
  if (b.objects_exhausted > 0) return { label: "交付受阻", detail: `${b.objects_exhausted} 个产物的拉取重试已耗尽。先检查接收端、磁盘和网络，再恢复交付。` };
  if (b.status === "paused") return { label: "已暂停", detail: "新数据粒暂不分发，已领取的任务仍会继续完成。恢复后继续调度。" };
  if ((b.counts.failed ?? 0) > 0) return { label: "需要处理", detail: "存在失败数据粒。查看错误原因并修复后，可单独或批量重试。" };
  if (!inFlightTotal(b) && !(b.counts.uploaded ?? 0) && (b.counts.blacklisted ?? 0) > 0)
    return { label: "已停止", detail: "剩余数据粒已停止，其中可能包含主动取消的任务。核对范围后再决定是否重新处理。" };
  if ((b.counts.uploaded ?? 0) > 0)
    return { label: "等待交付", detail: "已有产物等待接收端拉取。若长时间没有进展，请检查接收端是否在线并已启用。" };
  return { label: "处理中", detail: "任务会按下载、处理、上传、交付推进。长时间停在待分配时，请检查工作节点是否在线并可接单。" };
}
