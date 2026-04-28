import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { logout } from "./auth";
import { API } from "./api";
import { useLiveStream } from "./live";
import { useTheme } from "./theme";
import {
  IconBatches,
  IconBundles,
  IconChevronLeft,
  IconChevronRight,
  IconDashboard,
  IconEvents,
  IconLogout,
  IconMoon,
  IconReceivers,
  IconSettings,
  IconShared,
  IconSun,
  IconWorkers,
} from "./icons";

type NavItem = {
  to: string;
  label: string;
  icon: typeof IconDashboard;
  end?: boolean;
};

const NAV: NavItem[] = [
  { to: "/", label: "总览", icon: IconDashboard, end: true },
  { to: "/batches", label: "批次", icon: IconBatches },
  { to: "/bundles", label: "任务包", icon: IconBundles },
  { to: "/shared", label: "共享文件", icon: IconShared },
  { to: "/workers", label: "工作节点", icon: IconWorkers },
  { to: "/receivers", label: "接收端", icon: IconReceivers },
  { to: "/events", label: "事件日志", icon: IconEvents },
  { to: "/settings", label: "设置", icon: IconSettings },
];

const COLLAPSE_KEY = "sathop.sidebar.collapsed";

export function Layout() {
  const { connected } = useLiveStream();
  const [collapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem(COLLAPSE_KEY) === "1",
  );
  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  return (
    <div className="flex h-full bg-bg text-text">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar connected={connected} />
        <main className="flex-1 overflow-auto">
          <div className="mx-auto w-full max-w-[1480px] px-6 py-6 lg:px-8 lg:py-8">
            <div className="animate-fade-in">
              <Outlet />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const w = collapsed ? "w-[72px]" : "w-60";
  return (
    <aside
      className={`${w} relative flex shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 ease-out`}
      aria-label="主导航"
    >
      <Brand collapsed={collapsed} />

      <nav className="flex-1 overflow-y-auto px-3 py-3">
        {!collapsed && (
          <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted/80">
            控制台
          </div>
        )}
        <ul className="space-y-0.5">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                title={collapsed ? n.label : undefined}
                className={({ isActive }) =>
                  [
                    "group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition",
                    "outline-none",
                    isActive
                      ? "bg-accent-soft text-accent shadow-soft"
                      : "text-muted hover:bg-subtle hover:text-text",
                    collapsed ? "justify-center" : "",
                  ].join(" ")
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={`absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full transition ${
                        isActive ? "bg-accent" : "bg-transparent"
                      }`}
                      aria-hidden
                    />
                    <n.icon
                      className={`shrink-0 transition ${
                        isActive ? "text-accent" : "text-muted group-hover:text-text"
                      }`}
                    />
                    {!collapsed && <span className="truncate">{n.label}</span>}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-border p-3">
        <button
          type="button"
          onClick={logout}
          title={collapsed ? "退出登录" : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-muted transition hover:bg-subtle hover:text-text ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <IconLogout className="shrink-0" />
          {!collapsed && <span>退出登录</span>}
        </button>
      </div>

      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
        className="absolute -right-3 top-20 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted shadow-soft transition hover:text-text"
      >
        {collapsed ? <IconChevronRight width={12} height={12} /> : <IconChevronLeft width={12} height={12} />}
      </button>
    </aside>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="flex h-16 items-center gap-3 border-b border-border px-4">
      <div className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent/60 text-accent-fg shadow-glow">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3" />
          <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
        </svg>
        <span className="absolute -inset-px rounded-xl ring-1 ring-inset ring-white/15" aria-hidden />
      </div>
      {!collapsed && (
        <div className="min-w-0">
          <div className="font-display text-[15px] font-semibold leading-none tracking-tight">
            SatHop
          </div>
          <div className="mt-1 text-[10.5px] uppercase tracking-[0.18em] text-muted">
            Mission Console
          </div>
        </div>
      )}
    </div>
  );
}

const TITLES: Record<string, string> = Object.fromEntries(NAV.map((n) => [n.to, n.label]));

function TopBar({ connected }: { connected: boolean }) {
  const { pathname } = useLocation();
  const { batchId } = useParams();
  const { effective, toggle } = useTheme();
  // staleTime: orchestrator config doesn't change without a restart.
  const info = useQuery({
    queryKey: ["orch-info"],
    queryFn: API.orchestratorInfo,
    staleTime: 5 * 60_000,
  });

  // Crumbs only appear when nested (e.g. /batches/abc) — root sections own
  // their H1 inside content via <PageHeader>, so the topbar stays uncluttered.
  const crumbs = useMemo(() => {
    const segs = pathname.split("/").filter(Boolean);
    if (segs.length < 2) return [];
    const out: { label: string; to: string }[] = [];
    let acc = "";
    for (const s of segs) {
      acc += `/${s}`;
      const label =
        TITLES[acc] ??
        (s === batchId ? `批次 ${s.slice(0, 10)}…` : decodeURIComponent(s));
      out.push({ label, to: acc });
    }
    return out;
  }, [pathname, batchId]);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border bg-bg/85 px-6 backdrop-blur-md lg:px-8">
      <nav
        className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-muted"
        aria-label="面包屑"
      >
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <span key={c.to} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-border">/</span>}
              {last ? (
                <span className="font-medium text-text">{c.label}</span>
              ) : (
                <Link to={c.to} className="transition hover:text-text">
                  {c.label}
                </Link>
              )}
            </span>
          );
        })}
      </nav>

      <div className="flex items-center gap-2">
        {info.data?.auth_open && (
          <Link
            to="/settings"
            title="Orchestrator 未启用 API 鉴权 — 点击查看设置"
            className="hidden items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning transition hover:bg-warning/15 md:inline-flex"
          >
            <span className="relative grid h-1.5 w-1.5 place-items-center">
              <span className="absolute inset-0 rounded-full bg-warning animate-pulse-soft" />
            </span>
            未鉴权
          </Link>
        )}
        <LiveBadge connected={connected} />
        <button
          type="button"
          onClick={toggle}
          aria-label={effective === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
          title={effective === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
          className="grid h-9 w-9 place-items-center rounded-lg border border-border bg-surface text-muted transition hover:text-text hover:shadow-soft"
        >
          {effective === "dark" ? <IconSun /> : <IconMoon />}
        </button>
      </div>
    </header>
  );
}

function LiveBadge({ connected }: { connected: boolean }) {
  return (
    <span
      className={`hidden items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-medium md:inline-flex ${
        connected
          ? "border-success/30 bg-success/10 text-success"
          : "border-border bg-subtle text-muted"
      }`}
      title={connected ? "SSE 已连接" : "SSE 未连接"}
    >
      <span className="relative grid h-1.5 w-1.5 place-items-center">
        <span
          className={`absolute inset-0 rounded-full ${
            connected ? "bg-success animate-pulse-soft" : "bg-muted"
          }`}
        />
      </span>
      {connected ? "实时" : "离线"}
    </span>
  );
}
