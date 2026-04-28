import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconCheck, IconCopy } from "./icons";

export function Card(props: {
  children: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  className?: string;
  bodyClassName?: string;
  action?: ReactNode;
  padded?: boolean;
}) {
  const padded = props.padded ?? true;
  return (
    <section
      className={`rounded-2xl border border-border bg-surface shadow-card ${
        props.className ?? ""
      }`}
    >
      {(props.title || props.action) && (
        <header className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
          <div className="min-w-0">
            {props.title && (
              <h3 className="font-display text-[13.5px] font-semibold tracking-tight text-text">
                {props.title}
              </h3>
            )}
            {props.description && (
              <p className="mt-0.5 text-xs text-muted">{props.description}</p>
            )}
          </div>
          {props.action && <div className="shrink-0">{props.action}</div>}
        </header>
      )}
      <div
        className={`${padded ? "p-5" : ""} ${props.bodyClassName ?? ""}`}
      >
        {props.children}
      </div>
    </section>
  );
}

export function Stat(props: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "warn" | "bad" | "good";
  to?: string;
  icon?: ReactNode;
}) {
  const dot = {
    default: "bg-accent",
    good: "bg-success",
    warn: "bg-warning",
    bad: "bg-danger",
  }[props.tone ?? "default"];

  const valueColor = {
    default: "text-text",
    good: "text-success",
    warn: "text-warning",
    bad: "text-danger",
  }[props.tone ?? "default"];

  const base =
    "group relative block overflow-hidden rounded-2xl border border-border bg-surface p-5 shadow-card transition" +
    (props.to ? " hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-pop" : "");

  const inner = (
    <>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
          {props.label}
        </span>
        {props.icon && (
          <span className="text-muted/70 transition group-hover:text-accent">
            {props.icon}
          </span>
        )}
      </div>
      <div
        className={`font-display mt-3 text-[32px] font-semibold leading-none tabular-nums tracking-tight ${valueColor}`}
      >
        {props.value}
      </div>
      {props.hint && <div className="mt-2 text-xs text-muted">{props.hint}</div>}
      {props.to && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 -bottom-px h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent opacity-0 transition group-hover:opacity-100"
        />
      )}
    </>
  );

  return props.to ? (
    <Link to={props.to} className={base}>
      {inner}
    </Link>
  ) : (
    <div className={base}>{inner}</div>
  );
}

const badgeTones = {
  pending: "bg-subtle text-muted ring-border",
  downloading: "bg-sky-500/10 text-sky-500 ring-sky-500/25 dark:text-sky-300",
  downloaded: "bg-sky-500/10 text-sky-500 ring-sky-500/25 dark:text-sky-300",
  processing: "bg-indigo-500/10 text-indigo-500 ring-indigo-500/25 dark:text-indigo-300",
  processed: "bg-indigo-500/10 text-indigo-500 ring-indigo-500/25 dark:text-indigo-300",
  uploaded: "bg-violet-500/10 text-violet-500 ring-violet-500/25 dark:text-violet-300",
  acked: "bg-success/10 text-success ring-success/25",
  deleted: "bg-success/10 text-success ring-success/25",
  failed: "bg-danger/10 text-danger ring-danger/25",
  blacklisted: "bg-danger/15 text-danger ring-danger/30",
  info: "bg-subtle text-muted ring-border",
  warn: "bg-warning/12 text-warning ring-warning/30",
  error: "bg-danger/12 text-danger ring-danger/30",
} as const;

export type BadgeTone = keyof typeof badgeTones;

