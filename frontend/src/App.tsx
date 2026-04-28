import { Route, Routes, Link, useLocation } from "react-router-dom";
import { Suspense, lazy, type ReactNode } from "react";
import { useAuthGate } from "./auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { Layout } from "./Layout";
import { Dashboard } from "./pages/Dashboard";
import { ActionButton, Spinner } from "./ui";

// Dashboard loads eagerly because it's the landing route. Everything else
// is split into separate chunks so the initial bundle stays small.
const Batches = lazy(() => import("./pages/Batches").then((m) => ({ default: m.Batches })));
const BatchDetail = lazy(() => import("./pages/BatchDetail").then((m) => ({ default: m.BatchDetail })));
const Workers = lazy(() => import("./pages/Workers").then((m) => ({ default: m.Workers })));
const Receivers = lazy(() => import("./pages/Receivers").then((m) => ({ default: m.Receivers })));
const Events = lazy(() => import("./pages/Events").then((m) => ({ default: m.Events })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));
const Bundles = lazy(() => import("./pages/Bundles").then((m) => ({ default: m.Bundles })));
const SharedFiles = lazy(() => import("./pages/SharedFiles").then((m) => ({ default: m.SharedFiles })));

// Fresh ErrorBoundary per route. Keying by pathname resets the boundary on
// navigation so a crashed page doesn't stay crashed after the user navigates
// away and back. Suspense covers async chunk loading.
function RouteBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary key={pathname}>
      <Suspense fallback={<RouteFallback />}>{children}</Suspense>
    </ErrorBoundary>
  );
}

function RouteFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-xs text-muted">
      <Spinner />
      <span className="ml-2">加载中…</span>
    </div>
  );
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
    <div className="flex h-[60vh] items-center justify-center">
      <div className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 text-center shadow-card">
        <div className="font-display text-6xl font-semibold text-muted/40 tracking-tight">404</div>
        <div className="mt-3 text-sm font-medium">页面不存在</div>
        <div className="mt-2 break-all rounded-lg border border-border bg-subtle px-3 py-2 font-mono text-[11px] text-muted">
          {pathname}
        </div>
        <Link to="/" className="mt-5 inline-block">
          <ActionButton tone="primary">返回总览</ActionButton>
        </Link>
      </div>
    </div>
  );
}
