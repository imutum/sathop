import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { defineComponent, h, nextTick, ref, type Ref } from "vue";
import { mount } from "@vue/test-utils";

import {
  useRegistrationWatch,
  type WatchState,
} from "@/features/onboarding/useRegistrationWatch";

type Node = { id: string };
type WatchAPI = { state: Ref<WatchState>; start: () => void };

// useRegistrationWatch registers an onBeforeUnmount hook, so it must run
// inside a component setup. This thin harness exposes the composable's API
// so the test can poke `start()` and mutate the list ref directly.
function harness(idValue: string) {
  const idRef = ref(idValue);
  const listRef = ref<Node[] | undefined>([]);
  let api: WatchAPI | null = null;

  const Host = defineComponent({
    setup() {
      api = useRegistrationWatch(idRef, listRef, (n: Node, id) => n.id === id);
      return () => h("div");
    },
  });

  const wrapper = mount(Host);
  return { wrapper, idRef, listRef, watch: api! };
}

describe("useRegistrationWatch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts in idle until start() is called", () => {
    const { watch } = harness("w1");
    expect(watch.state.value).toBe("idle");
  });

  it("transitions waiting → registered when the list grows to include the id", async () => {
    const { listRef, watch } = harness("w1");
    watch.start();
    expect(watch.state.value).toBe("waiting");

    listRef.value = [{ id: "other" }];
    await nextTick();
    expect(watch.state.value).toBe("waiting");

    listRef.value = [{ id: "other" }, { id: "w1" }];
    await nextTick();
    expect(watch.state.value).toBe("registered");
  });

  it("transitions waiting → timeout after 60s without a match", async () => {
    const { watch } = harness("w1");
    watch.start();
    vi.advanceTimersByTime(59_000);
    expect(watch.state.value).toBe("waiting");
    vi.advanceTimersByTime(1_001);
    expect(watch.state.value).toBe("timeout");
  });

  it("registration after timeout still flips state — late join is honoured", async () => {
    // Operator might step away from the screen; we don't want the panel to
    // stay stuck on "timeout" once the node finally lands.
    const { listRef, watch } = harness("w1");
    watch.start();
    vi.advanceTimersByTime(61_000);
    expect(watch.state.value).toBe("timeout");

    listRef.value = [{ id: "w1" }];
    await nextTick();
    expect(watch.state.value).toBe("registered");
  });

  it("re-calling start() resets the timer", () => {
    const { watch } = harness("w1");
    watch.start();
    vi.advanceTimersByTime(50_000);
    watch.start(); // restart
    vi.advanceTimersByTime(50_000);
    expect(watch.state.value).toBe("waiting"); // would have been timeout without restart
    vi.advanceTimersByTime(11_000);
    expect(watch.state.value).toBe("timeout");
  });

  it("passive list match while idle does not flip to registered", async () => {
    // start() must be called first — passively having the ID in the cache
    // does not count as 'just registered'. Without this guard, every reopen
    // of the modal would immediately show 'registered' for any pre-existing
    // node, defeating the purpose of the post-copy feedback.
    const { listRef, watch } = harness("w1");
    listRef.value = [{ id: "w1" }];
    await nextTick();
    expect(watch.state.value).toBe("idle");
  });
});
