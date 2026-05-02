import { describe, it, expect } from "vitest";
import {
  type Schema,
  type Row,
  credDraftToApi,
  emptyCred,
  emptyRow,
  filenameFromUrl,
  hasAnyInput,
  rowHasErrors,
  rowToGranule,
  validateRow,
} from "@/features/batch/types";

const schema: Schema = {
  slots: [
    { name: "raw", product: "MOD09A1" },
    { name: "mask", product: "QC", filename_pattern: "\\.tif$" },
    { name: "aux", product: "DEM", credential: "earthdata" },
  ],
  metaFields: [
    { name: "tile" },
    { name: "year", pattern: "^[0-9]{4}$" },
  ],
};

describe("emptyRow", () => {
  it("creates one input slot per schema slot, with credentials prefilled from spec", () => {
    const r = emptyRow(schema.slots);
    expect(Object.keys(r.inputs)).toEqual(["raw", "mask", "aux"]);
    expect(r.inputs.aux.credential).toBe("earthdata");
    expect(r.inputs.raw.credential).toBe(""); // no spec default
    expect(r.granule_id).toBe("");
    expect(r.meta).toEqual({});
  });
});

describe("emptyCred / credDraftToApi", () => {
  it("returns a fresh basic-scheme draft", () => {
    expect(emptyCred()).toEqual({ scheme: "basic", username: "", secret: "" });
  });
  it("converts basic drafts to API shape with null for blanks", () => {
    expect(
      credDraftToApi("ftp", { scheme: "basic", username: "alice", secret: "" }),
    ).toEqual({ name: "ftp", scheme: "basic", username: "alice", password: null });
  });
  it("converts bearer drafts to API shape", () => {
    expect(
      credDraftToApi("edl", { scheme: "bearer", username: "ignored", secret: "tok" }),
    ).toEqual({ name: "edl", scheme: "bearer", token: "tok" });
  });
});

describe("filenameFromUrl", () => {
  it("pulls the last path segment from a well-formed URL", () => {
    expect(filenameFromUrl("https://example.com/a/b/foo.tif")).toBe("foo.tif");
  });
  it("ignores trailing slashes", () => {
    expect(filenameFromUrl("https://example.com/a/b/")).toBe("b");
  });
  it("falls back to the last slash split for non-URL strings", () => {
    expect(filenameFromUrl("not a url")).toBe("not a url");
    expect(filenameFromUrl("some/path/x.zip")).toBe("x.zip");
  });
});

describe("validateRow / rowHasErrors", () => {
  function fillRow(): Row {
    return {
      granule_id: "abc",
      inputs: {
        raw: { url: "https://x/raw.bin", filename: "raw.bin", credential: "", size: "", checksum: "" },
        mask: { url: "https://x/m.tif", filename: "m.tif", credential: "", size: "", checksum: "" },
        aux: { url: "https://x/dem.tif", filename: "dem.tif", credential: "earthdata", size: "", checksum: "" },
      },
      meta: { tile: "h12v04", year: "2024" },
    };
  }

  it("a fully-filled row is error-free", () => {
    const e = validateRow(fillRow(), schema.slots, schema.metaFields);
    expect(rowHasErrors(e)).toBe(false);
  });

  it("flags missing granule_id", () => {
    const r = fillRow();
    r.granule_id = "  ";
    const e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.granule_id).toBe("必填");
    expect(rowHasErrors(e)).toBe(true);
  });

  it("flags missing url on a slot", () => {
    const r = fillRow();
    r.inputs.raw.url = "";
    const e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.inputs.raw?.url).toBe("必填");
    expect(rowHasErrors(e)).toBe(true);
  });

  it("checks filename against the slot's regex", () => {
    const r = fillRow();
    r.inputs.mask.filename = "wrong.bin";
    const e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.inputs.mask?.filename).toContain("应匹配");
  });

  it("rejects size that is not a positive integer", () => {
    const r = fillRow();
    r.inputs.raw.size = "0";
    let e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.inputs.raw?.size).toBe("应为正整数字节数");
    r.inputs.raw.size = "1.5";
    e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.inputs.raw?.size).toBe("应为正整数字节数");
  });

  it("rejects malformed sha256", () => {
    const r = fillRow();
    r.inputs.raw.checksum = "xx";
    const e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.inputs.raw?.checksum).toContain("64 位 sha256");
  });

  it("flags missing meta + meta regex", () => {
    const r = fillRow();
    r.meta.tile = "";
    r.meta.year = "abcd";
    const e = validateRow(r, schema.slots, schema.metaFields);
    expect(e.meta.tile).toBe("必填");
    expect(e.meta.year).toContain("应匹配");
  });
});

describe("rowToGranule", () => {
  it("derives filename from url when blank, omits credential when blank, drops invalid size, lowercases checksum", () => {
    const row: Row = {
      granule_id: "g1",
      inputs: {
        raw: {
          url: "https://x/A.tif",
          filename: "",
          credential: "",
          size: "abc", // invalid → dropped
          checksum: "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899",
        },
      },
      meta: {},
    };
    const g = rowToGranule(row, [{ name: "raw", product: "MOD" }]);
    expect(g.inputs[0].filename).toBe("A.tif");
    expect((g.inputs[0] as { size?: number }).size).toBeUndefined();
    expect((g.inputs[0] as { credential?: string }).credential).toBeUndefined();
    expect(g.inputs[0].checksum).toBe(
      "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
    );
  });

  it("preserves valid size and credential", () => {
    const row: Row = {
      granule_id: "g2",
      inputs: {
        raw: { url: "u", filename: "f", credential: "c", size: "1024", checksum: "" },
      },
      meta: { tile: "h12v04" },
    };
    const g = rowToGranule(row, [{ name: "raw", product: "MOD" }]);
    expect(g.inputs[0]).toMatchObject({ filename: "f", credential: "c", size: 1024 });
    expect(g.meta).toEqual({ tile: "h12v04" });
  });
});

describe("hasAnyInput", () => {
  it("true when any slot has a non-blank url", () => {
    const r = emptyRow(schema.slots);
    expect(hasAnyInput(r)).toBe(false);
    r.inputs.mask.url = "u";
    expect(hasAnyInput(r)).toBe(true);
  });
});
