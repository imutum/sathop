import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";
import { IconAlert, IconCheck, IconInfo, IconX } from "./icons";

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
        className="pointer-events-none fixed right-5 bottom-5 z-[100] flex w-[340px] flex-col gap-2.5"
      >
        {items.map((it) => (
          <Toast key={it.id} item={it} onDismiss={() => dismiss(it.id)} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const tones: Record<ToastKind, { wrap: string; icon: string }> = {
    success: {
      wrap: "border-success/30 bg-success/10 text-text",
      icon: "text-success bg-success/15",
    },
    error: {
      wrap: "border-danger/30 bg-danger/10 text-text",
      icon: "text-danger bg-danger/15",
    },
    info: {
      wrap: "border-border bg-surface/95 text-text",
      icon: "text-accent bg-accent/15",
    },
  };
  const Icon =
    item.kind === "success" ? IconCheck : item.kind === "error" ? IconAlert : IconInfo;
  return (
    <div
      role={item.kind === "error" ? "alert" : "status"}
      className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-xs shadow-pop backdrop-blur-md animate-slide-up ${tones[item.kind].wrap}`}
    >
      <span
        className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg ${tones[item.kind].icon}`}
        aria-hidden
      >
        <Icon width={13} height={13} />
      </span>
      <span className="flex-1 break-words whitespace-pre-wrap leading-relaxed text-text">
        {item.text}
      </span>
      <button
        onClick={onDismiss}
        className="grid h-5 w-5 place-items-center rounded text-muted transition hover:bg-subtle hover:text-text"
        aria-label="关闭通知"
      >
        <IconX width={12} height={12} />
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
