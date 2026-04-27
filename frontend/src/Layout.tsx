import { NavLink, Outlet } from "react-router-dom";
import { logout } from "./auth";
import { useLiveStream } from "./live";

const nav = [
  { to: "/", label: "总览", end: true },
  { to: "/batches", label: "批次" },
  { to: "/bundles", label: "任务包" },
  { to: "/shared", label: "共享文件" },
  { to: "/workers", label: "工作节点" },
  { to: "/receivers", label: "接收端" },
  { to: "/events", label: "事件日志" },
  { to: "/settings", label: "设置" },
];

export function Layout() {
  useLiveStream();
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-5 py-4">
          <div className="text-base font-semibold tracking-tight">SatHop</div>
          <div className="text-xs text-muted">控制面板</div>
        </div>
        <nav className="flex-1 p-3" aria-label="主导航">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `block rounded border-l-2 px-3 py-2 text-sm transition ${
                  isActive
                    ? "border-accent bg-bg font-medium text-text"
                    : "border-transparent text-muted hover:bg-bg hover:text-text"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          <button
            onClick={logout}
            className="w-full rounded px-3 py-2 text-left text-xs text-muted hover:bg-bg hover:text-text"
          >
            退出登录
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
