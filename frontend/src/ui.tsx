import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";

export function Card(props: { children: ReactNode; title?: string; className?: string; action?: ReactNode }) {
  return (
    <div
      className={`rounded-lg border border-border bg-surface p-4 ${props.className ?? ""}`}
    >
      {(props.title || props.action) && (
        <div className="mb-3 flex items-center justify-between">
          {props.title && <h3 className="text-sm font-semibold text-text">{props.title}</h3>}
          {props.action}
        </div>
      )}
      {props.children}
    </div>
  );
}

export function Stat(props: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "warn" | "bad" | "good";
  to?: string;
}) {
  const colors = {
    default: "text-text",
    good: "text-emerald-400",
    warn: "text-amber-400",
    bad: "text-rose-400",
  };
  const base =
    "block rounded-lg border border-border bg-surface p-4" +
    (props.to ? " transition hover:border-accent hover:bg-bg cursor-pointer" : "");
  const inner = (
    <>
      <div className="text-xs uppercase tracking-wide text-muted">{props.label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${colors[props.tone ?? "default"]}`}>
        {props.value}
      </div>
      {props.hint && <div className="mt-1 text-xs text-muted">{props.hint}</div>}
    </>
  );
  return props.to ? (
    <Link to={props.to} className={base}>{inner}</Link>
  ) : (
    <div className={base}>{inner}</div>
  );
}

const badgeTones: Record<string, string> = {
  pending: "bg-slate-700 text-slate-200",
  downloading: "bg-sky-900/70 text-sky-300",
  downloaded: "bg-sky-900/70 text-sky-300",
  processing: "bg-indigo-900/70 text-indigo-300",
  processed: "bg-indigo-900/70 text-indigo-300",
  uploaded: "bg-violet-900/70 text-violet-300",
  acked: "bg-emerald-900/70 text-emerald-300",
  deleted: "bg-emerald-900/70 text-emerald-400",
  failed: "bg-rose-900/70 text-rose-300",
  blacklisted: "bg-rose-950 text-rose-400",
  info: "bg-slate-700 text-slate-200",
  warn: "bg-amber-900/70 text-amber-300",
  error: "bg-rose-900/70 text-rose-300",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const cls = badgeTones[tone ?? ""] ?? "bg-slate-700 text-slate-200";
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {children}
    </span>
  );
}

export function fmtGB(n: number): string {
  if (n >= 1024) return `${(n / 1024).toFixed(1)} TB`;
  return `${n.toFixed(1)} GB`;
}

/** Close the active modal on Escape. Pass the onClose handler the modal uses. */
export function useEscClose(onClose: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [onClose, enabled]);
}

/**
 * Standard modal shell. Handles backdrop click, Esc close, and centers content.
 * `onCloseIntent` is called for backdrop/Esc — caller can interpose a
 * "discard changes?" confirm there. `dirty=true` auto-warns on backdrop.
 */
export function Modal(props: {
  onClose: () => void;
  children: ReactNode;
  widthClass?: string; // e.g. "w-[720px]"
  dirty?: boolean;
  zIndex?: number;
}) {
  const z = props.zIndex ?? 50;
  const tryClose = () => {
    if (props.dirty && !confirm("表单有未保存的修改，放弃并关闭？")) return;
    props.onClose();
  };
  useEscClose(tryClose);
  return (
    <div
      className="fixed inset-0 flex items-center justify-center bg-black/60"
      style={{ zIndex: z }}
      onClick={tryClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`${props.widthClass ?? "w-[520px]"} max-h-[90vh] overflow-auto rounded-lg border border-border bg-surface p-5 shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        {props.children}
      </div>
    </div>
  );
}

type ActionTone = "primary" | "default" | "danger" | "ghost";

/** Button with built-in pending state: disables + swaps label, keeps width stable. */
export function ActionButton({
  tone = "default",
  pending = false,
  pendingLabel = "处理中…",
  children,
  className = "",
  disabled,
  ...rest
}: {
  tone?: ActionTone;
  pending?: boolean;
  pendingLabel?: string;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> & { disabled?: boolean }) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  const tones: Record<ActionTone, string> = {
    primary: "bg-accent text-white hover:bg-blue-600",
    default: "border border-border bg-bg text-muted hover:text-text",
    danger: "border border-rose-900 text-rose-400 hover:bg-rose-950/40",
    ghost: "text-muted hover:text-text",
  };
  return (
    <button
      {...rest}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={`${base} ${tones[tone]} ${className}`}
    >
      {pending && (
        <span
          aria-hidden
          className="inline-block h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
        />
      )}
      <span>{pending ? pendingLabel : children}</span>
    </button>
  );
}

/**
 * Tiny icon button that copies `value` on click and flashes "✓" for 1.4s.
 * Swallows the click so it can sit inside anchor/link rows without navigating.
 */
export function CopyButton({ value, title }: { value: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        });
      }}
      title={title ?? "复制"}
      aria-label={title ?? "复制"}
      className={`ml-1 inline-block select-none rounded px-1 text-[10px] leading-none transition ${
        copied
          ? "text-emerald-400"
          : "text-muted/60 hover:bg-bg hover:text-text"
      }`}
    >
      {copied ? "✓" : "⎘"}
    </button>
  );
}

export function ProgressBar({ value, max, tone = "accent" }: { value: number; max: number; tone?: "accent" | "good" | "warn" | "bad" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const colors = {
    accent: "bg-accent",
    good: "bg-emerald-500",
    warn: "bg-amber-500",
    bad: "bg-rose-500",
  };
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg">
      <div className={`h-full ${colors[tone]} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}
