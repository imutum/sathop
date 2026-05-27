import {
  type CompiledSchema,
  type MetaSpec,
  type Row,
  type RowErrors,
  type Schema,
  type SlotSpec,
  filenameFromUrl,
} from "./types";

const SHA256_RE = /^[0-9a-fA-F]{64}$/;

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
