import { describe, it, expect, beforeEach } from "vitest";
import { defineComponent, h, withDirectives } from "vue";
import { mount } from "@vue/test-utils";
import { permissionDirective } from "@/directives/permission";
import { isAuthenticated } from "@/composables/useAuthGate";

// withDirectives stamps the directive onto a vnode without going through
// the template compiler, which keeps the tests independent of any global
// app.directive() registration.
function fixture(value: unknown, modifiers: Record<string, boolean> = {}) {
  return defineComponent({
    setup() {
      return () =>
        h("div", { class: "wrap" }, [
          withDirectives(h("button", { class: "target" }, "ok"), [
            [permissionDirective, value, "", modifiers],
          ]),
        ]);
    },
  });
}

describe("directives/v-permission", () => {
  beforeEach(() => {
    isAuthenticated.value = false;
  });

  it("hides the element when unauthenticated", () => {
    const w = mount(fixture("batch:delete"));
    expect(w.find(".target").exists()).toBe(false);
    expect(w.find(".wrap").element.innerHTML).toContain("v-permission");
  });

  it("renders the element when authenticated", () => {
    isAuthenticated.value = true;
    const w = mount(fixture("batch:delete"));
    expect(w.find(".target").exists()).toBe(true);
    expect(w.find(".target").text()).toBe("ok");
  });

  it("treats undefined value as no requirement", () => {
    isAuthenticated.value = true;
    const w = mount(fixture(undefined));
    expect(w.find(".target").exists()).toBe(true);
  });

  it("supports array value with all-mode default", () => {
    isAuthenticated.value = true;
    const w = mount(fixture(["a", "b"]));
    expect(w.find(".target").exists()).toBe(true);
  });

  it("supports the .any modifier (OR)", () => {
    isAuthenticated.value = true;
    const w = mount(fixture(["a", "b"], { any: true }));
    expect(w.find(".target").exists()).toBe(true);
  });
});
