import { reactive } from "vue";

// Singleton toast queue. ToastContainer.vue renders `items`; useToast().error
// etc. push onto it. error toasts stay until dismissed; success/info auto-pop
// after 3.5s.

export type ToastKind = "success" | "error" | "info";
export type ToastItem = {
  id: number;
  kind: ToastKind;
  text: string;
  sticky: boolean;
};

const state = reactive<{ items: ToastItem[] }>({ items: [] });
let nextId = 0;

function push(kind: ToastKind, text: string) {
  const id = ++nextId;
  state.items.push({ id, kind, text, sticky: kind === "error" });
  if (kind !== "error") {
    window.setTimeout(() => dismiss(id), 3500);
  }
}

export function dismiss(id: number) {
  const i = state.items.findIndex((x) => x.id === id);
  if (i >= 0) state.items.splice(i, 1);
}

export const toastItems = state.items;

export function useToast() {
  return {
    success: (text: string) => push("success", text),
    error: (text: string) => push("error", text),
    info: (text: string) => push("info", text),
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
