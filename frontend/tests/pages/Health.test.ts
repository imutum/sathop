import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { API, type Overview } from "@/api";
import { TooltipProvider } from "@/components/ui/tooltip";
import { K } from "@/queryKeys";
import Health from "@/pages/Health.vue";

const cleanups: Array<() => void> = [];
const emptyOverview: Overview = {
  state_counts: {}, stuck_by_state: {}, stuck_over_hours: 6, last_events: [],
  throughput_per_min: null, eta_realtime: null,
};

function mountHealth(cachedOverview?: Overview) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (cachedOverview) queryClient.setQueryData(K.overview, cachedOverview);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: Health }] });
  const host = defineComponent({ setup: () => () => h(TooltipProvider, null, () => h(Health)) });
  const wrapper = mount(host, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  });
  cleanups.push(() => { wrapper.unmount(); queryClient.clear(); });
  return wrapper;
}

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  vi.restoreAllMocks();
});

describe("health diagnostics", () => {
  it("does not report idle or healthy before requests complete", async () => {
    vi.spyOn(API, "overview").mockReturnValue(new Promise(() => {}));
    vi.spyOn(API, "inFlight").mockReturnValue(new Promise(() => {}));
    const stuck = vi.spyOn(API, "stuck").mockResolvedValue([]);
    const wrapper = mountHealth();
    await flushPromises();
    expect(wrapper.findAll('[role="status"]')).toHaveLength(2);
    expect(wrapper.text()).not.toContain("空闲");
    expect(wrapper.text()).not.toContain("当前未发现");
    expect(wrapper.text()).not.toContain("暂无事件");
    expect(stuck).not.toHaveBeenCalled();
  });

  it("exposes retry after a failure and only shows empty states after recovery", async () => {
    const overview = vi.spyOn(API, "overview").mockRejectedValue(new Error("offline"));
    const inflight = vi.spyOn(API, "inFlight").mockRejectedValue(new Error("offline"));
    vi.spyOn(API, "stuck").mockResolvedValue([]);
    const wrapper = mountHealth();
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.findAll('[role="alert"]')).toHaveLength(2));
    expect(wrapper.text()).not.toContain("空闲");
    expect(wrapper.text()).not.toContain("当前未发现");
    expect(wrapper.text()).not.toContain("暂无事件");

    overview.mockResolvedValue(emptyOverview);
    inflight.mockResolvedValue([]);
    for (const button of wrapper.findAll("button").filter((button) => button.text() === "重试")) {
      await button.trigger("click");
    }
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.findAll('[role="alert"]')).toHaveLength(0));
    expect(wrapper.text()).toContain("空闲");
    expect(wrapper.text()).toContain("当前未发现");
    expect(wrapper.text()).toContain("暂无事件");
  });

  it("reports a failed timeout lookup without hiding the nonzero summary", async () => {
    vi.spyOn(API, "overview").mockResolvedValue({ ...emptyOverview, stuck_by_state: { downloading: 2 } });
    vi.spyOn(API, "inFlight").mockResolvedValue([]);
    const stuck = vi.spyOn(API, "stuck").mockRejectedValue(new Error("unavailable"));
    const wrapper = mountHealth();
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.text()).toContain("超时明细加载失败"));
    expect(stuck).toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("当前未发现");
    expect(wrapper.text()).toContain("0 / 2");
  });

  it("labels retained results when refreshing fails", async () => {
    vi.spyOn(API, "overview").mockRejectedValue(new Error("offline"));
    vi.spyOn(API, "inFlight").mockResolvedValue([]);
    vi.spyOn(API, "stuck").mockResolvedValue([]);
    const wrapper = mountHealth(emptyOverview);
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.text()).toContain("部分信息刷新失败，以下保留上次结果"));
    expect(wrapper.text()).toContain("进度超时");
  });
});
