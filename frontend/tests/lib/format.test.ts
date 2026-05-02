import { describe, it, expect, beforeEach } from "vitest";
import { fmtBytes, fmtGB, fmtRate, nodeStatusBadge } from "@/lib/format";
import { useNow } from "@/i18n";

describe("lib/format/fmtBytes", () => {
  it("renders < 1 KiB as integer bytes", () => {
    expect(fmtBytes(0)).toBe("0 B");
    expect(fmtBytes(1023)).toBe("1023 B");
  });
  it("renders KB / MB / GB at the right thresholds", () => {
    expect(fmtBytes(1024)).toBe("1.0 KB");
    expect(fmtBytes(1024 * 1024)).toBe("1.00 MB");
    expect(fmtBytes(1024 * 1024 * 1024)).toBe("1.00 GB");
  });
  it("uses 2 decimals for MB / GB and 1 for KB", () => {
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtBytes(1.5 * 1024 * 1024)).toBe("1.50 MB");
  });
});

describe("lib/format/fmtGB", () => {
  it("formats GB with one decimal under 1 TB", () => {
    expect(fmtGB(0)).toBe("0.0 GB");
    expect(fmtGB(512.4)).toBe("512.4 GB");
  });
  it("crosses to TB at 1024 GB", () => {
    expect(fmtGB(1024)).toBe("1.0 TB");
    expect(fmtGB(2048)).toBe("2.0 TB");
  });
});

describe("lib/format/fmtRate", () => {
  it("renders an em-dash for non-positive bps", () => {
    expect(fmtRate(0)).toBe("—");
    expect(fmtRate(-1)).toBe("—");
  });
  it("uses B/s, KB/s, MB/s, GB/s by magnitude", () => {
    expect(fmtRate(500)).toBe("500 B/s");
    expect(fmtRate(2048)).toBe("2.0 KB/s");
    expect(fmtRate(2 * 1024 * 1024)).toBe("2.00 MB/s");
    expect(fmtRate(2 * 1024 * 1024 * 1024)).toBe("2.00 GB/s");
  });
});

describe("lib/format/nodeStatusBadge", () => {
  beforeEach(() => {
    // Pin the reactive clock so the freshness windows are deterministic.
    useNow().value = new Date("2026-05-02T12:00:00Z").getTime();
  });

  it("returns 已禁用 when not enabled, regardless of last_seen", () => {
    expect(nodeStatusBadge(false, "2026-05-02T12:00:00Z")).toEqual({
      tone: "error",
      label: "已禁用",
    });
  });
  it("returns 在线 within 60 s of last_seen", () => {
    expect(nodeStatusBadge(true, "2026-05-02T11:59:30Z")).toEqual({
      tone: "acked",
      label: "在线",
    });
  });
  it("returns 待机 between 60 s and 5 min", () => {
    expect(nodeStatusBadge(true, "2026-05-02T11:58:00Z")).toEqual({
      tone: "warn",
      label: "待机",
    });
  });
  it("returns 离线 beyond 5 min", () => {
    expect(nodeStatusBadge(true, "2026-05-02T11:50:00Z")).toEqual({
      tone: "error",
      label: "离线",
    });
  });
});
