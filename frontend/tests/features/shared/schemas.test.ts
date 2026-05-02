import { describe, it, expect } from "vitest";
import { SHARED_NAME_RE, uploadSharedSchema } from "@/features/shared/schemas";

function makeFile(name = "blob.bin") {
  return new File(["x"], name);
}

describe("features/shared/SHARED_NAME_RE", () => {
  it.each(["a", "mask.tif", "a-b_c.0", "A1", "x".repeat(255)])("accepts %s", (n) => {
    expect(SHARED_NAME_RE.test(n)).toBe(true);
  });
  it.each([
    "",
    ".hidden",
    "_under",
    "-dash",
    "name with space",
    "中文",
    "x".repeat(256),
  ])("rejects %s", (n) => {
    expect(SHARED_NAME_RE.test(n)).toBe(false);
  });
});

describe("features/shared/uploadSharedSchema", () => {
  it("accepts a valid name + File + optional description", () => {
    const r = uploadSharedSchema.safeParse({
      name: "mask.tif",
      file: makeFile(),
      description: "raster mask",
    });
    expect(r.success).toBe(true);
  });

  it("accepts an empty description (omitted)", () => {
    const r = uploadSharedSchema.safeParse({ name: "mask.tif", file: makeFile() });
    expect(r.success).toBe(true);
  });

  it("rejects an empty name with the fill-name prompt", () => {
    const r = uploadSharedSchema.safeParse({ name: "", file: makeFile() });
    expect(r.success).toBe(false);
    if (!r.success) {
      const msgs = r.error.issues.filter((i) => i.path[0] === "name").map((i) => i.message);
      expect(msgs).toContain("请填写名称");
    }
  });

  it("rejects a name starting with a dot with the regex hint", () => {
    const r = uploadSharedSchema.safeParse({ name: ".rc", file: makeFile() });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues.find((i) => i.path[0] === "name")?.message).toMatch(/名称不合法/);
    }
  });

  it("rejects when file is missing or not a File", () => {
    const r1 = uploadSharedSchema.safeParse({ name: "mask.tif" });
    expect(r1.success).toBe(false);
    const r2 = uploadSharedSchema.safeParse({ name: "mask.tif", file: "blob" });
    expect(r2.success).toBe(false);
    if (!r2.success) {
      expect(r2.error.issues.find((i) => i.path[0] === "file")?.message).toBe("请选择文件");
    }
  });
});
