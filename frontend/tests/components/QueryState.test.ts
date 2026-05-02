import { describe, it, expect } from "vitest";
import { defineComponent, h, ref } from "vue";
import { mount } from "@vue/test-utils";
import QueryState from "@/components/QueryState.vue";

// Minimal stand-in for the parts of UseQueryReturnType that QueryState
// reads — just refs that mirror the live Query result shape.
type StubQuery<T> = {
  data: ReturnType<typeof ref<T | undefined>>;
  isPending: ReturnType<typeof ref<boolean>>;
  error: ReturnType<typeof ref<Error | null>>;
  refetch: () => Promise<unknown>;
};

function stubQuery<T>(init: {
  data?: T;
  isPending?: boolean;
  error?: Error | null;
}): StubQuery<T> {
  return {
    data: ref(init.data) as StubQuery<T>["data"],
    isPending: ref(init.isPending ?? false),
    error: ref(init.error ?? null) as StubQuery<T>["error"],
    refetch: async () => undefined,
  };
}

const Harness = defineComponent({
  props: ["query", "isEmpty"],
  setup(props) {
    return () =>
      h(
        QueryState,
        // biome-ignore lint/suspicious/noExplicitAny: stub harness
        { query: props.query as any, isEmpty: props.isEmpty as any },
        {
          loading: () => h("div", { class: "L" }, "loading"),
          error: ({ error }: { error: Error }) =>
            h("div", { class: "E" }, `err:${error.message}`),
          empty: () => h("div", { class: "X" }, "empty"),
          default: ({ data }: { data: unknown }) =>
            h("div", { class: "D" }, JSON.stringify(data)),
        },
      );
  },
});

describe("components/QueryState", () => {
  it("renders the loading slot while isPending and data is undefined", () => {
    const w = mount(Harness, {
      props: { query: stubQuery<number[]>({ isPending: true }) },
    });
    expect(w.find(".L").exists()).toBe(true);
    expect(w.find(".D").exists()).toBe(false);
  });

  it("renders the error slot with the error message", () => {
    const w = mount(Harness, {
      props: { query: stubQuery<number[]>({ error: new Error("boom") }) },
    });
    expect(w.find(".E").text()).toBe("err:boom");
  });

  it("renders the empty slot for an empty array (default isEmpty)", () => {
    const w = mount(Harness, {
      props: { query: stubQuery<number[]>({ data: [] }) },
    });
    expect(w.find(".X").exists()).toBe(true);
  });

  it("renders the default slot with the data when populated", () => {
    const w = mount(Harness, {
      props: { query: stubQuery<number[]>({ data: [1, 2, 3] }) },
    });
    expect(w.find(".D").text()).toBe("[1,2,3]");
  });

  it("uses a custom isEmpty predicate when provided", () => {
    const w = mount(Harness, {
      props: {
        query: stubQuery<{ items: number[] }>({ data: { items: [] } }),
        isEmpty: (v: { items: number[] }) => v.items.length === 0,
      },
    });
    expect(w.find(".X").exists()).toBe(true);
  });

  it("keeps showing data while a refetch is in-flight (no flicker)", () => {
    // background refetch with stale data still in cache — pages should
    // not flash the skeleton in that case.
    const q = stubQuery<number[]>({ data: [9], isPending: false });
    const w = mount(Harness, { props: { query: q } });
    expect(w.find(".D").text()).toBe("[9]");
  });
});
