import { describe, expect, it } from "vitest";
import { operationStatus } from "@/features/batch/operationStatus";
import type { BatchSummary } from "@/api";

function batch(counts: BatchSummary["counts"], extra: Partial<BatchSummary> = {}): BatchSummary {
  return { batch_id: "b", name: "n", bundle_ref: "orch:x@1", target_receiver_id: null,
    status: "running", created_at: "2026-09-27T00:00:00Z", counts,
    objects_exhausted: 0, eta_realtime: null, throughput_per_min: 0, ...extra };
}

describe("operator status", () => {
  it("recognizes completed delivery including pruned history", () => {
    expect(operationStatus(batch({ acked: 2, deleted: 468 })).label).toBe("全部已交付");
  });
  it("does not call stopped work running or completed", () => {
    expect(operationStatus(batch({ deleted: 468, blacklisted: 20000 })).label).toBe("已停止");
  });
  it("surfaces exhausted delivery even while the batch is paused", () => {
    expect(operationStatus(batch({ uploaded: 1 }, { status: "paused", objects_exhausted: 1 })).label).toBe("交付受阻");
  });
  it("distinguishes pause from failure", () => {
    expect(operationStatus(batch({ pending: 10 }, { status: "paused" })).label).toBe("已暂停");
    expect(operationStatus(batch({ failed: 1, pending: 10 })).label).toBe("需要处理");
  });
  it("distinguishes upload from delivery", () => {
    expect(operationStatus(batch({ uploaded: 1 })).label).toBe("等待交付");
  });
  it("does not declare an empty batch delivered", () => {
    expect(operationStatus(batch({})).label).toBe("等待提交");
  });
  it("allows active work alongside stopped granules", () => {
    expect(operationStatus(batch({ pending: 2, blacklisted: 1 })).label).toBe("处理中");
  });
});
