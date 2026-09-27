import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createMemoryHistory, createRouter } from "vue-router";
import { API, type BundleDetail } from "@/api";
import Bundles from "@/pages/Bundles.vue";

afterEach(() => vi.restoreAllMocks());

it("recovers from a detail failure and returns to the filtered catalog", async () => {
  const bundle: BundleDetail = {
    name: "modis-trio-sinusoidal", version: "1.0", sha256: "a".repeat(64), size: 2000,
    description: null, uploaded_at: "2026-09-27T00:00:00Z", in_use_count: 0,
    manifest: { name: "modis-trio-sinusoidal", version: "1.0", execution: { entrypoint: "main.py" } },
  };
  vi.spyOn(API, "bundles").mockResolvedValue([bundle]);
  const detail = vi.spyOn(API, "bundleDetail").mockRejectedValue(new Error("offline"));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/bundles", component: Bundles }] });
  await router.push("/bundles");
  const wrapper = mount(Bundles, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }], router],
      stubs: { BundleManifestView: { props: ["d"], template: '<h2>{{ d.name }}</h2>' } },
    },
  });
  try {
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find('[aria-label="搜索任务包"]').exists()).toBe(true));
    await wrapper.get("input").setValue("modis");
    await wrapper.get('[aria-pressed="false"]').trigger("click");
    await vi.waitFor(() => expect(wrapper.text()).toContain("任务包加载失败：offline"));
    detail.mockResolvedValue(bundle);
    await wrapper.findAll("button").find(b => b.text() === "重试")!.trigger("click");
    await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(false));
    expect(wrapper.get('[aria-label="任务包详情"]').text()).toContain(bundle.name);
    await wrapper.findAll("button").find(b => b.text().includes("返回任务包目录"))!.trigger("click");
    expect((wrapper.get("input").element as HTMLInputElement).value).toBe("modis");
    expect(wrapper.get('[aria-pressed]').attributes("aria-pressed")).toBe("false");
  } finally {
    wrapper.unmount();
    queryClient.clear();
  }
});
