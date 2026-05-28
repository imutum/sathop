import { computed } from "vue";
import { useMutation, useQueryClient } from "@tanstack/vue-query";

import type { ConfirmOptions } from "@/composables/useConfirm";
import { requestConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";

type NodeRecord = { enabled: boolean };

type NodeLifecycleConfig<T extends NodeRecord> = {
  id: string;
  queryKey: readonly string[];
  getId: (node: T) => string;
  setEnabled: (next: boolean) => Promise<unknown>;
  forget: () => Promise<unknown>;
  restart: () => Promise<unknown>;
  enabledMessage: string;
  disabledMessage: string;
  deletedMessage: string;
  restartMessage: string;
  forgetConfirm: ConfirmOptions;
  restartConfirm: ConfirmOptions;
};

export function useNodeLifecycle<T extends NodeRecord>(config: NodeLifecycleConfig<T>) {
  const qc = useQueryClient();
  const toast = useToast();
  const queryKey = [...config.queryKey];

  const enable = useMutation({
    mutationFn: config.setEnabled,
    onSuccess: (_r, next) => {
      qc.setQueryData<T[]>(queryKey, (prev) =>
        prev?.map((node) =>
          config.getId(node) === config.id ? ({ ...node, enabled: next } as T) : node,
        ) ?? prev,
      );
      qc.invalidateQueries({ queryKey });
      toast.success(next ? config.enabledMessage : config.disabledMessage);
    },
    onError: (e: Error) => toast.error(`失败：${e.message}`),
  });

  const forget = useMutation({
    mutationFn: config.forget,
    onSuccess: () => {
      qc.setQueryData<T[]>(queryKey, (prev) => prev?.filter((node) => config.getId(node) !== config.id) ?? prev);
      qc.invalidateQueries({ queryKey });
      toast.success(config.deletedMessage);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const restart = useMutation({
    mutationFn: config.restart,
    onSuccess: () => {
      toast.success(config.restartMessage);
    },
    onError: (e: Error) => toast.error(`重启失败：${e.message}`),
  });

  const pending = computed(() => enable.isPending.value || forget.isPending.value || restart.isPending.value);

  function setEnabled(next: boolean): void {
    enable.mutate(next);
  }

  async function confirmForget(): Promise<void> {
    if (await requestConfirm(config.forgetConfirm)) forget.mutate();
  }

  async function confirmRestart(): Promise<void> {
    if (await requestConfirm(config.restartConfirm)) restart.mutate();
  }

  return {
    pending,
    setEnabled,
    confirmForget,
    confirmRestart,
  };
}
