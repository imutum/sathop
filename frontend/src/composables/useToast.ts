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
