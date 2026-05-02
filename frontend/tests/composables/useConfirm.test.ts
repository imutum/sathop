import { describe, it, expect, beforeEach } from "vitest";
import {
  confirmInput,
  confirmRequest,
  requestConfirm,
  resolveConfirm,
} from "@/composables/useConfirm";

describe("composables/useConfirm", () => {
  beforeEach(() => {
    // Reset the singleton between tests.
    confirmRequest.value = null;
    confirmInput.value = "";
  });

  it("resolves true when the user confirms", async () => {
    const p = requestConfirm({ title: "Delete?" });
    expect(confirmRequest.value?.title).toBe("Delete?");
    resolveConfirm(true);
    await expect(p).resolves.toBe(true);
    expect(confirmRequest.value).toBeNull();
  });

  it("resolves false when the user cancels", async () => {
    const p = requestConfirm({ title: "Cancel?" });
    resolveConfirm(false);
    await expect(p).resolves.toBe(false);
  });

  it("fills sensible defaults for confirmText / cancelText / tone", () => {
    void requestConfirm({ title: "T" });
    expect(confirmRequest.value).toMatchObject({
      title: "T",
      confirmText: "确认",
      cancelText: "取消",
      tone: "default",
    });
  });

  it("clears confirmInput when a new request opens", () => {
    confirmInput.value = "stale text";
    void requestConfirm({ title: "T" });
    expect(confirmInput.value).toBe("");
  });

  it("rejects nested calls — second requestConfirm resolves false immediately", async () => {
    void requestConfirm({ title: "first" });
    const second = requestConfirm({ title: "second" });
    await expect(second).resolves.toBe(false);
    // First request still owns the singleton.
    expect(confirmRequest.value?.title).toBe("first");
  });

  it("resolveConfirm is a no-op when no request is open", () => {
    expect(() => resolveConfirm(true)).not.toThrow();
    expect(confirmRequest.value).toBeNull();
  });

  it("preserves the optional requireText / inputLabel through the request", () => {
    void requestConfirm({
      title: "Type the name",
      requireText: "batch-x",
      inputLabel: "请输入",
    });
    expect(confirmRequest.value).toMatchObject({
      requireText: "batch-x",
      inputLabel: "请输入",
    });
  });
});
