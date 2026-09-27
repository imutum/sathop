import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { TooltipProvider } from "@/components/ui/tooltip";
import BundleManifestView from "@/features/bundle/components/BundleManifestView.vue";
import type { BundleDetail } from "@/api";

describe("bundle output defaults", () => {
  const cases: Array<[BundleDetail["manifest"]["outputs"], string, string]> = [
    [undefined, "output", "全部"],
    [{}, "output", "全部"],
    [{ watch_dir: "results", extensions: [".tif"] }, "results", ".tif"],
  ];
  it.each(cases)("renders valid manifests with outputs=%j", (outputs, directory, extensions) => {
    const d: BundleDetail = {
      name: "preview", version: "1.0", sha256: "a".repeat(64), size: 1,
      uploaded_at: "2026-09-27T00:00:00Z", in_use_count: 0, description: null,
      manifest: { name: "preview", version: "1.0", execution: { entrypoint: "main.py" }, outputs },
    };
    const router = createRouter({ history: createMemoryHistory(), routes: [] });
    const wrapper = mount(defineComponent({
      setup: () => () => h(TooltipProvider, null, () => h(BundleManifestView, { d, pending: false, error: null })),
    }), { global: { plugins: [router], stubs: { BundleFileBrowser: true } } });
    const fields = wrapper.findAllComponents({ name: "Field" });
    expect(fields.find((f) => f.props("label") === "输出目录")?.text()).toContain(directory);
    expect(fields.find((f) => f.props("label") === "输出扩展名")?.text()).toContain(extensions);
    wrapper.unmount();
  });
});