export function Badge({
  children,
  tone,
  dot,
}: {
  children: ReactNode;
  tone?: BadgeTone | string;
  dot?: boolean;
}) {
  const cls =
    (tone && Object.prototype.hasOwnProperty.call(badgeTones, tone)
      ? badgeTones[tone as BadgeTone]
      : null) ?? "bg-subtle text-muted ring-border";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${cls}`}
    >
      {dot && (
        <span
          className="h-1.5 w-1.5 rounded-full bg-current opacity-70"
          aria-hidden
        />
      )}
      {children}
    </span>
  );
}

export function fmtGB(n: number): string {
  if (n >= 1024) return `${(n / 1024).toFixed(1)} TB`;
  return `${n.toFixed(1)} GB`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** Close the active modal on Escape. Pass the onClose handler the modal uses. */
function useEscClose(onClose: () => void, enabled = true) {
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

export function Modal(props: {
  onClose: () => void;
  children: ReactNode;
  widthClass?: string;
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
      className="fixed inset-0 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm"
      style={{ zIndex: z }}
      onClick={tryClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`${props.widthClass ?? "w-[520px]"} relative max-h-[90vh] overflow-auto rounded-2xl border border-border bg-elevated p-6 shadow-pop animate-scale-in`}
        onClick={(e) => e.stopPropagation()}
      >
        {props.children}
      </div>
    </div>
  );
}

type ActionTone = "primary" | "default" | "danger" | "ghost" | "outline";

export function ActionButton({
  tone = "default",
  pending = false,
  pendingLabel = "处理中…",
  children,
  className = "",
  disabled,
  size = "md",
  ...rest
}: {
  tone?: ActionTone;
  pending?: boolean;
  pendingLabel?: string;
  size?: "sm" | "md";
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> & { disabled?: boolean }) {
  const sizeCls =
    size === "sm"
      ? "h-7 px-2.5 text-[11px] gap-1"
      : "h-8 px-3 text-xs gap-1.5";
  const base =
    "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition " +
    "disabled:cursor-not-allowed disabled:opacity-50 " +
    "active:translate-y-px";
  const tones: Record<ActionTone, string> = {
    primary:
      "bg-accent text-accent-fg shadow-soft hover:bg-accent/90 hover:shadow-glow",
    default:
      "border border-border bg-surface text-text hover:border-accent/40 hover:bg-subtle",
    danger:
      "border border-danger/30 bg-danger/10 text-danger hover:bg-danger/15",
    ghost: "text-muted hover:bg-subtle hover:text-text",
    outline:
      "border border-accent/40 bg-transparent text-accent hover:bg-accent-soft",
  };
  return (
    <button
      {...rest}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={`${base} ${sizeCls} ${tones[tone]} ${className}`}
    >
      {pending && (
        <span
          aria-hidden
          className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border border-current border-t-transparent"
        />
      )}
      {pending ? pendingLabel : children}
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  className = "",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; count?: number; dim?: boolean }[];
  size?: "sm" | "md";
  className?: string;
}) {
  const h = size === "sm" ? "h-7 text-[11px] px-2.5" : "h-8 text-xs px-3";
  return (
    <div
      role="tablist"
      className={`inline-flex items-center gap-0.5 rounded-lg border border-border bg-subtle p-0.5 ${className}`}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={`${h} inline-flex items-center gap-1.5 rounded-md font-medium transition ${
              active
                ? "bg-surface text-text shadow-soft"
                : o.dim
                  ? "text-muted/50 hover:text-muted"
                  : "text-muted hover:text-text"
            }`}
          >
            {o.label}
            {o.count !== undefined && (
              <span
                className={`tabular-nums text-[10.5px] ${
                  active ? "text-muted" : "text-muted/70"
                }`}
              >
                {o.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

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
      className={`ml-1 inline-grid h-5 w-5 place-items-center rounded-md transition ${
        copied
          ? "text-success"
          : "text-muted/60 hover:bg-subtle hover:text-text"
      }`}
    >
      {copied ? <IconCheck width={11} height={11} /> : <IconCopy width={11} height={11} />}
    </button>
  );
}

export function ProgressBar({
  value,
  max,
  tone = "accent",
}: {
  value: number;
  max: number;
  tone?: "accent" | "good" | "warn" | "bad";
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const colors = {
    accent: "bg-accent",
    good: "bg-success",
    warn: "bg-warning",
    bad: "bg-danger",
  };
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-subtle">
      <div
        className={`h-full ${colors[tone]} transition-[width] duration-500 ease-out`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-display text-balance text-2xl font-semibold tracking-tight text-text">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm text-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      {icon && (
        <div className="grid h-12 w-12 place-items-center rounded-2xl border border-border bg-subtle text-muted">
          {icon}
        </div>
      )}
      <div className="text-sm font-medium text-text">{title}</div>
      {description && (
        <div className="max-w-md text-xs text-muted">{description}</div>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** Enable/disable + forget buttons shared by Workers & Receivers. The page
 * owns the mutations (so toast wording stays domain-specific); this just
 * paints the buttons and routes confirm() through them. */
export function NodeLifecycleActions(props: {
  enabled: boolean;
  pending: boolean;
  onSetEnabled: (next: boolean) => void;
  onForget: () => void;
  disableConfirm: string;
  forgetConfirm: string;
  disableTitle?: string;
  forgetTitle?: string;
}) {
  const { enabled, pending, onSetEnabled, onForget } = props;
  return (
    <span className="flex items-center gap-1.5">
      <button
        type="button"
        disabled={pending}
        onClick={() => {
          if (enabled && !confirm(props.disableConfirm)) return;
          onSetEnabled(!enabled);
        }}
        className={`rounded-md border px-2 py-0.5 text-[10.5px] font-medium transition disabled:opacity-50 ${
          enabled
            ? "border-border bg-surface text-muted hover:border-danger/40 hover:text-danger"
            : "border-success/30 bg-success/10 text-success hover:bg-success/15"
        }`}
        title={enabled ? props.disableTitle ?? "禁用此节点" : "重新启用此节点"}
      >
        {pending ? "…" : enabled ? "禁用" : "启用"}
      </button>
      {!enabled && (
        <button
          type="button"
          disabled={pending}
          onClick={() => {
            if (!confirm(props.forgetConfirm)) return;
            onForget();
          }}
          className="rounded-md border border-danger/30 bg-danger/10 px-2 py-0.5 text-[10.5px] font-medium text-danger transition hover:bg-danger/15 disabled:opacity-50"
          title={props.forgetTitle ?? "永久从注册表中删除"}
        >
          {pending ? "…" : "移除"}
        </button>
      )}
    </span>
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-[0.10em] text-muted">
      {children}
    </span>
  );
}

// Read-only labeled value used in metadata grids (Bundles / BatchDetail / Settings).
// `mono` switches the value to a fixed-width style; `hint` pins a small warning chip.
export function Field({
  label,
  children,
  mono,
  hint,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <div>
      <div className="text-[10.5px] font-medium uppercase tracking-[0.12em] text-muted">
        {label}
      </div>
      <div className={`mt-1.5 flex items-center break-all ${mono ? "font-mono text-[11.5px]" : "text-sm"}`}>
        {children}
        {hint && (
          <span className="ml-2 rounded bg-warning/15 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
            {hint}
          </span>
        )}
      </div>
    </div>
  );
}

export function Spinner({ size = 14, className = "" }: { size?: number; className?: string }) {
  return (
    <span
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
      style={{ width: size, height: size, borderWidth: Math.max(1, Math.round(size / 7)) }}
      aria-hidden
    />
  );
}

// Heartbeat tone/label shared by Workers + Receivers (pages keep thresholds in lockstep).
export function nodeStatusBadge(enabled: boolean, lastSeenISO: string): { tone: BadgeTone; label: string } {
  if (!enabled) return { tone: "error", label: "已禁用" };
  const sec = (Date.now() - new Date(lastSeenISO).getTime()) / 1000;
  if (sec < 60) return { tone: "acked", label: "在线" };
  if (sec < 300) return { tone: "warn", label: "待机" };
  return { tone: "error", label: "离线" };
}

export function Alert({
  tone = "danger",
  children,
}: {
  tone?: "danger" | "warn" | "info";
  children: ReactNode;
}) {
  const cls = {
    danger: "border-danger/30 bg-danger/10 text-danger",
    warn: "border-warning/30 bg-warning/10 text-warning",
    info: "border-border bg-subtle text-text",
  }[tone];
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${cls}`}>{children}</div>
  );
}

export function TextInput(
  props: React.InputHTMLAttributes<HTMLInputElement> & { leftIcon?: ReactNode },
) {
  const { leftIcon, className = "", ...rest } = props;
  return (
    <div className="relative">
      {leftIcon && (
        <span className="pointer-events-none absolute inset-y-0 left-2.5 grid place-items-center text-muted">
          {leftIcon}
        </span>
      )}
      <input
        {...rest}
        className={`h-8 w-full rounded-lg border border-border bg-surface text-xs text-text outline-none transition placeholder:text-muted/70 hover:border-accent/40 focus:border-accent ${
          leftIcon ? "pl-8 pr-3" : "px-3"
        } ${className}`}
      />
    </div>
  );
}
