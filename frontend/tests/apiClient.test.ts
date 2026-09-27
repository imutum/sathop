import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadFile, setToken } from "@/apiClient";
import { API } from "@/api";
import { serviceAPI } from "@/serviceWorkflows";

const fetchMock = vi.fn();
const createObjectURL = vi.fn(() => "blob:delivery-report");
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  });
  fetchMock.mockResolvedValue(new Response("交付文件,SHA-256\r\n"));
  setToken("test-download-token");
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("authenticated file downloads", () => {
  it.each([
    [() => API.downloadDeliveryReport("客户/一"), "/api/batches/%E5%AE%A2%E6%88%B7%2F%E4%B8%80/delivery-report", "客户_一-delivery.csv"],
    [() => serviceAPI.exportDeliveries("q=tile"), "/api/deliveries/export?q=tile", "delivery-ledger.csv"],
  ])("preserves the endpoint, filename and token for %s", async (download, path, filename) => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe(filename);
      expect(this.href).toBe("blob:delivery-report");
      expect(document.body.contains(this)).toBe(true);
    });
    await download();
    expect(fetchMock.mock.calls[0][0]).toBe(path);
    expect(fetchMock.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer test-download-token");
    expect(click).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(document.querySelector("a[download]")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:delivery-report");
  });

  it("shows the API error without creating a download", async () => {
    fetchMock.mockResolvedValue(new Response('{"detail":"导出失败"}', { status: 500 }));
    await expect(downloadFile("/api/deliveries/export", "ledger.csv")).rejects.toThrow("导出失败");
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(document.querySelector("a[download]")).toBeNull();
  });

  it("releases the link and blob even when starting the download throws", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { throw new Error("blocked"); });
    await expect(downloadFile("/api/deliveries/export", "ledger.csv")).rejects.toThrow("blocked");
    expect(document.querySelector("a[download]")).toBeNull();
    vi.advanceTimersByTime(1000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:delivery-report");
  });
});
