import { describe, expect, it } from "vitest";
import { parseConcurrency } from "@/features/nodes/workerActions";

describe("concurrency input", () => {
  it("restores defaults for blank input", () => {
    for (const value of ["", "  ", null, undefined]) expect(parseConcurrency(value)).toBeNull();
  });

  it("accepts both text fields and numeric v-model values", () => {
    for (const value of [" 8 ", 8]) expect(parseConcurrency(value)).toBe(8);
    expect(parseConcurrency("1")).toBe(1);
  });

  it("rejects fractions, non-positive numbers and non-finite values", () => {
    for (const value of ["1.5", 0, -2, "NaN", NaN, "Infinity", Infinity, "invalid"]) {
      expect(parseConcurrency(value)).toBeUndefined();
    }
  });
});
