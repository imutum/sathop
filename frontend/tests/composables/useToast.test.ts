import { describe, it, expect, vi, beforeEach } from "vitest";

const { successSpy, errorSpy, infoSpy } = vi.hoisted(() => ({
  successSpy: vi.fn(),
  errorSpy: vi.fn(),
  infoSpy: vi.fn(),
}));

vi.mock("vue-sonner", () => ({
  toast: { success: successSpy, error: errorSpy, info: infoSpy },
}));

import { useToast } from "@/composables/useToast";

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
