import { type Row, type SlotSpec, filenameFromUrl } from "./types";

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
