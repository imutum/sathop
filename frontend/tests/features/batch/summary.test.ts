import { describe, expect, it } from "vitest";
import { batchProgress, isBatchClosed } from "@/features/batch/summary";

describe("batch progress", () => {
  it("counts delivery acknowledgements as complete, but not uploads or stopped work", () => {
    const batch = { counts: { acked: 2, deleted: 3, uploaded: 4, downloading: 2, failed: 1, blacklisted: 1 } };
    expect(batchProgress(batch)).toEqual({ total: 13, done: 5, errors: 2, inFlight: 2, pct: 38 });
    expect(isBatchClosed(batch)).toBe(false);
  });

  it("does not treat an empty batch as complete", () => {
    expect(batchProgress({ counts: {} })).toEqual({ total: 0, done: 0, errors: 0, inFlight: 0, pct: 0 });
    expect(isBatchClosed({ counts: {} })).toBe(false);
  });

  it("keeps retained delivery totals in progress after detail cleanup", () => {
    const batch = { counts: { acked: 2, deleted: 998 } };
    expect(batchProgress(batch)).toMatchObject({ total: 1000, done: 1000, pct: 100 });
    expect(isBatchClosed(batch)).toBe(true);
  });
});
