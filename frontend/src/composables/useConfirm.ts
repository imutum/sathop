import { ref } from "vue";

export type ConfirmTone = "default" | "danger";

export type ConfirmOptions = {
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  tone?: ConfirmTone;
  requireText?: string;
  inputLabel?: string;
};

export type ConfirmRequest = Required<
  Pick<ConfirmOptions, "title" | "confirmText" | "cancelText" | "tone">
> &
  Pick<ConfirmOptions, "description" | "requireText" | "inputLabel"> & {
    resolve: (ok: boolean) => void;
  };

export const confirmRequest = ref<ConfirmRequest | null>(null);
export const confirmInput = ref("");

export function requestConfirm(options: ConfirmOptions): Promise<boolean> {
  if (confirmRequest.value) return Promise.resolve(false);
  confirmInput.value = "";
  return new Promise((resolve) => {
    confirmRequest.value = {
      title: options.title,
      description: options.description,
      confirmText: options.confirmText ?? "确认",
      cancelText: options.cancelText ?? "取消",
      tone: options.tone ?? "default",
      requireText: options.requireText,
      inputLabel: options.inputLabel,
      resolve,
    };
  });
}

export function resolveConfirm(ok: boolean): void {
  const current = confirmRequest.value;
  confirmRequest.value = null;
  confirmInput.value = "";
  current?.resolve(ok);
}
