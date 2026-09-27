import type { ConfirmOptions } from "@/composables/useConfirm";

// Shared by single-node and fleet actions; the subject identifies their scope.
export function workerUpdateConfirmation(subject: string, version: string | null): ConfirmOptions {
  return {
    title: version ? `升级 ${subject} 至 v${version}？` : `重启 ${subject}？`,
    description: version
      ? `节点将在下次心跳后等待当前任务完成，再安装 v${version} 并重启。期间可用处理能力可能下降，建议分批升级。`
      : "暂未获取最新版本。节点将在当前任务完成后重启，版本保持不变。",
    confirmText: version ? "升级并重启" : "重启",
  };
}

export function workerRemoveConfirmation(subject: string): ConfirmOptions {
  return {
    title: `移除 ${subject}？`,
    description: "节点将在当前任务完成后停止。移除后，该节点 ID 无法再次注册；如需恢复服务，请使用新的节点 ID。",
    confirmText: "移除",
    tone: "danger",
  };
}

export function workerPurgeConfirmation(subject: string): ConfirmOptions {
  return {
    title: `删除 ${subject} 的记录？`,
    description: "节点记录将永久删除，已上传产物和事件日志仍按原保留规则处理。若节点仍在运行，会重新注册；如需停止服务，请先停止节点。",
    confirmText: "删除记录",
    tone: "danger",
  };
}

export function workerRevokeConfirmation(subject: string, count?: number): ConfirmOptions {
  const scope = count === undefined ? "全部未完成任务" : `${count} 条未完成任务`;
  return {
    title: `重新分配 ${subject} 的任务？`,
    description: `将收回${scope}并重新调度。已下载或处理的中间结果将被丢弃，重试次数增加 1 次，仍受重试上限限制。`,
    confirmText: "重新分配",
    tone: "danger",
  };
}

/** Empty input restores node defaults; undefined means invalid input. */
export function parseConcurrency(
  value: string | number | null | undefined,
): number | null | undefined {
  // Number inputs can emit numbers despite the initial string value.
  const text = String(value ?? "").trim();
  if (!text) return null;
  const concurrency = Number(text);
  return Number.isInteger(concurrency) && concurrency >= 1 ? concurrency : undefined;
}
