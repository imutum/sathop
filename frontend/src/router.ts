import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

// Route-level code splitting keeps the initial page small while the default
// dashboard stays at the root path. `meta.title` populates document.title so
// browser history, tab labels and screen readers reflect the active page.
const childRoutes: RouteRecordRaw[] = [
  { path: "", name: "dashboard", component: () => import("./pages/Dashboard.vue"), meta: { title: "总览" } },
  { path: "settings", name: "settings", component: () => import("./pages/Settings.vue"), meta: { title: "设置" } },
  { path: "workers", name: "workers", component: () => import("./pages/Workers.vue"), meta: { title: "工作节点" } },
  { path: "receivers", name: "receivers", component: () => import("./pages/Receivers.vue"), meta: { title: "接收端" } },
  { path: "shared", name: "shared", component: () => import("./pages/SharedFiles.vue"), meta: { title: "共享文件" } },
  { path: "bundles", name: "bundles", component: () => import("./pages/Bundles.vue"), meta: { title: "任务包" } },
  { path: "events", name: "events", component: () => import("./pages/Events.vue"), meta: { title: "事件日志" } },
  { path: "batches", name: "batches", component: () => import("./pages/Batches.vue"), meta: { title: "批次" } },
  { path: "batches/:batchId", name: "batch-detail", component: () => import("./pages/BatchDetail.vue"), meta: { title: "批次详情" } },
];

if (import.meta.env.DEV) {
  childRoutes.push({
    path: "ui-kit",
    name: "ui-kit",
    component: () => import("./pages/UiKit.vue"),
    meta: { title: "UI Kit" },
  });
}

childRoutes.push({
  path: ":pathMatch(.*)*",
  name: "not-found",
  component: () => import("./pages/NotFound.vue"),
  meta: { title: "页面不存在" },
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

const BASE_TITLE = "SatHop · 控制面板";
router.afterEach((to) => {
  const pageTitle = (to.meta?.title as string | undefined) ?? "";
  document.title = pageTitle ? `${pageTitle} · ${BASE_TITLE}` : BASE_TITLE;
});
