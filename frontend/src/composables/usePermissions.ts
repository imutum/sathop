import { computed, type Ref } from "vue";
import { isAuthenticated } from "@/composables/useAuthGate";

// Permission-check facade. SatHop's orchestrator currently ships a single
// bearer token with no role/permission shape — every authenticated user is
// authorized for everything. So today `hasPermission` is just a proxy for
// `isAuthenticated`.
//
// When the backend grows roles or scoped tokens, the only changes here are
// (1) populate `grantedSet` from the auth response, and (2) flip
// `hasPermission` to a real set-membership check. The directive +
// router-guard call sites stay untouched.

export type Permission = string;

// Reactive set of granted permissions. Empty today; reserved for the
// future roles model.
const grantedSet: Ref<ReadonlySet<Permission>> = computed(() => new Set<Permission>());

export function hasPermission(perm: Permission | Permission[] | undefined, mode: "all" | "any" = "all"): boolean {
  if (!isAuthenticated.value) return false;
  if (perm === undefined) return true;
  const list = Array.isArray(perm) ? perm : [perm];
  if (list.length === 0) return true;
  // Single-token model: authenticated implies all permissions. Once
  // grantedSet has entries, switch to set-membership only.
  if (grantedSet.value.size === 0) return true;
  const check = (p: Permission) => grantedSet.value.has(p);
  return mode === "all" ? list.every(check) : list.some(check);
}

export function usePermissions() {
  const can = (perm: Permission | Permission[], mode: "all" | "any" = "all") =>
    hasPermission(perm, mode);
  return { can, hasPermission };
}
