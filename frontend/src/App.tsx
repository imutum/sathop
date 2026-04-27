import { Route, Routes, Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuthGate } from "./auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { Layout } from "./Layout";
import { Dashboard } from "./pages/Dashboard";
import { Batches } from "./pages/Batches";
import { BatchDetail } from "./pages/BatchDetail";
import { Workers } from "./pages/Workers";
import { Receivers } from "./pages/Receivers";
import { Events } from "./pages/Events";
import { Settings } from "./pages/Settings";
import { Bundles } from "./pages/Bundles";
import { SharedFiles } from "./pages/SharedFiles";

// Fresh ErrorBoundary per route. Keying by pathname resets the boundary on
// navigation so a crashed page doesn't stay crashed after the user navigates
// away and back.
function RouteBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}

export function App() {
  const { ready, Login } = useAuthGate();
  if (!ready) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<RouteBoundary><Dashboard /></RouteBoundary>} />
        <Route path="batches" element={<RouteBoundary><Batches /></RouteBoundary>} />
        <Route path="batches/:batchId" element={<RouteBoundary><BatchDetail /></RouteBoundary>} />
        <Route path="workers" element={<RouteBoundary><Workers /></RouteBoundary>} />
        <Route path="receivers" element={<RouteBoundary><Receivers /></RouteBoundary>} />
        <Route path="events" element={<RouteBoundary><Events /></RouteBoundary>} />
        <Route path="settings" element={<RouteBoundary><Settings /></RouteBoundary>} />
        <Route path="bundles" element={<RouteBoundary><Bundles /></RouteBoundary>} />
        <Route path="shared" element={<RouteBoundary><SharedFiles /></RouteBoundary>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  const { pathname } = useLocation();
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-[420px] rounded-lg border border-border bg-surface p-6 text-center">
        <div className="text-4xl font-semibold text-muted">404</div>
        <div className="mt-2 text-sm">页面不存在</div>
        <div className="mt-1 break-all font-mono text-xs text-muted">{pathname}</div>
        <Link
          to="/"
          className="mt-4 inline-block rounded bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
        >
          返回总览
        </Link>
      </div>
    </div>
  );
}
