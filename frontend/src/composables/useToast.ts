import { toast } from "vue-sonner";

export type ToastKind = "success" | "error" | "info";

export function useToast() {
  return {
    success: (text: string) => toast.success(text),
    info: (text: string) => toast.info(text),
    // Errors are sticky — vue-sonner auto-dismisses by default; force Infinity
    // so failures linger until the user dismisses, matching prior behavior.
    error: (text: string) => toast.error(text, { duration: Infinity }),
  };
}

// Helper for VueQuery-style mutations: hand to onSuccess/onError directly.
export function useMutationToast() {
  const t = useToast();
  return {
    onSuccess: (msg: string) => () => t.success(msg),
    onError: (prefix?: string) => (e: unknown) => {
      const text = e instanceof Error ? e.message : String(e);
      t.error(prefix ? `${prefix}：${text}` : text);
    },
  };
}
