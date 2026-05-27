import type { Credential as ApiCredential } from "@/api";

export type SlotSpec = {
  name: string;
  product: string;
  filename_pattern?: string;
  credential?: string;
};

export type MetaSpec = { name: string; pattern?: string };

export type Schema = { slots: SlotSpec[]; metaFields: MetaSpec[] };

export type CompiledSlot = {
  name: string;
  product: string;
  filename_pattern?: string;
  filename_re: RegExp | null;
  credential?: string;
};

export type CompiledMeta = {
  name: string;
  re: RegExp | null;
  pattern?: string;
};

export type CompiledSchema = { slots: CompiledSlot[]; metaFields: CompiledMeta[] };

function safeRegExp(pattern: string): RegExp | null {
  try {
    return new RegExp(pattern);
  } catch {
    return null;
  }
}

export function compileSchema(schema: Schema): CompiledSchema {
  return {
    slots: schema.slots.map((s) => ({
      name: s.name,
      product: s.product,
      credential: s.credential,
      filename_pattern: s.filename_pattern,
      filename_re: s.filename_pattern ? safeRegExp(s.filename_pattern) : null,
    })),
    metaFields: schema.metaFields.map((m) => ({
      name: m.name,
      pattern: m.pattern,
      re: m.pattern ? safeRegExp(m.pattern) : null,
    })),
  };
}

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

export function validateRow(row: Row, compiled: CompiledSchema): RowErrors;
export function validateRow(row: Row, slots: SlotSpec[], metaFields: MetaSpec[]): RowErrors;
export function validateRow(
  row: Row,
  slotsOrCompiled: SlotSpec[] | CompiledSchema,
  metaFields?: MetaSpec[],
): RowErrors {
  const c: CompiledSchema = Array.isArray(slotsOrCompiled)
    ? compileSchema({ slots: slotsOrCompiled, metaFields: metaFields! })
    : slotsOrCompiled;

  const e: RowErrors = { inputs: {}, meta: {} };
  if (!row.granule_id.trim()) e.granule_id = "必填";
  for (const s of c.slots) {
    const rec: { url?: string; filename?: string; size?: string; checksum?: string } = {};
    const i = row.inputs[s.name];
    if (!i.url.trim()) rec.url = "必填";
    if (s.filename_re) {
      const fname = i.filename || filenameFromUrl(i.url);
      if (fname && !s.filename_re.test(fname))
        rec.filename = `应匹配 /${s.filename_pattern}/`;
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
  for (const m of c.metaFields) {
    const v = row.meta[m.name] ?? "";
    if (!v.trim()) {
      e.meta[m.name] = "必填";
      continue;
    }
    if (m.re && !m.re.test(v)) e.meta[m.name] = `应匹配 /${m.pattern}/`;
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

export function rowHasDraftContent(row: Row): boolean {
  return (
    row.granule_id.trim() !== "" ||
    Object.values(row.inputs).some((i) => i.url.trim() !== "" || i.filename.trim() !== "") ||
    Object.values(row.meta).some((v) => v.trim() !== "")
  );
}

export function credentialsHaveDraftContent(drafts: Record<string, CredDraft>): boolean {
  return Object.values(drafts).some((d) => d.username.trim() !== "" || d.secret.trim() !== "");
}

export function credentialsPayload(drafts: Record<string, CredDraft>): Record<string, ApiCredential> {
  return Object.fromEntries(Object.entries(drafts).map(([name, draft]) => [name, credDraftToApi(name, draft)]));
}

export function credentialsAreValid(names: string[], drafts: Record<string, CredDraft>): boolean {
  return names.every((name) => {
    const draft = drafts[name];
    if (!draft) return false;
    return draft.secret.trim() !== "" && (draft.scheme !== "basic" || draft.username.trim() !== "");
  });
}

export function parseExecutionEnv(text: string | undefined): Record<string, string> {
  const raw = text?.trim() ?? "";
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, String(value)]));
  } catch {
    return {};
  }
}
