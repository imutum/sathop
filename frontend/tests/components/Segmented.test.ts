import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import Segmented from "@/components/Segmented.vue";

const OPTIONS = [
  { value: "a", label: "A" },
  { value: "b", label: "B" },
  { value: "c", label: "C" },
];

function make(initial = "a") {
  return mount(Segmented, {
    props: { modelValue: initial, options: OPTIONS, "onUpdate:modelValue": () => {} },
  });
}

describe("components/Segmented", () => {
  it("renders as a radiogroup with one radio per option", () => {
    const w = make();
    expect(w.attributes("role")).toBe("radiogroup");
    const radios = w.findAll('[role="radio"]');
    expect(radios).toHaveLength(3);
  });

  it("marks the active option aria-checked + tabindex 0; the rest tabindex -1", () => {
    const w = make("b");
    const radios = w.findAll('[role="radio"]');
    expect(radios[0].attributes("aria-checked")).toBe("false");
    expect(radios[0].attributes("tabindex")).toBe("-1");
    expect(radios[1].attributes("aria-checked")).toBe("true");
    expect(radios[1].attributes("tabindex")).toBe("0");
    expect(radios[2].attributes("tabindex")).toBe("-1");
  });

  it("emits update:modelValue on click", async () => {
    const w = make("a");
    await w.findAll('[role="radio"]')[2].trigger("click");
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["c"]);
  });

  it("ArrowRight moves selection forward and wraps at the end", async () => {
    const w = make("a");
    const radios = w.findAll('[role="radio"]');
    await radios[0].trigger("keydown", { key: "ArrowRight" });
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["b"]);
    await radios[2].trigger("keydown", { key: "ArrowRight" });
    expect(w.emitted("update:modelValue")?.[1]).toEqual(["a"]);
  });

  it("ArrowLeft moves selection back and wraps at the start", async () => {
    const w = make("b");
    const radios = w.findAll('[role="radio"]');
    await radios[1].trigger("keydown", { key: "ArrowLeft" });
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["a"]);
    await radios[0].trigger("keydown", { key: "ArrowLeft" });
    expect(w.emitted("update:modelValue")?.[1]).toEqual(["c"]);
  });

  it("Home / End jump to extremes", async () => {
    const w = make("b");
    const radios = w.findAll('[role="radio"]');
    await radios[1].trigger("keydown", { key: "End" });
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["c"]);
    await radios[1].trigger("keydown", { key: "Home" });
    expect(w.emitted("update:modelValue")?.[1]).toEqual(["a"]);
  });

  it("ignores other keys", async () => {
    const w = make("a");
    await w.findAll('[role="radio"]')[0].trigger("keydown", { key: "Tab" });
    expect(w.emitted("update:modelValue")).toBeUndefined();
  });

  it("renders an aria-label when provided", () => {
    const w = mount(Segmented, {
      props: { modelValue: "a", options: OPTIONS, ariaLabel: "状态过滤" },
    });
    expect(w.attributes("aria-label")).toBe("状态过滤");
  });
});
