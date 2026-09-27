import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { defineComponent, ref } from "vue";
import { API } from "@/api";
import { useVersionCheck } from "@/composables/useVersionCheck";

const cleanups: Array<() => void> = [];
const release = { tag: "v1.0.22", html_url: "https://example.com/release", current: "1.0.22" };

function mountCheck() {
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0, refetchInterval: 50 } } });
  const current = ref("1.0.22");
  let check!: ReturnType<typeof useVersionCheck>;
  const wrapper = mount(defineComponent({
    setup() { check = useVersionCheck(current); return () => null; },
  }), { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } });
  cleanups.push(() => { wrapper.unmount(); client.clear(); });
  return { check, current };
}

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("version checks", () => {
  it("compares fresh releases reactively and does not inherit background polling", async () => {
    vi.useFakeTimers();
    const fetch = vi.spyOn(API, "latestVersion").mockResolvedValue(release);
    const { check, current } = mountCheck();
    await flushPromises();
    expect(check.status.value).toBe("current");
    current.value = "1.0.21";
    expect(check.status.value).toBe("outdated");
    expect(check.statusLabel.value).toContain("v1.0.22");
    await vi.advanceTimersByTimeAsync(500);
    expect(fetch).toHaveBeenCalledTimes(1);
    check.refresh();
    await flushPromises();
    expect(fetch).toHaveBeenLastCalledWith(true);
    await check.latest.refetch();
    expect(fetch).toHaveBeenLastCalledWith(false);
  });

  it.each([
    { stale: true },
    { error: "GitHub unavailable" },
  ])("labels a last-known release without claiming it is current: %j", async (fallback) => {
    vi.spyOn(API, "latestVersion").mockResolvedValue({ ...release, ...fallback });
    const { check } = mountCheck();
    await flushPromises();
    expect(check.status.value).toBe("stale");
    expect(check.statusLabel.value).toBe("更新检查未完成，上次记录为 v1.0.22");
    expect(check.dotClass.value).toBe("bg-warning");
  });

  it("preserves the last release but marks it stale after a failed refresh", async () => {
    const fetch = vi.spyOn(API, "latestVersion").mockResolvedValue(release);
    const { check } = mountCheck();
    await flushPromises();
    expect(check.status.value).toBe("current");
    fetch.mockRejectedValue(new Error("offline"));
    await check.latest.refetch();
    expect(check.status.value).toBe("stale");
    expect(check.latestTag.value).toBe("v1.0.22");
  });

  it("does not claim a version is current when no release can be read", async () => {
    vi.spyOn(API, "latestVersion").mockResolvedValue({ ...release, tag: "", error: "unavailable" });
    const { check } = mountCheck();
    await vi.waitFor(() => expect(check.status.value).toBe("unknown"));
    expect(check.statusLabel.value).toBe("暂时无法检查更新");
  });
});
