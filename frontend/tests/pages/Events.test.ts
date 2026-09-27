import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createMemoryHistory, createRouter } from "vue-router";
import { API, type EventRow } from "@/api";
import { K } from "@/queryKeys";
import Events from "@/pages/Events.vue";

const cleanups: Array<() => void> = [];
function events(newest: number, count = 1): EventRow[] {
  return Array.from({ length: count }, (_, i) => ({
    id: newest - i, ts: "2026-09-27T00:00:00Z", level: "warn", source: "worker-a",
    batch_id: null, granule_id: null, message: `event ${newest - i}`,
  }));
}
async function mountEvents(path = "/events", live = false) {
  localStorage.clear();
  if (live) localStorage.setItem("sathop.events.live", "1");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/events", component: Events }] });
  await router.push(path);
  const wrapper = mount(Events, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], router] } });
  cleanups.push(() => { wrapper.unmount(); client.clear(); });
  await flushPromises();
  return { wrapper, client };
}
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("event browser", () => {
  it("opens at the newest event when restoring live mode", async () => {
    let resolve!: (rows: EventRow[]) => void;
    vi.spyOn(API, "events").mockReturnValue(new Promise((done) => { resolve = done; }));
    const { wrapper } = await mountEvents("/events", true);
    const scroller = wrapper.find(".overflow-auto").element;
    Object.defineProperty(scroller, "scrollHeight", { value: 10_000, configurable: true });
    resolve(events(200, 200));
    await flushPromises();
    expect(scroller.scrollTop).toBe(10_000);
    expect(wrapper.text()).not.toContain("条新事件");
  });

  it("counts matching new events when the recent window is already full", async () => {
    vi.spyOn(API, "events")
      .mockResolvedValueOnce(events(500, 200))
      .mockResolvedValueOnce(events(300, 200))
      .mockResolvedValueOnce(events(100, 100))
      .mockResolvedValueOnce([{ ...events(502)[0], level: "info" }, ...events(501)]);
    const { wrapper, client } = await mountEvents("/events?level=warn");
    for (let page = 0; page < 2; page++) {
      await wrapper.findAll("button").find((button) => button.text() === "加载更早事件")!.trigger("click");
      await flushPromises();
    }
    expect(wrapper.findAll("li")).toHaveLength(500);
    await wrapper.findAll("button").find((button) => button.text() === "实时")!.trigger("click");
    const scroller = wrapper.find(".overflow-auto").element;
    Object.defineProperties(scroller, {
      scrollHeight: { value: 10_000, configurable: true },
      clientHeight: { value: 500, configurable: true },
    });
    scroller.scrollTop = 0;
    await client.invalidateQueries({ queryKey: K.events });
    await flushPromises();
    expect(wrapper.text()).toContain("1 条新事件");
    expect(wrapper.findAll("li")).toHaveLength(499);
    await wrapper.findAll("button").find((button) => button.text().includes("1 条新事件"))!.trigger("click");
    expect(wrapper.text()).not.toContain("条新事件");
    expect(scroller.scrollTop).toBe(10_000);
  });

  it("keeps loaded events visible after a refresh failure", async () => {
    const fetch = vi.spyOn(API, "events").mockResolvedValue(events(10));
    const { wrapper, client } = await mountEvents();
    fetch.mockRejectedValue(new Error("offline"));
    await client.invalidateQueries({ queryKey: K.events });
    await flushPromises();
    expect(wrapper.text()).toContain("事件刷新失败，当前显示上次读取的记录");
    expect(wrapper.text()).toContain("event 10");
  });

  it("ignores repeated query parameters and explains the search scope", async () => {
    const fetch = vi.spyOn(API, "events").mockResolvedValue(events(10));
    const { wrapper } = await mountEvents("/events?q=a&q=b&source=a&source=b&level=invalid");
    expect(fetch).toHaveBeenCalledWith(0, 200, undefined, undefined);
    expect(wrapper.text()).toContain("event 10");
    expect(wrapper.text()).toContain("筛选仅作用于已加载记录");
    await wrapper.find('input[aria-label="搜索事件"]').setValue("absent");
    expect(wrapper.text()).toContain("已加载记录中没有匹配事件");
  });
});
