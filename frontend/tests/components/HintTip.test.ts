import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { TooltipProvider } from "@/components/ui/tooltip";
import HintTip from "@/components/HintTip.vue";

// HintTip needs a TooltipProvider somewhere in the ancestor chain
// (App.vue installs one in production); wrap the mount under it here.
function makeHost(slotsContent: () => unknown) {
  return defineComponent({
    setup() {
      return () => h(TooltipProvider, null, slotsContent);
    },
  });
}

describe("components/HintTip", () => {
  it("renders the slot only (no tooltip wrapper) when text is empty", () => {
    const w = mount(
      makeHost(() => h(HintTip, { text: "" }, () => h("button", { id: "kid" }, "go"))),
    );
    expect(w.find("#kid").exists()).toBe(true);
    // TooltipTrigger renders the asChild element, but with no surrounding
    // popup attributes when the wrapper short-circuits — easiest signal: no
    // data-state attribute on the button.
    expect(w.find("[data-state]").exists()).toBe(false);
  });

  it("renders the slot only when text is null (passthrough-empty default)", () => {
    const w = mount(
      makeHost(() => h(HintTip, { text: null }, () => h("button", { id: "kid" }, "go"))),
    );
    expect(w.find("#kid").exists()).toBe(true);
    expect(w.find("[data-state]").exists()).toBe(false);
  });

  it("wires the tooltip trigger when text is non-empty", () => {
    const w = mount(
      makeHost(() => h(HintTip, { text: "复制" }, () => h("button", { id: "kid" }, "go"))),
    );
    expect(w.find("#kid").exists()).toBe(true);
    // reka-ui sets data-state="closed" on the trigger before hover.
    expect(w.find("#kid").attributes("data-state")).toBe("closed");
  });

  it("respects passthrough-empty=false: keeps the wrapper even with empty text", () => {
    const w = mount(
      makeHost(() =>
        h(
          HintTip,
          { text: "", passthroughEmpty: false },
          () => h("button", { id: "kid" }, "go"),
        ),
      ),
    );
    expect(w.find("#kid").attributes("data-state")).toBe("closed");
  });
});
