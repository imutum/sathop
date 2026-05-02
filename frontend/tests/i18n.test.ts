import { describe, it, expect, beforeEach } from "vitest";
import {
  fmtAge,
  fmtDuration,
  fmtMs,
  fmtPerMinute,
  fmtProgressStep,
  levelLabel,
  stateLabel,
  useNow,
} from "@/i18n";

describe("i18n/fmtAge", () => {
  beforeEach(() => {
    useNow().value = new Date("2026-05-02T12:00:00Z").getTime();
  });

  it("renders seconds when fresh", () => {
    expect(fmtAge("2026-05-02T11:59:55Z")).toBe("5 秒前");
    expect(fmtAge("2026-05-02T11:59:01Z")).toBe("59 秒前");
  });
  it("renders minutes between 1 min and 1 hour", () => {
    expect(fmtAge("2026-05-02T11:55:00Z")).toBe("5 分钟前");
    expect(fmtAge("2026-05-02T11:01:00Z")).toBe("59 分钟前");
  });
  it("renders fractional hours between 1 h and 1 day", () => {
    expect(fmtAge("2026-05-02T09:00:00Z")).toBe("3.0 小时前");
    expect(fmtAge("2026-05-02T10:30:00Z")).toBe("1.5 小时前");
  });
  it("renders fractional days beyond 1 day", () => {
    expect(fmtAge("2026-04-30T12:00:00Z")).toBe("2.0 天前");
  });
  it("clamps negative ages (clock skew) to 0 秒前", () => {
    expect(fmtAge("2026-05-02T12:00:30Z")).toBe("0 秒前");
  });
});

describe("i18n/fmtMs", () => {
  it("renders 0 when zero or falsy", () => {
    expect(fmtMs(0)).toBe("0");
  });
  it("renders ms under 1 s", () => {
    expect(fmtMs(750)).toBe("750ms");
  });
  it("renders s under 1 min, with 1 dp under 10 s", () => {
    expect(fmtMs(2_500)).toBe("2.5s");
    expect(fmtMs(45_000)).toBe("45s");
  });
  it("renders mm:ss-style for >= 1 min", () => {
    expect(fmtMs(125_000)).toBe("2m05s");
    expect(fmtMs(60_000)).toBe("1m00s");
  });
});

describe("i18n/fmtDuration", () => {
  it("delegates to fmtMs under 1 hour", () => {
    expect(fmtDuration(45_000)).toBe("45s");
    expect(fmtDuration(125_000)).toBe("2m05s");
  });
  it("renders h+m beyond 1 hour", () => {
    expect(fmtDuration(3_600_000)).toBe("1h00m");
    expect(fmtDuration(2 * 3_600_000 + 30 * 60_000)).toBe("2h30m");
  });
});

describe("i18n/fmtPerMinute", () => {
  it("returns em-dash on non-positive count or ms", () => {
    expect(fmtPerMinute(0, 1000)).toBe("—");
    expect(fmtPerMinute(5, 0)).toBe("—");
    expect(fmtPerMinute(-1, 1000)).toBe("—");
  });
  it("uses 1 dp under 10/min, integer above", () => {
    // 3 events in 60s = 3.0/min
    expect(fmtPerMinute(3, 60_000)).toBe("3.0/min");
    // 30 events in 60s = 30/min
    expect(fmtPerMinute(30, 60_000)).toBe("30/min");
  });
});

describe("i18n/fmtProgressStep", () => {
  it("expands the download:<filename> prefix", () => {
    expect(fmtProgressStep("download:foo.tif")).toBe("下载 foo.tif");
  });
  it("passes other steps through verbatim", () => {
    expect(fmtProgressStep("upload")).toBe("upload");
    expect(fmtProgressStep("custom-step")).toBe("custom-step");
  });
});

describe("i18n/stateLabel + levelLabel", () => {
  it("translates known states + falls back to the raw value for unknown", () => {
    expect(stateLabel("pending")).toBe("待处理");
    expect(stateLabel("failed")).toBe("失败");
    // @ts-expect-error — exercising the fallback path
    expect(stateLabel("unknown")).toBe("unknown");
  });
  it("translates known event levels + falls back to the raw value", () => {
    expect(levelLabel("warn")).toBe("警告");
    expect(levelLabel("error")).toBe("错误");
    expect(levelLabel("debug")).toBe("debug");
  });
});
