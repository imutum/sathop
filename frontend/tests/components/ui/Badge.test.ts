import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { Badge, BADGE_TONES } from "@/components/ui/badge";

describe("ui/Badge", () => {
  it("renders default variant + slot content", () => {
    const w = mount(Badge, { slots: { default: "在线" } });
    expect(w.text()).toBe("在线");
    expect(w.classes()).toContain("bg-primary");
  });

  it("variant=warning maps to warning bg/text", () => {
    const w = mount(Badge, { props: { variant: "warning" } });
    expect(w.classes().some((c) => c.startsWith("bg-warning"))).toBe(true);
  });

  it("tone='acked' applies BADGE_TONES.acked classes", () => {
    const w = mount(Badge, { props: { tone: "acked" } });
    expect(w.classes().some((c) => c.startsWith("bg-success"))).toBe(true);
    expect(w.classes()).toContain("text-success");
  });

  it("unknown tone falls back to info palette", () => {
    const w = mount(Badge, { props: { tone: "unknown_state_xyz" } });
    expect(w.classes()).toContain("bg-muted");
    expect(w.classes()).toContain("text-muted-foreground");
  });

  it("dot=true prepends a status dot span", () => {
    const w = mount(Badge, {
      props: { dot: true, tone: "queued" },
      slots: { default: "排队中" },
    });
    const dot = w.find("span[aria-hidden]");
    expect(dot.exists()).toBe(true);
    expect(dot.classes()).toContain("rounded-full");
  });

  it("BADGE_TONES exposes all 14 state keys", () => {
    expect(Object.keys(BADGE_TONES).sort()).toEqual(
      [
        "acked",
        "blacklisted",
        "deleted",
        "downloaded",
        "downloading",
        "error",
        "failed",
        "info",
        "pending",
        "processed",
        "processing",
        "queued",
        "uploaded",
        "warn",
      ].sort(),
    );
  });
});
