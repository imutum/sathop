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
});
