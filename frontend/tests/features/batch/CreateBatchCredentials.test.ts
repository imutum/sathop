import { afterEach, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import CreateBatchCredentials from "@/features/batch/components/CreateBatchCredentials.vue";

afterEach(() => vi.unstubAllGlobals());

it("disables remembering on HTTP while allowing credentials for the current batch", async () => {
  vi.stubGlobal("crypto", {});
  const wrapper = mount(CreateBatchCredentials, {
    props: {
      names: ["source"],
      drafts: { source: { scheme: "basic", username: "", secret: "" } },
      remember: {},
    },
  });
  try {
    expect(wrapper.get('[role="checkbox"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("本次仍可正常填写和提交");
    await wrapper.get('input[type="password"]').setValue("test-only-value");
    expect(wrapper.emitted("change")?.[0]).toEqual([
      "source", { scheme: "basic", username: "", secret: "test-only-value" },
    ]);
    expect(wrapper.emitted("rememberChange")).toBeUndefined();
  } finally {
    wrapper.unmount();
  }
});
