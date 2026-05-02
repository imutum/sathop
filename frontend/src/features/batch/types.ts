import type { Credential as ApiCredential } from "@/api";

export type SlotSpec = {
  name: string;
  product: string;
  filename_pattern?: string;
  credential?: string;
};

export type MetaSpec = { name: string; pattern?: string };

export type Schema = { slots: SlotSpec[]; metaFields: MetaSpec[] };

export type Row = {
  granule_id: string;
  inputs: Record<
    string,
    { url: string; filename: string; credential: string; size: string; checksum: string }
  >;
  meta: Record<string, string>;
};

export type RowErrors = {
  granule_id?: string;
  inputs: Record<string, { url?: string; filename?: string; size?: string; checksum?: string }>;
  meta: Record<string, string>;
};

export type CredDraft = {
  scheme: "basic" | "bearer";
  username: string;
  secret: string;
};

export function credDraftToApi(name: string, d: CredDraft): ApiCredential {
  if (d.scheme === "basic") {
    return { name, scheme: "basic", username: d.username || null, password: d.secret || null };
  }
  return { name, scheme: "bearer", token: d.secret || null };
}

export function emptyRow(slots: SlotSpec[]): Row {
  const inputs: Row["inputs"] = {};
  for (const s of slots) {
    inputs[s.name] = {
      url: "",
      filename: "",
      credential: s.credential ?? "",
      size: "",
      checksum: "",
    };
  }
  return { granule_id: "", inputs, meta: {} };
}

export function emptyCred(): CredDraft {
  return { scheme: "basic", username: "", secret: "" };
}

export function filenameFromUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname.split("/").filter(Boolean).pop() ?? "";
  } catch {
    return url.split("/").pop() ?? "";
  }
}

const SHA256_RE = /^[0-9a-fA-F]{64}$/;

export function rowToGranule(row: Row, slots: SlotSpec[]) {
  const inputs = slots.map((s) => {
    const i = row.inputs[s.name];
    const sizeStr = i.size.trim();
    const sumStr = i.checksum.trim();
    const sizeNum = sizeStr ? Number(sizeStr) : NaN;
    return {
      url: i.url,
      filename: i.filename || filenameFromUrl(i.url),
      product: s.product,
      ...(i.credential ? { credential: i.credential } : {}),
      ...(Number.isFinite(sizeNum) && sizeNum > 0 ? { size: sizeNum } : {}),
      ...(sumStr ? { checksum: sumStr.toLowerCase() } : {}),
    };
  });
  return { granule_id: row.granule_id, inputs, meta: row.meta };
}

export function validateRow(row: Row, slots: SlotSpec[], metaFields: MetaSpec[]): RowErrors {
  const e: RowErrors = { inputs: {}, meta: {} };
  if (!row.granule_id.trim()) e.granule_id = "必填";
  for (const s of slots) {
    const rec: { url?: string; filename?: string; size?: string; checksum?: string } = {};
    const i = row.inputs[s.name];
    if (!i.url.trim()) rec.url = "必填";
    if (s.filename_pattern) {
      const fname = i.filename || filenameFromUrl(i.url);
      try {
        const re = new RegExp(s.filename_pattern);
        if (fname && !re.test(fname)) rec.filename = `应匹配 /${s.filename_pattern}/`;
      } catch {
        /* server-side regex; ignore on client */
      }
    }
    const sizeStr = i.size.trim();
    if (sizeStr) {
      const n = Number(sizeStr);
      if (!Number.isInteger(n) || n <= 0) rec.size = "应为正整数字节数";
    }
    const sumStr = i.checksum.trim();
    if (sumStr && !SHA256_RE.test(sumStr)) {
      rec.checksum = "应为 64 位 sha256 十六进制";
    }
    if (Object.keys(rec).length) e.inputs[s.name] = rec;
  }
  for (const m of metaFields) {
    const v = row.meta[m.name] ?? "";
    if (!v.trim()) {
      e.meta[m.name] = "必填";
      continue;
    }
    if (m.pattern) {
      try {
        const re = new RegExp(m.pattern);
        if (!re.test(v)) e.meta[m.name] = `应匹配 /${m.pattern}/`;
      } catch {
        /* ignore */
      }
    }
  }
  return e;
}

export function rowHasErrors(e: RowErrors): boolean {
  if (e.granule_id) return true;
  if (Object.values(e.inputs).some((x) => Object.keys(x).length > 0)) return true;
  if (Object.keys(e.meta).length > 0) return true;
  return false;
}

export function hasAnyInput(r: Row): boolean {
  return Object.values(r.inputs).some((x) => x.url.trim() !== "");
}
