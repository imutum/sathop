import { expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { BundleSummary } from "@/api";
import BundleCatalog from "@/features/bundle/components/BundleCatalog.vue";

const bundles: BundleSummary[] = ["1.0", "2.0"].map(version => ({
  name: "aerdt-l2-viirs-snpp-land-aod", version, sha256: "a".repeat(64),
  size: 2400, description: null, uploaded_at: "2026-09-27T00:00:00Z", in_use_count: 1,
}));

it("filters names and versions, and lets an empty search result recover", async () => {
  const wrapper = mount(BundleCatalog, { props: { bundles, selected: null } });
  try {
    await wrapper.get("input").setValue("  AERDT  ");
    expect(wrapper.findAll('[aria-pressed]')).toHaveLength(2);
    await wrapper.get("input").setValue("@2.0");
    expect(wrapper.findAll('[aria-pressed]')).toHaveLength(1);
    await wrapper.get("input").setValue("missing");
    expect(wrapper.text()).toContain("没有匹配的任务包");
    await wrapper.get("button").trigger("click");
    expect(wrapper.findAll('[aria-pressed]')).toHaveLength(2);
  } finally { wrapper.unmount(); }
});

it("selects the exact version while exposing the full name and selection state", async () => {
  const wrapper = mount(BundleCatalog, { props: { bundles, selected: bundles[1] } });
  try {
    const choices = wrapper.findAll('[aria-pressed]');
    expect(choices[0].attributes("aria-pressed")).toBe("false");
    expect(choices[1].attributes("aria-pressed")).toBe("true");
    expect(choices[0].attributes("aria-label")).toBe(`${bundles[0].name}@1.0`);
    await choices[0].trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual([bundles[0]]);
  } finally { wrapper.unmount(); }
});
