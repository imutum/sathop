import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

// Lazy chunks: only Dashboard is eager (landing page). Each subsequent page
// migration will register itself here.
const routes: RouteRecordRaw[] = [
  {
    path: "/",
    component: () => import("./Layout.vue"),
    children: [
      { path: "", name: "dashboard", component: () => import("./pages/Dashboard.vue") },
      { path: "settings", name: "settings", component: () => import("./pages/Settings.vue") },
      { path: "workers", name: "workers", component: () => import("./pages/Workers.vue") },
      { path: "receivers", name: "receivers", component: () => import("./pages/Receivers.vue") },
      { path: "shared", name: "shared", component: () => import("./pages/SharedFiles.vue") },
      { path: "bundles", name: "bundles", component: () => import("./pages/Bundles.vue") },
      { path: "events", name: "events", component: () => import("./pages/Events.vue") },
      { path: "batches", name: "batches", component: () => import("./pages/Batches.vue") },
      { path: "batches/:batchId", name: "batch-detail", component: () => import("./pages/BatchDetail.vue") },
      // Pending: real Dashboard, CreateBatchModal.
      { path: ":pathMatch(.*)*", name: "not-found", component: () => import("./pages/NotFound.vue") },
    ],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
