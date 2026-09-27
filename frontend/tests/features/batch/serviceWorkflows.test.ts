import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { deliveryParams, serviceAPI } from "@/serviceWorkflows";
import TaskTemplatePicker from "@/features/batch/components/TaskTemplatePicker.vue";

vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));
vi.mock("@/composables/useConfirm", () => ({ requestConfirm: vi.fn(async () => true) }));
afterEach(() => vi.restoreAllMocks());

describe("operator service workflows", () => {
  it("exports literal search and inclusive local date range without pagination", () => {
    const p = deliveryParams(" file_1% ", "b/1", "2026-09-01", "2026-09-27");
    expect(p.get("q")).toBe("file_1%");
    expect(p.get("batch_id")).toBe("b/1");
    expect(new Date(p.get("since")!).getDate()).toBe(1);
    expect(new Date(p.get("until")!).getDate()).toBe(28);
    expect(p.has("offset")).toBe(false);
  });

  it("does not save environment values unless explicitly included", async () => {
    vi.spyOn(serviceAPI, "templates").mockResolvedValue([]);
    const save = vi.spyOn(serviceAPI, "saveTemplate").mockResolvedValue({ template_id: "t", name: "monthly", bundle_ref: "orch:x@1", target_receiver_id: null, execution_env: {}, created_at: "", updated_at: "" });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const w = mount(TaskTemplatePicker, { props: { bundleRef: "orch:x@1", receiverId: "", envText: '{"TOKEN":"private"}' }, global: { plugins: [[VueQueryPlugin, { queryClient }]] } });
    await flushPromises();
    await w.find('input[aria-label="模板名称"]').setValue("monthly");
    await w.findAll('button').find(b => b.text() === '保存为新模板')!.trigger('click');
    await flushPromises();
    expect(save).toHaveBeenCalledWith({ name: "monthly", bundle_ref: "orch:x@1", target_receiver_id: null, execution_env: {} }, undefined);
    w.unmount(); queryClient.clear();
  });

  it("applying a preset emits its configuration, never starts a task", async () => {
    const preset = { template_id: "t", name: "monthly", bundle_ref: "orch:x@1", target_receiver_id: null, execution_env: { FACTOR: "4" }, created_at: "", updated_at: "" };
    vi.spyOn(serviceAPI, "templates").mockResolvedValue([preset]);
    const save = vi.spyOn(serviceAPI, "saveTemplate");
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const w = mount(TaskTemplatePicker, { props: { bundleRef: "orch:", receiverId: "", envText: "" }, global: { plugins: [[VueQueryPlugin, { queryClient }]] } });
    await flushPromises();
    await w.find('select').setValue('t');
    await w.findAll('button').find(b => b.text() === '套用配置')!.trigger('click');
    expect(w.emitted('apply')?.[0]).toEqual([preset]);
    expect(save).not.toHaveBeenCalled();
    w.unmount(); queryClient.clear();
  });
});
