import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";

type ToastKind = "success" | "error" | "info";
type ToastItem = {
  id: number;
  kind: ToastKind;
  text: string;
  // Error toasts stay until clicked; success/info auto-dismiss after 3.5s.
  sticky: boolean;
};

type ToastApi = {
  success: (text: string) => void;
  error: (text: string) => void;
  info: (text: string) => void;
};

const ToastCtx = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const t = useContext(ToastCtx);
  if (!t) throw new Error("useToast must be used inside <ToastProvider>");
  return t;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = ++idRef.current;
    setItems((xs) => [...xs, { id, kind, text, sticky: kind === "error" }]);
    if (kind !== "error") {
      window.setTimeout(() => {
        setItems((xs) => xs.filter((x) => x.id !== id));
      }, 3500);
    }
  }, []);

  const api: ToastApi = {
    success: (t) => push("success", t),
    error: (t) => push("error", t),
    info: (t) => push("info", t),
  };

  const dismiss = (id: number) => setItems((xs) => xs.filter((x) => x.id !== id));

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed right-4 bottom-4 z-[100] flex w-80 flex-col gap-2"
      >
        {items.map((it) => (
          <Toast key={it.id} item={it} onDismiss={() => dismiss(it.id)} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const tones: Record<ToastKind, string> = {
    success: "border-emerald-700/70 bg-emerald-950/90 text-emerald-200",
    error: "border-rose-800/70 bg-rose-950/95 text-rose-100",
    info: "border-border bg-surface/95 text-text",
  };
  const icons: Record<ToastKind, string> = { success: "✓", error: "⚠", info: "•" };
  return (
    <div
      role={item.kind === "error" ? "alert" : "status"}
      className={`pointer-events-auto flex items-start gap-2 rounded border px-3 py-2 text-xs shadow-lg backdrop-blur-sm ${tones[item.kind]}`}
    >
      <span className="select-none pt-0.5 font-bold">{icons[item.kind]}</span>
      <span className="flex-1 break-words whitespace-pre-wrap">{item.text}</span>
      <button
        onClick={onDismiss}
        className="select-none text-muted hover:text-text"
        aria-label="关闭通知"
      >
        ×
      </button>
    </div>
  );
}

// Hook to hand to useMutation: show toast on success / error with sensible defaults.
export function useMutationToast() {
  const toast = useToast();
  return {
    onSuccess: (msg: string) => () => toast.success(msg),
    onError: (prefix?: string) => (e: unknown) => {
      const text = e instanceof Error ? e.message : String(e);
      toast.error(prefix ? `${prefix}：${text}` : text);
    },
  };
}
