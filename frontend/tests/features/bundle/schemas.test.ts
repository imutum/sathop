import { describe, it, expect } from "vitest";
import { uploadBundleSchema } from "@/features/bundle/schemas";

function makeFile(name: string, contents = "x") {
  return new File([contents], name, { type: "application/zip" });
}

describe("features/bundle/uploadBundleSchema", () => {
  it("accepts a .zip file with optional description", () => {
    const r = uploadBundleSchema.safeParse({
      file: makeFile("hello.zip"),
      description: "ok",
    });
    expect(r.success).toBe(true);
  });

  it("accepts a .zip file without a description", () => {
    const r = uploadBundleSchema.safeParse({ file: makeFile("hello.zip") });
    expect(r.success).toBe(true);
  });

  it("treats the .zip suffix case-insensitively", () => {
    const r = uploadBundleSchema.safeParse({ file: makeFile("HELLO.ZIP") });
    expect(r.success).toBe(true);
  });

  it("rejects a missing file with the prompt to pick one", () => {
    const r = uploadBundleSchema.safeParse({ description: "no file" });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues[0]?.path).toEqual(["file"]);
      expect(r.error.issues[0]?.message).toBe("请选择一个 ZIP 文件");
    }
  });

  it("rejects a non-File value with the same prompt", () => {
    const r = uploadBundleSchema.safeParse({ file: "not-a-file", description: "" });
    expect(r.success).toBe(false);
    if (!r.success) expect(r.error.issues[0]?.message).toBe("请选择一个 ZIP 文件");
  });

  it("rejects a non-zip file with the format hint", () => {
    const r = uploadBundleSchema.safeParse({ file: makeFile("hello.tar") });
    expect(r.success).toBe(false);
    if (!r.success) expect(r.error.issues[0]?.message).toBe("文件需为 .zip 格式");
  });
});
