import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useLatestRelease } from "@/composables/useVersionCheck";

// All worker operations in one place: the six mutations plus their confirm
// dialogs and the toast+invalidate boilerplate that used to be copy-pasted six
// times inside WorkerCard. Mirrors features/nodes/useNodeLifecycle.ts (receivers)
// so both card types share the same shape.
export function useWorkerLifecycle(worker: MaybeRefOrGetter<{ worker_id: string }>) {
  const qc = useQueryClient();
  const toast = useToast();
  const id = () => toValue(worker).worker_id;
  const refreshWorkers = () => qc.invalidateQueries({ queryKey: [...K.workers] });

  // Target release for "更新" — newest version (shared, server-resolved query);
  // null while unknown ⇒ degrades to a same-version restart.
  const latest = useLatestRelease();
  const updateTarget = computed(() => (latest.data.value?.tag ?? "").replace(/^v/, "") || null);

  // version is captured at confirm time and passed through mutate(), so the
  // request + toast use exactly what the user confirmed — not whatever the
  // shared latest query happens to hold when the callback later fires.
  const update = useMutation({
    mutationFn: (version: string | null) => API.updateWorker(id(), version),
    onSuccess: (_r, version) =>
      toast.success(
        version ? `已发送升级到 v${version} 信号，下次心跳生效` : "已发送重启信号，下次心跳生效",
      ),
    onError: (e: Error) => toast.error(`更新失败：${e.message}`),
  });

  const remove = useMutation({
    mutationFn: () => API.removeWorker(id()),
    onSuccess: () => {
      refreshWorkers();
      toast.success(`已移除节点 ${id()}`);
    },
    onError: (e: Error) => toast.error(`移除失败：${e.message}`),
  });

  const purge = useMutation({
    mutationFn: () => API.purgeWorker(id()),
    onSuccess: () => {
      refreshWorkers();
      toast.success(`已彻底删除节点 ${id()}`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const pause = useMutation({
    mutationFn: (next: boolean) => API.setWorkerPaused(id(), next),
    onSuccess: (_r, next) => {
      refreshWorkers();
      toast.success(next ? "已暂停领新任务（在手任务继续）" : "已恢复");
    },
    onError: (e: Error) => toast.error(`暂停切换失败：${e.message}`),
  });

  const revoke = useMutation({
    mutationFn: () => API.revokeWorkerLeases(id()),
    onSuccess: (r) => {
      refreshWorkers();
      qc.invalidateQueries({ queryKey: [...K.batches] });
      toast.success(`已释放 ${r.revoked} 条 lease，等待其他 worker 抢占`);
    },
    onError: (e: Error) => toast.error(`释放失败：${e.message}`),
  });

  const gc = useMutation({
    mutationFn: () => API.workerGc(id()),
    onSuccess: () => toast.success("已发送清理信号，下次心跳生效"),
    onError: (e: Error) => toast.error(`触发失败：${e.message}`),
  });

  const setConcurrency = useMutation({
    mutationFn: (body: { download_concurrency: number | null; process_concurrency: number | null }) =>
      API.setWorkerConcurrency(id(), body),
    onSuccess: () => {
      refreshWorkers();
      toast.success("已下发并发设置，下次心跳收敛");
    },
    onError: (e: Error) => toast.error(`设置失败：${e.message}`),
  });

  // Disables version-row + remove while either lifecycle op is in flight.
  const pending = computed(() => update.isPending.value || remove.isPending.value);

  async function confirmUpdate(): Promise<void> {
    const target = updateTarget.value;
    const ok = await requestConfirm({
      title: target ? `升级节点 ${id()} 到 v${target}？` : `重启节点 ${id()}？`,
      description: target
        ? `该 worker 在下次心跳后排空在手任务、写入待装版本 v${target} 并退出，由 entrypoint 拉取该版本安装后重启。`
        : "未能确定最新版本，将发送同版本重启信号（排空在手任务后重启，版本不变）。",
      confirmText: target ? "升级" : "重启",
    });
    if (ok) update.mutate(target);
  }

  async function confirmRemove(): Promise<void> {
    const ok = await requestConfirm({
      title: `移除节点 ${id()}？`,
      description:
        "该节点将被永久移除，容器会在排空任务后自动停止。\n" +
        "移除后该节点 ID 不可再注册 — 如需恢复，请启动新的 worker。",
      confirmText: "移除",
      tone: "danger",
    });
    if (ok) remove.mutate();
  }

  async function confirmPurge(): Promise<void> {
    const ok = await requestConfirm({
      title: `彻底删除节点 ${id()}？`,
      description:
        "从注册表中物理删除该节点记录（已上传产物与事件日志不受影响，各自按保留周期老化）。\n" +
        "如果该节点容器仍在运行，删除后它会以新节点身份重新注册 — 想让它彻底不再回来，请先停掉容器。",
      confirmText: "彻底删除",
      tone: "danger",
    });
    if (ok) purge.mutate();
  }

  function togglePause(currentlyPaused: boolean): void {
    pause.mutate(!currentlyPaused);
  }

  async function confirmRevoke(inflight: number): Promise<void> {
    const ok = await requestConfirm({
      title: `立即释放此节点的所有 lease？`,
      description:
        `把这台节点持有的全部在手 lease（${inflight} 条）重置回 待分配，等其他 worker 抢占。\n` +
        "已下载/已处理的中间产物会被丢弃；retry_count 会 +1，仍受 max_retries 限制。\n" +
        "用于 worker 卡住但还在心跳的场景。",
      confirmText: "立即释放",
      tone: "danger",
    });
    if (ok) revoke.mutate();
  }

  async function confirmGc(): Promise<void> {
    const ok = await requestConfirm({
      title: `让节点立即清理缓存？`,
      description:
        "向该 worker 发送清理信号 — 下一次心跳生效，立即跑一次 venv LRU + shared 孤儿清理。\n" +
        "正在使用的 bundle/venv 不会被清掉（受 in_use 锁保护）。",
      confirmText: "清理缓存",
    });
    if (ok) gc.mutate();
  }

  return {
    update,
    remove,
    purge,
    pause,
    revoke,
    gc,
    setConcurrency,
    pending,
    confirmUpdate,
    confirmRemove,
    confirmPurge,
    togglePause,
    confirmRevoke,
    confirmGc,
  };
}
