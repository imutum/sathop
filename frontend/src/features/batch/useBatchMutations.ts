import type { Ref } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { API } from "@/api";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { K } from "@/queryKeys";

function useBatchInvalidation(batchId?: Ref<string>) {
  const qc = useQueryClient();
  return {
    lists() {
      qc.invalidateQueries({ queryKey: [...K.batches] });
    },
    detail() {
      if (batchId?.value) {
        qc.invalidateQueries({ queryKey: [...K.granules, batchId.value] });
        qc.invalidateQueries({ queryKey: [...K.batch, batchId.value] });
      }
      qc.invalidateQueries({ queryKey: [...K.batches] });
    },
    listsAndOverview() {
      qc.invalidateQueries({ queryKey: [...K.batches] });
      qc.invalidateQueries({ queryKey: [...K.overview] });
    },
  };
}

export function useBatchListMutations() {
  const toast = useToast();
  const inv = useBatchInvalidation();

  const retry = useMutation({
    mutationFn: (id: string) => API.retryFailed(id),
    onSuccess: (res) => {
      inv.lists();
      toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
    },
    onError: (e: Error) => toast.error(`重试失败：${e.message}`),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => API.cancelBatch(id),
    onSuccess: (res) => {
      inv.lists();
      toast.success(`已取消 ${res.cancelled} 条数据粒`);
    },
    onError: (e: Error) => toast.error(`取消失败：${e.message}`),
  });

  const remove = useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) => API.deleteBatch(id, force),
    onSuccess: (res) => {
      inv.listsAndOverview();
      toast.success(`已删除批次：${res.granules} 数据粒 / ${res.objects} 产物`);
    },
    onError: async (e: Error, vars) => {
      if (
        /mid-flight/.test(e.message) &&
        (await requestConfirm({
          title: "强制删除批次？",
          description: `${e.message}\n\n强制删除会让正在处理的 worker 在下次状态汇报时收到 404。`,
          confirmText: "强制删除",
          tone: "danger",
        }))
      ) {
        remove.mutate({ id: vars.id, force: true });
        return;
      }
      toast.error(`删除失败：${e.message}`);
    },
  });

  const setPaused = useMutation({
    mutationFn: ({ id, paused }: { id: string; paused: boolean }) =>
      paused ? API.pauseBatch(id) : API.resumeBatch(id),
    onSuccess: (res) => {
      inv.lists();
      toast.success(res.status === "paused" ? "已暂停，不再分发新数据粒" : "已恢复分发");
    },
    onError: (e: Error) => toast.error(`操作失败：${e.message}`),
  });

  return { retry, cancel, remove, setPaused, invalidate: inv.lists };
}

export function useBatchDetailMutations(batchId: Ref<string>) {
  const toast = useToast();
  const router = useRouter();
  const inv = useBatchInvalidation(batchId);

  const cancel = useMutation({
    mutationFn: (g: string) => API.cancelGranule(batchId.value, g),
    onSuccess: (_r, g) => {
      inv.detail();
      toast.success(`已取消数据粒 ${g}`);
    },
    onError: (e: Error, g) => toast.error(`取消 ${g} 失败：${e.message}`),
  });

  const retry = useMutation({
    mutationFn: (g: string) => API.retryGranule(batchId.value, g),
    onSuccess: (_r, g) => {
      inv.detail();
      toast.success(`已重试数据粒 ${g}`);
    },
    onError: (e: Error, g) => toast.error(`重试 ${g} 失败：${e.message}`),
  });

  const retryAll = useMutation({
    mutationFn: () => API.retryFailed(batchId.value),
    onSuccess: (res) => {
      inv.detail();
      toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
    },
    onError: (e: Error) => toast.error(`重试失败：${e.message}`),
  });

  const cancelAll = useMutation({
    mutationFn: () => API.cancelBatch(batchId.value),
    onSuccess: (res) => {
      inv.detail();
      toast.success(`已取消 ${res.cancelled} 条数据粒`);
    },
    onError: (e: Error) => toast.error(`取消失败：${e.message}`),
  });

  const resetExhausted = useMutation({
    mutationFn: () => API.resetExhaustedObjects(batchId.value),
    onSuccess: (res) => {
      inv.detail();
      if (res.reset > 0) toast.success(`已重置 ${res.reset} 个产物的重试计数，下个 receiver poll 周期会重新派发`);
      else toast.info("当前批次没有已放弃的产物");
    },
    onError: (e: Error) => toast.error(`重置失败：${e.message}`),
  });

  const deleteBatch = useMutation({
    mutationFn: (force: boolean) => API.deleteBatch(batchId.value, force),
    onSuccess: (res) => {
      inv.listsAndOverview();
      toast.success(`已删除批次：${res.granules} 数据粒 / ${res.objects} 产物 / ${res.events} 事件`);
      void router.push("/batches");
    },
    onError: async (e: Error) => {
      if (
        /mid-flight/.test(e.message) &&
        (await requestConfirm({
          title: "强制删除批次？",
          description:
            `批次仍有 worker 在处理。\n\n${e.message}\n\n` +
            "强制删除会让正在处理的 worker 在下次状态汇报时收到 404。",
          confirmText: "强制删除",
          tone: "danger",
        }))
      ) {
        deleteBatch.mutate(true);
        return;
      }
      toast.error(`删除失败：${e.message}`);
    },
  });

  // Batch-level flow control (pause/resume): non-destructive, sits above the
  // atomic per-granule cancel/retry above.
  const setPaused = useMutation({
    mutationFn: (paused: boolean) =>
      paused ? API.pauseBatch(batchId.value) : API.resumeBatch(batchId.value),
    onSuccess: (res) => {
      inv.detail();
      toast.success(res.status === "paused" ? "已暂停，不再分发新数据粒" : "已恢复分发");
    },
    onError: (e: Error) => toast.error(`操作失败：${e.message}`),
  });

  return {
    cancel,
    retry,
    retryAll,
    cancelAll,
    resetExhausted,
    deleteBatch,
    setPaused,
    invalidate: inv.detail,
  };
}
