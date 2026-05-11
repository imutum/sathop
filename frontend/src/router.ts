import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

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
