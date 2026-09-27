import type { BatchSummary } from "@/api";
import { completedTotal, inFlightTotal, totalCount } from "./summary";

export function operationStatus(b: BatchSummary): { label: string; detail: string } {
  const total = totalCount(b.counts);
  if (!total) return { label: "等待提交", detail: "批次还没有数据粒。" };
  if (completedTotal(b) === total) {
    return { label: "全部已交付", detail: "接收端已确认全部数据粒，可导出交付报告核对文件。" };
  }
  if (b.objects_exhausted > 0) {
    return {
      label: "交付受阻",
      detail: `${b.objects_exhausted} 个产物已达到拉取重试上限。请检查接收端、磁盘和网络后恢复交付。`,
    };
  }
  if (b.status === "paused") {
    return { label: "已暂停", detail: "已暂停分配新数据粒，已领取的任务继续执行。" };
  }
  if ((b.counts.failed ?? 0) > 0) {
    return { label: "需要处理", detail: "存在失败数据粒，请查看错误原因，修复后重试。" };
  }
  if (!inFlightTotal(b) && !(b.counts.uploaded ?? 0) && (b.counts.blacklisted ?? 0) > 0) {
    return { label: "已停止", detail: "剩余数据粒已停止，可能包含主动取消的任务。重新处理前请核对范围。" };
  }
  if ((b.counts.uploaded ?? 0) > 0) {
    return { label: "等待交付", detail: "产物等待接收端拉取。若长时间未推进，请检查接收端是否在线并已启用。" };
  }
  return { label: "处理中", detail: "任务正在执行。若长时间待分配，请检查工作节点是否在线并可接收任务。" };
}
