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

export function filenameFromUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname.split("/").filter(Boolean).pop() ?? "";
  } catch {
    return url.split("/").pop() ?? "";
  }
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
