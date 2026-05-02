/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

// Per-route metadata understood by the global beforeEach guard.
// permission: required permission(s) — guard checks via hasPermission().
// permissionMode: 'all' (default) | 'any' for OR semantics.
import "vue-router";
declare module "vue-router" {
  interface RouteMeta {
    permission?: string | string[];
    permissionMode?: "all" | "any";
  }
}
