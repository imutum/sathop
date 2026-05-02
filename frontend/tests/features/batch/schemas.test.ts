import { describe, it, expect } from "vitest";
import { createBatchHeaderSchema } from "@/features/batch/schemas";

const VALID = {
  batchId: "mod09a1-2024001",
  name: "MOD09A1 2024 第 1 天",
  bundleSel: "mod09a1@1.0.0",
  targetReceiver: "",
  envText: "",
};

describe("features/batch/createBatchHeaderSchema", () => {
  it("accepts a fully filled valid header", () => {
    const r = createBatchHeaderSchema.safeParse({
      ...VALID,
      targetReceiver: "rx-1",
      envText: '{"SATHOP_FACTOR": "4"}',
    });
    expect(r.success).toBe(true);
  });

  it("accepts the minimum required fields with empty optional ones", () => {
    expect(createBatchHeaderSchema.safeParse(VALID).success).toBe(true);
  });

  it.each([
    ["batchId", "请填批次 ID"],
    ["name", "请填展示名称"],
    ["bundleSel", "请选择任务包"],
  ])("rejects empty %s with the user-facing prompt", (field, msg) => {
    const r = createBatchHeaderSchema.safeParse({ ...VALID, [field]: "" });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues.find((i) => i.path[0] === field)?.message).toBe(msg);
    }
  });

  describe("envText", () => {
    it("treats whitespace-only text as empty (passes)", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: "   \n  " });
      expect(r.success).toBe(true);
    });

    it("accepts a JSON object", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: '{"K":"v"}' });
      expect(r.success).toBe(true);
    });

    it("rejects malformed JSON", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: "{not json" });
      expect(r.success).toBe(false);
      if (!r.success) {
        expect(r.error.issues.find((i) => i.path[0] === "envText")?.message).toBe(
          "环境变量必须是 JSON 对象 {KEY: value}",
        );
      }
    });

    it("rejects a JSON array (must be an object)", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: "[1,2]" });
      expect(r.success).toBe(false);
    });

    it("rejects a JSON primitive (must be an object)", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: '"string"' });
      expect(r.success).toBe(false);
    });

    it("rejects null (typeof null === 'object', but the schema explicitly excludes it)", () => {
      const r = createBatchHeaderSchema.safeParse({ ...VALID, envText: "null" });
      expect(r.success).toBe(false);
    });
  });
});
