import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { deliveryParams, serviceAPI } from "@/serviceWorkflows";
import TaskTemplatePicker from "@/features/batch/components/TaskTemplatePicker.vue";
import { requestConfirm } from "@/composables/useConfirm";

vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));
vi.mock("@/composables/useConfirm", () => ({ requestConfirm: vi.fn(async () => true) }));
const preset = {
  template_id: "t", name: "monthly", bundle_ref: "orch:x@1", target_receiver_id: null,
  execution_env: { FACTOR: "4" }, created_at: "", updated_at: "",
};
const cleanups: Array<() => void> = [];

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  vi.restoreAllMocks();
});

async function mountPicker(envText = "") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = mount(TaskTemplatePicker, {
    props: { bundleRef: "orch:x@1", receiverId: "", envText },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  });
  cleanups.push(() => { wrapper.unmount(); queryClient.clear(); });
  await flushPromises();
  return wrapper;
}

function button(wrapper: VueWrapper, label: string) {
  return wrapper.findAll("button").find((button) => button.text() === label)!;
}

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
    const save = vi.spyOn(serviceAPI, "saveTemplate").mockResolvedValue(preset);
    const w = await mountPicker('{"TOKEN":"private"}');
    await w.find('input[aria-label="模板名称"]').setValue("monthly");
    await button(w, "保存为新模板").trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith({ name: "monthly", bundle_ref: "orch:x@1", target_receiver_id: null, execution_env: {} }, undefined);
  });

  it("applying a preset emits its configuration, never starts a task", async () => {
    vi.spyOn(serviceAPI, "templates").mockResolvedValue([preset]);
    const save = vi.spyOn(serviceAPI, "saveTemplate");
    const w = await mountPicker();
    await w.setProps({ bundleRef: "orch:" });
    await w.find('select').setValue('t');
    await button(w, "套用配置").trigger("click");
    expect(w.emitted('apply')?.[0]).toEqual([preset]);
    expect(save).not.toHaveBeenCalled();
  });

  it("rejects an invalid included environment and allows a corrected retry", async () => {
    vi.spyOn(serviceAPI, "templates").mockResolvedValue([]);
    const save = vi.spyOn(serviceAPI, "saveTemplate").mockResolvedValue(preset);
    const w = await mountPicker("[]");
    await w.find('input[aria-label="模板名称"]').setValue("monthly");
    await w.find('input[type="checkbox"]').setValue(true);
    await button(w, "保存为新模板").trigger("click");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toBe("环境变量必须是 JSON 对象");
    expect(save).not.toHaveBeenCalled();
    expect(button(w, "保存为新模板").attributes("disabled")).toBeUndefined();

    await w.setProps({ envText: '{"FACTOR":4}' });
    await button(w, "保存为新模板").trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ execution_env: { FACTOR: "4" } }), undefined);
    expect(w.find('[role="alert"]').exists()).toBe(false);
  });

  it("keeps the selection after a failed delete and clears it after a successful retry", async () => {
    const templates = vi.spyOn(serviceAPI, "templates").mockResolvedValue([preset]);
    const remove = vi.spyOn(serviceAPI, "deleteTemplate").mockRejectedValueOnce(new Error("服务暂时不可用"));
    const w = await mountPicker();
    await w.find("select").setValue("t");
    await button(w, "删除模板").trigger("click");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toBe("服务暂时不可用");
    expect(w.get("select").element.value).toBe("t");
    expect(button(w, "删除模板").attributes("disabled")).toBeUndefined();

    remove.mockResolvedValueOnce({ ok: true });
    templates.mockResolvedValue([]);
    await button(w, "删除模板").trigger("click");
    await flushPromises();
    expect(remove).toHaveBeenLastCalledWith("t");
    expect(w.get("select").element.value).toBe("");
    expect(w.get<HTMLInputElement>('input[aria-label="模板名称"]').element.value).toBe("");
    expect(w.find('[role="alert"]').exists()).toBe(false);
  });

  it("does not mutate a template when confirmation is cancelled", async () => {
    vi.spyOn(serviceAPI, "templates").mockResolvedValue([preset]);
    const save = vi.spyOn(serviceAPI, "saveTemplate");
    const remove = vi.spyOn(serviceAPI, "deleteTemplate");
    vi.mocked(requestConfirm).mockResolvedValue(false);
    const w = await mountPicker();
    await w.find("select").setValue("t");
    await button(w, "更新所选模板").trigger("click");
    await button(w, "删除模板").trigger("click");
    await flushPromises();
    expect(save).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
});
