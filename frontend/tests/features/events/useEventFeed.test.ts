import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { defineComponent, nextTick, ref } from "vue";
import { API, type EventRow } from "@/api";
import { useEventFeed } from "@/features/events/useEventFeed";

const cleanups: Array<() => void> = [];
function events(newest: number, count = 1, source = "worker-a"): EventRow[] {
  return Array.from({ length: count }, (_, i) => ({
    id: newest - i, ts: "2026-09-27T00:00:00Z", level: "info", source,
    batch_id: null, granule_id: null, message: `event ${newest - i}`,
  }));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function mountFeed() {
  const source = ref("worker-a");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let feed!: ReturnType<typeof useEventFeed>;
  const wrapper = mount(defineComponent({
    setup() { feed = useEventFeed(source); return () => null; },
  }), { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } });
  cleanups.push(() => { wrapper.unmount(); client.clear(); });
  return { source, feed };
}
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  vi.restoreAllMocks();
});

describe("event feed", () => {
  it("ignores an old source response after switching away and back", async () => {
    const oldPage = deferred<EventRow[]>();
    const newPage = deferred<EventRow[]>();
    vi.spyOn(API, "events")
      .mockResolvedValueOnce(events(10))
      .mockReturnValueOnce(oldPage.promise)
      .mockResolvedValueOnce(events(20, 1, "worker-b"))
      .mockResolvedValueOnce(events(11))
      .mockReturnValueOnce(newPage.promise);
    const { source, feed } = mountFeed();
    await flushPromises();
    const oldRequest = feed.loadOlder();
    source.value = "worker-b";
    await flushPromises();
    expect(feed.rows.value.map((row) => row.id)).toEqual([20]);
    source.value = "worker-a";
    await flushPromises();
    const newRequest = feed.loadOlder();
    oldPage.resolve(events(9));
    await oldRequest;
    expect(feed.loadingOlder.value).toBe(true);
    expect(feed.rows.value.some((row) => row.id === 9)).toBe(false);
    newPage.resolve(events(8));
    await newRequest;
    expect(feed.loadingOlder.value).toBe(false);
    expect(feed.rows.value.at(-1)?.id).toBe(8);
  });

  it("does not show pagination errors from a previous source", async () => {
    const oldPage = deferred<EventRow[]>();
    vi.spyOn(API, "events")
      .mockResolvedValueOnce(events(10))
      .mockReturnValueOnce(oldPage.promise)
      .mockResolvedValueOnce(events(20, 1, "worker-b"));
    const { source, feed } = mountFeed();
    await flushPromises();
    const request = feed.loadOlder();
    source.value = "worker-b";
    await flushPromises();
    oldPage.reject(new Error("old source failed"));
    await request;
    expect(feed.olderError.value).toBeNull();
    expect(feed.rows.value.map((row) => row.id)).toEqual([20]);
  });

  it("allows retry after pagination failure and prevents concurrent requests", async () => {
    const page = deferred<EventRow[]>();
    const fetch = vi.spyOn(API, "events")
      .mockResolvedValueOnce(events(10))
      .mockReturnValueOnce(page.promise)
      .mockResolvedValueOnce(events(9, 2));
    const { feed } = mountFeed();
    await flushPromises();
    const request = feed.loadOlder();
    await feed.loadOlder();
    expect(fetch).toHaveBeenCalledTimes(2);
    page.reject(new Error("offline"));
    await request;
    expect(feed.olderError.value).toBe("offline");
    expect(feed.rows.value.map((row) => row.id)).toEqual([10]);
    await feed.loadOlder();
    expect(feed.olderError.value).toBeNull();
    expect(feed.rows.value.map((row) => row.id)).toEqual([10, 9, 8]);
    expect(feed.hasMoreOlder.value).toBe(false);
    expect(fetch).toHaveBeenLastCalledWith(0, 200, 10, "worker-a");
    await feed.loadOlder();
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("deduplicates overlapping results and reopens history after trimming", async () => {
    vi.spyOn(API, "events")
      .mockResolvedValueOnce(events(500, 200))
      .mockResolvedValueOnce(events(300, 200))
      .mockResolvedValueOnce(events(100, 100))
      .mockResolvedValueOnce(events(501, 2));
    const { feed } = mountFeed();
    await flushPromises();
    await feed.loadOlder();
    await feed.loadOlder();
    expect(feed.rows.value).toHaveLength(500);
    expect(feed.hasMoreOlder.value).toBe(false);
    await feed.query.refetch();
    await nextTick();
    expect(feed.rows.value).toHaveLength(500);
    expect(feed.rows.value[0].id).toBe(501);
    expect(feed.rows.value.at(-1)?.id).toBe(2);
    expect(new Set(feed.rows.value.map((row) => row.id)).size).toBe(500);
    expect(feed.hasMoreOlder.value).toBe(true);
  });
});
