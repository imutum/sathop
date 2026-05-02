import { describe, it, expect, vi, beforeEach } from "vitest";

const { successSpy, errorSpy, infoSpy } = vi.hoisted(() => ({
  successSpy: vi.fn(),
  errorSpy: vi.fn(),
  infoSpy: vi.fn(),
}));

vi.mock("vue-sonner", () => ({
  toast: { success: successSpy, error: errorSpy, info: infoSpy },
}));

import { useToast, useMutationToast } from "@/composables/useToast";

beforeEach(() => {
  successSpy.mockReset();
  errorSpy.mockReset();
  infoSpy.mockReset();
});

describe("composables/useToast", () => {
  it("forwards success / info to vue-sonner without options", () => {
    const t = useToast();
    t.success("hi");
    t.info("note");
    expect(successSpy).toHaveBeenCalledWith("hi");
    expect(infoSpy).toHaveBeenCalledWith("note");
  });

  it("pins error toasts with duration: Infinity (sticky-on-error contract)", () => {
    useToast().error("boom");
    expect(errorSpy).toHaveBeenCalledWith("boom", { duration: Infinity });
  });
});

describe("composables/useMutationToast", () => {
  it("onSuccess returns a curried handler that fires success(msg)", () => {
    const m = useMutationToast();
    const handler = m.onSuccess("已保存");
    handler();
    expect(successSpy).toHaveBeenCalledWith("已保存");
  });

  it("onError formats Error.message with optional prefix", () => {
    const m = useMutationToast();
    m.onError("保存失败")(new Error("network down"));
    expect(errorSpy).toHaveBeenCalledWith("保存失败：network down", { duration: Infinity });
  });

  it("onError without prefix shows the error message verbatim", () => {
    useMutationToast().onError()(new Error("oops"));
    expect(errorSpy).toHaveBeenCalledWith("oops", { duration: Infinity });
  });

  it("onError stringifies non-Error values", () => {
    useMutationToast().onError("err")("plain string");
    expect(errorSpy).toHaveBeenCalledWith("err：plain string", { duration: Infinity });
  });
});
