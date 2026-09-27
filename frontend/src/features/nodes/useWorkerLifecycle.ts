import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";

import { API } from "@/api";
import { K } from "@/queryKeys";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useLatestRelease } from "@/composables/useVersionCheck";
import {
  workerUpdateConfirmation,
  workerRemoveConfirmation,
  workerPurgeConfirmation,
  workerRevokeConfirmation,
} from "./workerActions";

// Worker actions resolve the current ID when invoked, including drawer switches.
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
        version ? `已提交 v${version} 升级请求，下次心跳生效` : "已提交重启请求，下次心跳生效",
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
      toast.success(`已删除节点 ${id()} 的记录`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const pause = useMutation({
    mutationFn: (next: boolean) => API.setWorkerPaused(id(), next),
    onSuccess: (_r, next) => {
      refreshWorkers();
      toast.success(next ? "已暂停接收新任务，当前任务继续执行" : "已恢复接收新任务");
    },
    onError: (e: Error) => toast.error(`调度设置失败：${e.message}`),
  });

  const revoke = useMutation({
    mutationFn: () => API.revokeWorkerLeases(id()),
    onSuccess: (r) => {
      refreshWorkers();
      qc.invalidateQueries({ queryKey: [...K.batches] });
      toast.success(`已收回 ${r.revoked} 条任务，等待重新调度`);
    },
    onError: (e: Error) => toast.error(`重新分配失败：${e.message}`),
  });

  const gc = useMutation({
    mutationFn: () => API.workerGc(id()),
    onSuccess: () => toast.success("已提交缓存清理请求，下次心跳生效"),
    onError: (e: Error) => toast.error(`清理请求失败：${e.message}`),
  });

  const setConcurrency = useMutation({
    mutationFn: (body: { download_concurrency: number | null; process_concurrency: number | null }) =>
      API.setWorkerConcurrency(id(), body),
    onSuccess: () => {
      refreshWorkers();
      toast.success("并发设置已更新，下次心跳生效");
    },
    onError: (e: Error) => toast.error(`设置失败：${e.message}`),
  });

  // Disables version-row + remove while either lifecycle op is in flight.
  const pending = computed(() => update.isPending.value || remove.isPending.value);

  async function confirmUpdate(): Promise<void> {
    const target = updateTarget.value;
    const ok = await requestConfirm(workerUpdateConfirmation(`节点 ${id()}`, target));
    if (ok) update.mutate(target);
  }

  async function confirmRemove(): Promise<void> {
    const ok = await requestConfirm(workerRemoveConfirmation(`节点 ${id()}`));
    if (ok) remove.mutate();
  }

  async function confirmPurge(): Promise<void> {
    const ok = await requestConfirm(workerPurgeConfirmation(`节点 ${id()}`));
    if (ok) purge.mutate();
  }

  function togglePause(currentlyPaused: boolean): void {
    pause.mutate(!currentlyPaused);
  }

  async function confirmRevoke(inflight: number): Promise<void> {
    const ok = await requestConfirm(workerRevokeConfirmation(`节点 ${id()}`, inflight));
    if (ok) revoke.mutate();
  }

  async function confirmGc(): Promise<void> {
    const ok = await requestConfirm({
      title: `清理节点缓存？`,
      description:
        "节点将在下次心跳后清理闲置的运行环境和不再引用的共享文件。\n" +
        "正在使用的任务包和运行环境将保留。",
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
