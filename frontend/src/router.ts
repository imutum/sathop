import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { hasPermission } from "@/composables/usePermissions";

// Route-level code splitting keeps the initial page small while the default
// dashboard stays at the root path.
const childRoutes: RouteRecordRaw[] = [
  { path: "", name: "dashboard", component: () => import("./pages/Dashboard.vue") },
  { path: "settings", name: "settings", component: () => import("./pages/Settings.vue") },
  { path: "workers", name: "workers", component: () => import("./pages/Workers.vue") },
  { path: "receivers", name: "receivers", component: () => import("./pages/Receivers.vue") },
  { path: "shared", name: "shared", component: () => import("./pages/SharedFiles.vue") },
  { path: "bundles", name: "bundles", component: () => import("./pages/Bundles.vue") },
  { path: "events", name: "events", component: () => import("./pages/Events.vue") },
  { path: "batches", name: "batches", component: () => import("./pages/Batches.vue") },
  { path: "batches/:batchId", name: "batch-detail", component: () => import("./pages/BatchDetail.vue") },
];

if (import.meta.env.DEV) {
  childRoutes.push({
    path: "ui-kit",
    name: "ui-kit",
    component: () => import("./pages/UiKit.vue"),
  });
}

childRoutes.push({
  path: ":pathMatch(.*)*",
  name: "not-found",
  component: () => import("./pages/NotFound.vue"),
});

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    component: () => import("@/layouts/AppLayout.vue"),
    children: childRoutes,
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Permission guard. Routes can declare `meta: { permission: 'name' }` (or an
// array, with an optional `permissionMode: 'any'` for OR semantics). When the
// check fails, push the user back to '/' rather than rendering a 403 — there
// is no permission UI today; the guard exists for future role-based features.
//
// Auth gating itself stays at the App.vue level (Login splash on !ready),
// which preserves the OPEN-mode probe UX without flashing /login during
// orchestrator-without-token boots.
router.beforeEach((to) => {
  const perm = to.meta.permission as string | string[] | undefined;
  const mode = (to.meta.permissionMode as "all" | "any" | undefined) ?? "all";
  if (perm && !hasPermission(perm, mode)) {
    return { path: "/", replace: true };
  }
  return true;
});
