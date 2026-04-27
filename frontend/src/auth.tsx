import { useEffect, useState } from "react";
import { API, setToken } from "./api";

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

  const Login = () => (
    <div className="flex h-full items-center justify-center">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const t = input.trim();
          if (!t) return;
          setProbing(true);
          setErr(null);
          // Set token BEFORE probing so the fetch wrapper attaches it. Roll back
          // on failure so the user isn't left in a broken state.
          const prev = localStorage.getItem("sathop.token");
          setToken(t);
          try {
            await API.orchestratorInfo();
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
        className="w-[360px] rounded-lg border border-border bg-surface p-6 shadow-lg"
      >
        <h1 className="mb-1 text-lg font-semibold">SatHop</h1>
        <p className="mb-5 text-xs text-muted">请输入 Orchestrator 令牌。</p>
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
          placeholder="API 令牌"
          className="w-full rounded border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
        />
        {err && (
          <div className="mt-2 rounded border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={probing || !input.trim()}
          aria-busy={probing || undefined}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {probing && (
            <span className="inline-block h-3 w-3 animate-spin rounded-full border border-white border-t-transparent" />
          )}
          {probing ? "验证中…" : "进入"}
        </button>
      </form>
    </div>
  );
  return { ready, Login };
}

export function logout(): void {
  localStorage.removeItem("sathop.token");
  window.location.reload();
}
