import { describe, expect, it } from "vitest";
import { parseExecutionEnv } from "@/features/batch/serialization";

describe("execution environment parsing", () => {
  it.each([undefined, "", "  "])("accepts an empty environment: %s", (text) => {
    expect(parseExecutionEnv(text, { strict: true })).toEqual({});
  });

  it("preserves value conversion and whitespace in both modes", () => {
    const text = '{"PATH":" /data with spaces ","COUNT":3,"ENABLED":true}';
    const expected = { PATH: " /data with spaces ", COUNT: "3", ENABLED: "true" };
    expect(parseExecutionEnv(text)).toEqual(expected);
    expect(parseExecutionEnv(text, { strict: true })).toEqual(expected);
  });

  it.each(["{unfinished", "[]", "null", "42", '"string"'])("rejects %s only in strict mode", (text) => {
    expect(parseExecutionEnv(text)).toEqual({});
    expect(() => parseExecutionEnv(text, { strict: true })).toThrow();
  });
});
