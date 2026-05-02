import { describe, it, expect, beforeEach } from "vitest";
import { hasPermission } from "@/composables/usePermissions";
import { isAuthenticated } from "@/composables/useAuthGate";

describe("composables/usePermissions", () => {
  beforeEach(() => {
    isAuthenticated.value = false;
  });

  it("denies everything when unauthenticated", () => {
    expect(hasPermission("anything")).toBe(false);
    expect(hasPermission(["a", "b"])).toBe(false);
    expect(hasPermission(undefined)).toBe(false);
  });

  it("grants every permission when authenticated (single-token model)", () => {
    isAuthenticated.value = true;
    expect(hasPermission("batch:delete")).toBe(true);
    expect(hasPermission(["batch:delete", "admin"])).toBe(true);
    expect(hasPermission(["batch:delete", "admin"], "any")).toBe(true);
  });

  it("treats undefined / empty as no requirement", () => {
    isAuthenticated.value = true;
    expect(hasPermission(undefined)).toBe(true);
    expect(hasPermission([])).toBe(true);
  });
});
