import { describe, it, expect } from "vitest";
import {
  pipelineGroups,
  pipelineSegments,
  pipelineTotals,
} from "@/features/batch/pipelineSummary";

// The user's own snapshot — the canonical fixture for the shared 口径.
const counts = {
  pending: 11648, // 待分配
  queued: 38, // 待下载
  downloading: 100, // 下载中
  processing: 143, // 处理中
  uploaded: 71, // 待分发
  acked: 398, // 待清理
  deleted: 358735, // 已完成
} as const;

describe("pipelineTotals", () => {
  it("partitions into the four buckets; grand total excludes 异常", () => {
    const t = pipelineTotals(counts);
    expect(t.pending).toBe(11648);
    expect(t.active).toBe(38 + 100 + 143 + 71); // 352
    expect(t.done).toBe(398 + 358735); // 359133
    expect(t.failed).toBe(0);
    expect(t.total).toBe(11648 + 352 + 359133); // 异常 not summed in
  });
});

describe("pipelineSegments", () => {
  it("keeps only nonzero states, in processing order", () => {
    const segs = pipelineSegments(counts);
    expect(segs.map((s) => s.state)).toEqual([
      "pending",
      "queued",
      "downloading",
      "processing",
      "uploaded",
      "acked",
      "deleted",
    ]);
    expect(segs.reduce((sum, s) => sum + s.pct, 0)).toBeCloseTo(100, 5);
  });
});

describe("pipelineGroups", () => {
  it("emits the four big stages in pipeline order", () => {
    expect(pipelineGroups(counts).map((g) => g.label)).toEqual([
      "待分配",
      "进行中",
      "已交付",
      "异常",
    ]);
  });

  it("big-stage total equals the sum of its small stages", () => {
    const active = pipelineGroups(counts).find((g) => g.key === "active")!;
    expect(active.total).toBe(active.subs.reduce((sum, s) => sum + s.value, 0));
    expect(active.total).toBe(352);
  });

  it("待分配 is a leaf (its card IS its one state, no sub-rows)", () => {
    const pending = pipelineGroups(counts).find((g) => g.key === "pending")!;
    expect(pending.subs).toEqual([]);
    expect(pending.total).toBe(11648);
  });

  it("exposes every small stage even at count 0, so positions stay stable", () => {
    const active = pipelineGroups(counts).find((g) => g.key === "active")!;
    expect(active.subs.map((s) => s.state)).toEqual([
      "queued",
      "downloading",
      "downloaded",
      "processing",
      "processed",
      "uploading",
      "uploaded",
    ]);
    expect(active.subs.find((s) => s.state === "downloaded")!.value).toBe(0);
  });

  it("the three delivery stages' percentages sum to 100 (异常 is out-of-band)", () => {
    const groups = pipelineGroups(counts);
    const delivery = groups.filter((g) => g.key !== "failed");
    expect(delivery.reduce((sum, g) => sum + g.pct, 0)).toBeCloseTo(100, 5);
  });

  it("all zero in, all zero out (no divide-by-zero)", () => {
    const groups = pipelineGroups({});
    expect(groups.every((g) => g.total === 0 && g.pct === 0)).toBe(true);
  });
});
