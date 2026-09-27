import { afterEach, describe, expect, it } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import Modal from "@/ui/Modal.vue";
import ConfirmDialog from "@/ui/ConfirmDialog.vue";
import { DialogContent } from "@/components/ui/dialog";
import { confirmRequest, resolveConfirm } from "@/composables/useConfirm";

let host: VueWrapper;

async function open(dirty = true, zIndex = 50) {
  host = mount(defineComponent({
    setup: () => () => [
      h(Modal, { title: "编辑任务", description: "保存当前修改", dirty, zIndex }, {
        default: ({ close }: { close: () => void }) => h("button", { id: "cancel-form", onClick: close }, "取消"),
      }),
      h(ConfirmDialog),
    ],
  }), { attachTo: document.body });
  await flushPromises();
  return host.findComponent(Modal);
}

function button(text: string) {
  const el = [...document.querySelectorAll("button")].find((el) => el.textContent?.trim() === text);
  if (!el) throw new Error(`Missing button: ${text}`);
  return el;
}

afterEach(async () => {
  resolveConfirm(false);
  await flushPromises();
  host?.unmount();
  document.body.innerHTML = "";
});

describe("Modal dismissal", () => {
  it("gives the dialog an accessible title and description", async () => {
    await open(false);
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(document.getElementById(dialog.getAttribute("aria-labelledby")!)?.textContent).toBe("编辑任务");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe("保存当前修改");
  });

  it("closes a clean form directly from the close button", async () => {
    const modal = await open(false);
    button("关闭弹窗").click();
    await flushPromises();
    expect(modal.emitted("close")).toHaveLength(1);
    expect(confirmRequest.value).toBeNull();
  });

  it("keeps dirty input open when close is cancelled, then permits discard", async () => {
    const modal = await open();
    button("关闭弹窗").click();
    await flushPromises();
    expect(modal.emitted("close")).toBeUndefined();
    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
    const cancel = document.querySelector('[role="alertdialog"] button') as HTMLButtonElement;
    cancel.click();
    await flushPromises();
    expect(modal.emitted("close")).toBeUndefined();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    button("关闭弹窗").click();
    await flushPromises();
    button("放弃修改").click();
    await flushPromises();
    expect(modal.emitted("close")).toHaveLength(1);
  });

  it("guards the form cancel action and ignores repeated requests", async () => {
    const modal = await open();
    button("取消").click();
    await flushPromises();
    const request = confirmRequest.value;
    button("关闭弹窗").click();
    await flushPromises();
    expect(confirmRequest.value).toBe(request);
    expect(modal.emitted("close")).toBeUndefined();
    resolveConfirm(true);
    await flushPromises();
    expect(modal.emitted("close")).toHaveLength(1);
  });

  it("cancels Escape synchronously while waiting for confirmation", async () => {
    const modal = await open();
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    document.activeElement!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await flushPromises();
    expect(confirmRequest.value?.title).toBe("放弃未保存修改？");
    expect(modal.emitted("close")).toBeUndefined();
  });

  it("cancels outside dismissal and renders confirmation above nested dialogs", async () => {
    const modal = await open(true, 60);
    const event = new CustomEvent("interactOutside", { cancelable: true });
    modal.findComponent(DialogContent).vm.$emit("interactOutside", event);
    expect(event.defaultPrevented).toBe(true);
    await flushPromises();
    expect(modal.emitted("close")).toBeUndefined();
    expect((document.querySelector('[role="dialog"]') as HTMLElement).style.zIndex).toBe("60");
    expect(document.querySelector('[role="alertdialog"]')?.classList.contains("z-[100]")).toBe(true);
  });
});
