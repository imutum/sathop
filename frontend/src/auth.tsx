import { useEffect, useState } from "react";
import { API, setToken, suspendAuthRecovery } from "./api";
import { Alert, FieldLabel, Spinner } from "./ui";

export function useAuthGate(): { ready: boolean; Login: () => JSX.Element } {
  const [ready, setReady] = useState(() => !!localStorage.getItem("sathop.token"));
  const [input, setInput] = useState("");
  const [probing, setProbing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onStorage = () => setReady(!!localStorage.getItem("sathop.token"));
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // Open mode auto-skip: if orchestrator answers without auth, skip the prompt.
  // Uses the same probe as the login form (suspended) so a 401 doesn't trigger
  // the page-reload recovery loop.
  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    suspendAuthRecovery(() => API.orchestratorInfo())
      .then(() => {
        if (cancelled) return;
        setToken("open");
        setReady(true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [ready]);

  const Login = () => (
    <div className="relative flex h-full items-center justify-center overflow-hidden bg-bg">
      <div aria-hidden className="bg-radial-fade pointer-events-none absolute inset-0" />
      <div aria-hidden className="bg-dotgrid pointer-events-none absolute inset-0 opacity-40" />

      <div className="relative grid w-full max-w-[920px] gap-10 px-6 lg:grid-cols-[1.1fr_1fr]">
        {/* Marketing-style brand panel */}
        <div className="hidden flex-col justify-between lg:flex">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-accent to-accent/60 text-accent-fg shadow-glow">
              <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3" />
                <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
              </svg>
            </div>
            <div>
              <div className="font-display text-lg font-semibold tracking-tight">SatHop</div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-muted">
                Mission Console
              </div>
            </div>
          </div>

          <div className="space-y-6">
            <h1 className="font-display text-balance text-3xl font-semibold leading-tight tracking-tight">
              卫星数据
              <br />
              下载 · 处理 · 分发
              <br />
              <span className="text-accent">一站调度</span>
            </h1>
            <p className="max-w-sm text-sm leading-relaxed text-muted">
              基于 lease 的分布式管线 · SQLite 单事实状态 · 实时事件流
              · 用户脚本任务包热插拔。
            </p>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
              <Tag>Orchestrator</Tag>
              <Tag>Worker</Tag>
              <Tag>Receiver</Tag>
              <Tag>Bundle Registry</Tag>
            </div>
          </div>

          <div className="text-[11px] text-muted">
            © {new Date().getFullYear()} SatHop · Pull-based · HTTP-only
          </div>
        </div>

        {/* Login card */}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const t = input.trim();
            if (!t) return;
            setProbing(true);
            setErr(null);
            const prev = localStorage.getItem("sathop.token");
            setToken(t);
            try {
              await suspendAuthRecovery(() => API.orchestratorInfo());
              setReady(true);
            } catch (e) {
              const msg = (e as Error).message;
              if (prev) setToken(prev);
              else localStorage.removeItem("sathop.token");
              if (msg.startsWith("401") || msg.startsWith("403")) {
                setErr("令牌被 Orchestrator 拒绝，请检查 SATHOP_TOKEN。");
              } else {
                setErr(`无法连接 Orchestrator：${msg}`);
              }
            } finally {
              setProbing(false);
            }
          }}
          className="rounded-2xl border border-border bg-surface/80 p-8 shadow-pop backdrop-blur-xl"
        >
          <div className="mb-6">
            <div className="font-display text-xl font-semibold tracking-tight">欢迎回来</div>
            <p className="mt-1.5 text-xs text-muted">
              使用 Orchestrator 的 <code className="rounded bg-subtle px-1 py-0.5 font-mono text-[10.5px]">SATHOP_TOKEN</code> 登录。
            </p>
          </div>

          <label className="block">
            <FieldLabel>API 令牌</FieldLabel>
            <input
              autoFocus
              type="password"
              autoComplete="current-password"
              aria-label="Orchestrator API 令牌"
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                if (err) setErr(null);
              }}
              placeholder="sk_… 或部署时设置的 token"
              className="mt-2 w-full rounded-lg border border-border bg-bg px-3 py-2.5 font-mono text-sm text-text outline-none transition placeholder:text-muted/60 hover:border-accent/40 focus:border-accent"
            />
          </label>

          {err && (
            <div className="mt-3 animate-fade-in">
              <Alert>{err}</Alert>
            </div>
          )}

          <button
            type="submit"
            disabled={probing || !input.trim()}
            aria-busy={probing || undefined}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2.5 text-sm font-semibold text-accent-fg shadow-glow transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {probing && <Spinner className="text-accent-fg/70" />}
            {probing ? "验证中…" : "进入控制台"}
          </button>

          <div className="mt-6 border-t border-border pt-4 text-[11px] leading-relaxed text-muted">
            令牌仅保存在本浏览器 localStorage。
            如需轮换，请在 Orchestrator 容器重新设置 <span className="font-mono text-text">SATHOP_TOKEN</span>。
          </div>
        </form>
      </div>
    </div>
  );

  return { ready, Login };
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-border bg-surface/80 px-2.5 py-1 font-mono text-[10.5px] text-muted backdrop-blur">
      {children}
    </span>
  );
}

export function logout(): void {
  localStorage.removeItem("sathop.token");
  window.location.reload();
}
