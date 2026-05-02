import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { Button, buttonVariants } from "@/components/ui/button";

describe("ui/Button", () => {
  it("renders default variant + slot content", () => {
    const w = mount(Button, { slots: { default: "提交" } });
    expect(w.text()).toBe("提交");
    expect(w.classes()).toContain("bg-primary");
  });

  it("applies destructive variant", () => {
    const w = mount(Button, { props: { variant: "destructive" } });
    expect(w.classes()).toContain("bg-destructive");
  });

  it("applies size sm", () => {
    const w = mount(Button, { props: { size: "sm" } });
    expect(w.classes()).toContain("h-8");
  });

  it("buttonVariants() composes class string", () => {
    const cls = buttonVariants({ variant: "outline", size: "lg" });
    expect(cls).toContain("border-input");
    expect(cls).toContain("h-10");
  });

  it("merges user class via cn()", () => {
    const w = mount(Button, { props: { class: "custom-x" } });
    expect(w.classes()).toContain("custom-x");
  });

  it("shows spinner + pendingLabel when pending=true", () => {
    const w = mount(Button, {
      props: { pending: true, pendingLabel: "上传中…" },
      slots: { default: "上传" },
    });
    expect(w.text()).toBe("上传中…");
    expect(w.text()).not.toContain("上传 "); // slot suppressed
    expect(w.find("svg").exists()).toBe(true);
    expect(w.attributes("aria-busy")).toBe("true");
    expect(w.attributes("disabled")).toBeDefined();
  });

  it("falls back to default pendingLabel when omitted", () => {
    const w = mount(Button, {
      props: { pending: true },
      slots: { default: "保存" },
    });
    expect(w.text()).toBe("处理中…");
  });

  it("renders slot content when pending=false", () => {
    const w = mount(Button, {
      props: { pending: false, pendingLabel: "上传中…" },
      slots: { default: "上传" },
    });
    expect(w.text()).toBe("上传");
    expect(w.find("svg").exists()).toBe(false);
    expect(w.attributes("aria-busy")).toBeUndefined();
  });

  it("respects explicit disabled even when not pending", () => {
    const w = mount(Button, { props: { disabled: true } });
    expect(w.attributes("disabled")).toBeDefined();
  });
});
