import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, type EffectScope } from "vue";
import { useLiveStream } from "@/composables/useLiveStream";

const { invalidateQueries } = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));
vi.mock("@tanstack/vue-query", () => ({ useQueryClient: () => ({ invalidateQueries }) }));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();
  constructor(public url: string) { FakeEventSource.instances.push(this); }
  send(scope: string) { this.onmessage?.({ data: JSON.stringify({ scope }) }); }
}

let scope: EffectScope;
const latest = () => FakeEventSource.instances.at(-1)!;
function start() {
  scope = effectScope();
  return scope.run(() => useLiveStream())!;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-27T00:00:00Z"));
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: "1", web_sha: null }) }));
  FakeEventSource.instances = [];
  invalidateQueries.mockClear();
});
afterEach(() => {
  scope?.stop();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("real-time recovery", () => {
  it("coalesces bursts and shared keys without cancelling a slow refetch", async () => {
    start();
    latest().send("batches");
    latest().send("workers");
    latest().send("batches");
    await vi.advanceTimersByTimeAsync(1);
    expect(invalidateQueries.mock.calls.filter(([filter]) => filter.queryKey[0] === "overview")).toHaveLength(1);
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["batches"] }, { cancelRefetch: false });
    invalidateQueries.mockClear();
    latest().send("batches");
    await vi.advanceTimersByTimeAsync(1998);
    expect(invalidateQueries).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(invalidateQueries).toHaveBeenCalled();
  });

  it("refreshes changes missed while disconnected, even without a new event", async () => {
    const live = start();
    latest().onopen?.();
    expect(live.connected.value).toBe(true);
    latest().onerror?.();
    expect(live.connected.value).toBe(false);
    await vi.advanceTimersByTimeAsync(3000);
    latest().onopen?.();
    expect(live.connected.value).toBe(true);
    expect(invalidateQueries).toHaveBeenCalledWith();
  });

  it("resyncs after the first connection failed too", async () => {
    start();
    latest().onerror?.();
    await vi.advanceTimersByTimeAsync(3000);
    latest().onopen?.();
    expect(invalidateQueries).toHaveBeenCalledWith();
  });

  it("backs off repeated failures and resets after recovery", async () => {
    start();
    for (const delay of [3000, 6000, 12000, 24000, 30000, 30000]) {
      const before = FakeEventSource.instances.length;
      latest().onerror?.();
      latest().onerror?.(); // duplicate error must not schedule another retry
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(FakeEventSource.instances).toHaveLength(before);
      await vi.advanceTimersByTimeAsync(1);
      expect(FakeEventSource.instances).toHaveLength(before + 1);
    }
    latest().onopen?.();
    latest().onerror?.();
    const before = FakeEventSource.instances.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(FakeEventSource.instances).toHaveLength(before + 1);
  });

  it("ignores malformed events and inherited property names", async () => {
    start();
    latest().onmessage?.({ data: "broken" });
    latest().send("toString");
    latest().send("unknown");
    latest().send("batches");
    await vi.advanceTimersByTimeAsync(1);
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["batches"] }, { cancelRefetch: false });
  });

  it("cleans up the stream, timers and late callbacks on disposal", async () => {
    const live = start();
    const es = latest();
    es.send("batches");
    es.onerror?.();
    scope.stop();
    es.onopen?.();
    es.send("workers");
    await vi.advanceTimersByTimeAsync(60_000);
    await nextTick();
    expect(es.close).toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(invalidateQueries).not.toHaveBeenCalled();
    expect(live.connected.value).toBe(false);
  });
});
