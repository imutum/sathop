import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { API, BundleDetail, Credential } from "../api";
import { clearCred, hasCred, loadCred, saveCred } from "../credCache";
import { ActionButton, Alert, FieldLabel, Modal } from "../ui";
import { useToast } from "../toast";

type Props = {
  onClose: () => void;
  onCreated: () => void;
  initialBundle?: string;  // "<name>@<version>" — preselects the bundle dropdown
};

type SlotSpec = {
  name: string;
  product: string;
  filename_pattern?: string;
  credential?: string;
};
type MetaSpec = { name: string; pattern?: string };

type Row = {
  granule_id: string;
  inputs: Record<string, { url: string; filename: string; credential: string }>; // by slot name
  meta: Record<string, string>;
};

function emptyRow(slots: SlotSpec[]): Row {
  const inputs: Row["inputs"] = {};
  for (const s of slots) {
    inputs[s.name] = { url: "", filename: "", credential: s.credential ?? "" };
  }
  return { granule_id: "", inputs, meta: {} };
}

function filenameFromUrl(url: string): string {
  try {
    const u = new URL(url);
    const last = u.pathname.split("/").filter(Boolean).pop();
    return last ?? "";
  } catch {
    return url.split("/").pop() ?? "";
  }
}

function rowToGranule(row: Row, slots: SlotSpec[]) {
  const inputs = slots.map((s) => {
    const i = row.inputs[s.name];
    return {
      url: i.url,
      filename: i.filename || filenameFromUrl(i.url),
      product: s.product,
      ...(i.credential ? { credential: i.credential } : {}),
    };
  });
  return { granule_id: row.granule_id, inputs, meta: row.meta };
}

type RowErrors = {
  granule_id?: string;
  inputs: Record<string, { url?: string; filename?: string }>;
  meta: Record<string, string>;
};

function validateRow(row: Row, slots: SlotSpec[], metaFields: MetaSpec[]): RowErrors {
  const e: RowErrors = { inputs: {}, meta: {} };
  if (!row.granule_id.trim()) e.granule_id = "必填";
  for (const s of slots) {
    const rec: { url?: string; filename?: string } = {};
    const i = row.inputs[s.name];
    if (!i.url.trim()) rec.url = "必填";
    if (s.filename_pattern) {
      const fname = i.filename || filenameFromUrl(i.url);
      try {
        const re = new RegExp(s.filename_pattern);
        if (fname && !re.test(fname)) rec.filename = `应匹配 /${s.filename_pattern}/`;
      } catch {
        /* bad regex server-side; ignore client */
      }
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

function rowHasErrors(e: RowErrors): boolean {
  if (e.granule_id) return true;
  if (Object.values(e.inputs).some((x) => Object.keys(x).length > 0)) return true;
  if (Object.keys(e.meta).length > 0) return true;
  return false;
}

type CredDraft = {
  scheme: "basic" | "bearer";
  username: string;
  secret: string;
};

function emptyCred(): CredDraft {
  return { scheme: "basic", username: "", secret: "" };
}

function credDraftToApi(name: string, d: CredDraft): Credential {
  if (d.scheme === "basic") {
    return { name, scheme: "basic", username: d.username || null, password: d.secret || null };
  }
  return { name, scheme: "bearer", token: d.secret || null };
}

export function CreateBatchModal({ onClose, onCreated, initialBundle }: Props) {
  const [batchId, setBatchId] = useState("");
  const [name, setName] = useState("");
  const [bundleSel, setBundleSel] = useState<string>(initialBundle ?? "");
  const [targetReceiver, setTargetReceiver] = useState<string>("");
  const [envText, setEnvText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [creds, setCreds] = useState<Record<string, CredDraft>>({});
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState<string | null>(null);
  const [showCsv, setShowCsv] = useState(false);

  const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
  const bundles = useQuery({ queryKey: ["bundles"], queryFn: API.bundles });
  const bundleDetail = useQuery({
    queryKey: ["bundle-detail", bundleSel],
    queryFn: () => {
      const [n, v] = bundleSel.split("@");
      return API.bundleDetail(n, v);
    },
    enabled: !!bundleSel,
  });

  const schema = useMemo(() => {
    const m = bundleDetail.data?.manifest;
    if (!m) return null;
    const rawInputs = m.inputs as { slots?: SlotSpec[]; meta?: MetaSpec[] } | undefined;
    const slots = rawInputs?.slots ?? [];
    const metaFields = rawInputs?.meta ?? [];
    return { slots, metaFields };
  }, [bundleDetail.data]);

  const requiredCreds = useMemo<string[]>(
    () => bundleDetail.data?.manifest.requirements?.credentials ?? [],
    [bundleDetail.data],
  );

  // Reset rows + credentials when bundle changes (schema shape differs).
  useEffect(() => {
    if (schema) setRows([emptyRow(schema.slots)]);
    else setRows([]);
  }, [bundleSel, schema?.slots.length, schema?.metaFields.length]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const next: Record<string, CredDraft> = {};
      const nextRemember: Record<string, boolean> = {};
      for (const n of requiredCreds) {
        const stored = await loadCred(n);
        next[n] = creds[n] ?? stored ?? emptyCred();
        // Default the toggle to "on" when a cache entry exists, so the next
        // submit re-saves (handles secret-rotation in place).
        nextRemember[n] = remember[n] ?? hasCred(n);
      }
      if (!cancelled) {
        setCreds(next);
        setRemember(nextRemember);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requiredCreds.join("|")]);

  const parsedEnv = useMemo(() => {
    const txt = envText.trim();
    if (!txt) return { ok: true as const, value: {} as Record<string, string>, count: 0 };
    try {
      const v = JSON.parse(txt);
      if (typeof v !== "object" || v === null || Array.isArray(v)) {
        return { ok: false as const, error: "必须是 JSON 对象 {KEY: value}" };
      }
      const out: Record<string, string> = {};
      for (const [k, val] of Object.entries(v)) out[k] = String(val);
      return { ok: true as const, value: out, count: Object.keys(out).length };
    } catch (e) {
      return { ok: false as const, error: (e as Error).message };
    }
  }, [envText]);

  const rowErrors = useMemo(
    () => (schema ? rows.map((r) => validateRow(r, schema.slots, schema.metaFields)) : []),
    [rows, schema],
  );
  const allRowsOk = schema && rows.length > 0 && rowErrors.every((e) => !rowHasErrors(e));

  const credsPayload = useMemo<Record<string, Credential>>(() => {
    const out: Record<string, Credential> = {};
    for (const [n, d] of Object.entries(creds)) out[n] = credDraftToApi(n, d);
    return out;
  }, [creds]);

  const credsValid = useMemo(
    () =>
      requiredCreds.every((n) => {
        const d = creds[n];
        if (!d) return false;
        return d.secret.trim() !== "" && (d.scheme !== "basic" || d.username.trim() !== "");
      }),
    [creds, requiredCreds],
  );

  const toast = useToast();
  const create = useMutation({
    mutationFn: () =>
      API.createBatch({
        batch_id: batchId,
        name,
        bundle_ref: `orch:${bundleSel}`,
        target_receiver_id: targetReceiver || null,
        granules: rows.map((r) => rowToGranule(r, schema!.slots)),
        execution_env: parsedEnv.ok ? parsedEnv.value : {},
        credentials: credsPayload,
      }),
    onSuccess: (b) => {
      setErr(null);
      // Persist (or evict) cached credentials only after the batch was actually
      // accepted — guarantees we never cache a secret that the orchestrator
      // refused. Fire-and-forget: a failed cache write only affects future
      // autofill, not the current submission.
      for (const n of requiredCreds) {
        const d = creds[n];
        if (remember[n] && d) {
          void saveCred(n, { scheme: d.scheme, username: d.username, secret: d.secret });
        } else if (hasCred(n)) {
          clearCred(n);
        }
      }
      toast.success(`已创建批次 "${b.name}"，共 ${rows.length} 条数据粒`);
      onCreated();
    },
    onError: (e: Error) => {
      setErr(e.message);
      toast.error(`创建失败：${e.message}`);
    },
  });

  const canSubmit =
    batchId.trim() !== "" &&
    name.trim() !== "" &&
    bundleSel !== "" &&
    allRowsOk &&
    parsedEnv.ok &&
    credsValid &&
    !create.isPending;

  // "Dirty" covers every top-level field + any typed cell. Used to confirm
  // accidental backdrop / Esc closes.
  const rowsDirty = rows.some(
    (r) =>
      r.granule_id.trim() !== "" ||
      Object.values(r.inputs).some((i) => i.url.trim() !== "" || i.filename.trim() !== "") ||
      Object.values(r.meta).some((v) => v.trim() !== ""),
  );
  const credsDirty = Object.values(creds).some(
    (d) => d.username.trim() !== "" || d.secret.trim() !== "",
  );
  const dirty =
    batchId.trim() !== "" ||
    name.trim() !== "" ||
    bundleSel !== "" ||
    targetReceiver !== "" ||
    envText.trim() !== "" ||
    rowsDirty ||
    credsDirty;

  return (
    <Modal onClose={onClose} widthClass="w-[min(1200px,95vw)]" dirty={dirty}>
      <h2 className="font-display mb-1 text-lg font-semibold tracking-tight">新建任务</h2>
      <div className="mb-4 flex items-center gap-1.5 text-[11px] text-muted">
        <span>提示：</span>
        <kbd className="rounded-md border border-border bg-subtle px-1.5 py-0.5 font-mono text-[10.5px]">Ctrl</kbd>
        <span>+</span>
        <kbd className="rounded-md border border-border bg-subtle px-1.5 py-0.5 font-mono text-[10.5px]">Enter</kbd>
        <span>提交</span>
        <span className="text-border">·</span>
        <kbd className="rounded-md border border-border bg-subtle px-1.5 py-0.5 font-mono text-[10.5px]">Esc</kbd>
        <span>关闭</span>
      </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) create.mutate();
          }}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && canSubmit) {
              e.preventDefault();
              create.mutate();
            }
          }}
          className="space-y-3 text-sm"
        >
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <label className="block">
              <FieldLabel>批次 ID</FieldLabel>
              <input
                required
                value={batchId}
                onChange={(e) => setBatchId(e.target.value)}
                placeholder="如 mod09a1-2024001"
                className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-xs outline-none transition hover:border-accent/40 focus:border-accent"
              />
            </label>
            <label className="block">
              <FieldLabel>展示名称</FieldLabel>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="MOD09A1 2024 第 1 天"
                className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 outline-none transition hover:border-accent/40 focus:border-accent"
              />
            </label>
            <label className="block">
              <FieldLabel>目标接收端</FieldLabel>
              <select
                value={targetReceiver}
                onChange={(e) => setTargetReceiver(e.target.value)}
                className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 outline-none transition hover:border-accent/40 focus:border-accent"
              >
                <option value="">任意（由调度器决定）</option>
                {(receivers.data ?? []).map((r) => (
                  <option key={r.receiver_id} value={r.receiver_id}>
                    {r.receiver_id}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block">
            <FieldLabel>任务包</FieldLabel>
            <select
              required
              value={bundleSel}
              onChange={(e) => setBundleSel(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-xs outline-none transition hover:border-accent/40 focus:border-accent"
            >
              <option value="">-- 选择任务包 --</option>
              {(bundles.data ?? []).map((b) => (
                <option key={`${b.name}@${b.version}`} value={`${b.name}@${b.version}`}>
                  {b.name}@{b.version}
                  {b.description ? ` — ${b.description}` : ""}
                </option>
              ))}
            </select>
            {(bundles.data ?? []).length === 0 && (
              <div className="mt-1 text-[11px] text-warning">
                尚无已注册任务包。先到"任务包"页上传一个 ZIP。
              </div>
            )}
          </label>

          {bundleDetail.data && schema && <SchemaHint d={bundleDetail.data} />}

          {requiredCreds.length > 0 && (
            <CredentialsBlock
              names={requiredCreds}
              drafts={creds}
              remember={remember}
              onChange={(name, draft) =>
                setCreds((c) => ({ ...c, [name]: draft }))
              }
              onRememberChange={(name, v) =>
                setRemember((r) => ({ ...r, [name]: v }))
              }
              onForget={(name) => {
                clearCred(name);
                setCreds((c) => ({ ...c, [name]: emptyCred() }));
                setRemember((r) => ({ ...r, [name]: false }));
              }}
            />
          )}

          {schema && (
            <GranuleTable
              schema={schema}
              rows={rows}
              errors={rowErrors}
              setRows={setRows}
              onOpenCsv={() => setShowCsv(true)}
            />
          )}

          <details className="rounded-xl border border-border bg-subtle/40 px-3 py-2.5">
            <summary className="cursor-pointer text-xs font-medium text-muted transition hover:text-text">
              高级：环境变量覆盖（可选，JSON 对象）
            </summary>
            <textarea
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              placeholder={'{\n  "SATHOP_FACTOR": "4"\n}'}
              rows={3}
              className="mt-2 w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-xs outline-none transition hover:border-accent/40 focus:border-accent"
            />
            {!parsedEnv.ok && (
              <div className="mt-1 text-[11px] text-danger">
                JSON 错误：{"error" in parsedEnv ? parsedEnv.error : ""}
              </div>
            )}
          </details>

          {err && (
            <Alert>
              <span className="whitespace-pre-wrap">{err}</span>
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <ActionButton type="button" onClick={() => (dirty ? confirm("放弃未保存修改？") && onClose() : onClose())}>
              取消
            </ActionButton>
            <ActionButton
              type="submit"
              tone="primary"
              disabled={!canSubmit}
              pending={create.isPending}
              pendingLabel="提交中…"
            >
              提交 {rows.length > 0 ? `(${rows.length} 条)` : ""}
            </ActionButton>
          </div>
        </form>

        {showCsv && schema && (
          <CsvPasteModal
            schema={schema}
            onClose={() => setShowCsv(false)}
            onImport={(imported) => {
              setRows((cur) => [...cur.filter((r) => r.granule_id.trim() || hasAnyInput(r)), ...imported]);
              setShowCsv(false);
            }}
          />
        )}
    </Modal>
  );
}

function hasAnyInput(r: Row): boolean {
  return Object.values(r.inputs).some((x) => x.url.trim() !== "");
}

function SchemaHint({ d }: { d: BundleDetail }) {
  const m = d.manifest;
  const pipCount = m.requirements?.pip?.length ?? 0;
  const aptCount = m.requirements?.apt?.length ?? 0;
  return (
    <div className="rounded-lg border border-border bg-subtle/40 px-3 py-2 text-[11px] text-muted">
      <div>
        入口：<span className="font-mono text-text">{m.execution.entrypoint}</span>
      </div>
      <div className="mt-0.5">
        依赖：{pipCount} 个 pip{aptCount > 0 ? ` · ${aptCount} 个 apt` : ""}
      </div>
    </div>
  );
}

function GranuleTable({
  schema,
  rows,
  errors,
  setRows,
  onOpenCsv,
}: {
  schema: { slots: SlotSpec[]; metaFields: MetaSpec[] };
  rows: Row[];
  errors: RowErrors[];
  setRows: (u: Row[] | ((c: Row[]) => Row[])) => void;
  onOpenCsv: () => void;
}) {
  const addRow = () => setRows((c) => [...c, emptyRow(schema.slots)]);
  const removeRow = (idx: number) => {
    const r = rows[idx];
    const hasContent =
      r.granule_id.trim() !== "" ||
      Object.values(r.inputs).some((i) => i.url.trim() || i.filename.trim()) ||
      Object.values(r.meta).some((v) => v.trim());
    if (hasContent && !confirm(`删除第 ${idx + 1} 行？`)) return;
    setRows((c) => c.filter((_, i) => i !== idx));
  };
  const updateCell = (idx: number, fn: (r: Row) => Row) =>
    setRows((c) => c.map((r, i) => (i === idx ? fn(r) : r)));

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs text-muted">数据粒 · {rows.length} 条</span>
        <div className="flex gap-1.5 text-xs">
          <button type="button" onClick={onOpenCsv}
            className="rounded-md border border-border bg-surface px-2 py-1 text-muted transition hover:border-accent/40 hover:text-text">
            粘贴 CSV
          </button>
          <button type="button" onClick={addRow}
            className="rounded-md border border-border bg-surface px-2 py-1 text-muted transition hover:border-accent/40 hover:text-text">
            + 添加行
          </button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="bg-subtle/60 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
            <tr>
              <th className="px-2 py-1.5">granule_id</th>
              {schema.slots.map((s) => (
                <th key={s.name} className="px-2 py-1.5" colSpan={s.credential ? 2 : 3} title={`product=${s.product}`}>
                  {s.name}
                </th>
              ))}
              {schema.metaFields.map((m) => (
                <th key={m.name} className="px-2 py-1.5" title={m.pattern ? `/${m.pattern}/` : ""}>
                  {m.name}
                </th>
              ))}
              <th className="px-2 py-1.5"></th>
            </tr>
            <tr className="text-[10px] normal-case">
              <th></th>
              {schema.slots.flatMap((s) =>
                s.credential
                  ? [
                      <th key={`${s.name}-url`} className="px-2 py-1 text-muted">url</th>,
                      <th key={`${s.name}-filename`} className="px-2 py-1 text-muted">filename</th>,
                    ]
                  : [
                      <th key={`${s.name}-url`} className="px-2 py-1 text-muted">url</th>,
                      <th key={`${s.name}-filename`} className="px-2 py-1 text-muted">filename</th>,
                      <th key={`${s.name}-credential`} className="px-2 py-1 text-muted">credential</th>,
                    ]
              )}
              {schema.metaFields.map((m) => <th key={m.name} className="px-2 py-1 text-muted">{m.pattern ?? "—"}</th>)}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => {
              const e = errors[idx] ?? { inputs: {}, meta: {} };
              return (
                <tr key={idx} className="border-t border-border align-top">
                  <td className="px-2 py-1">
                    <Cell
                      value={r.granule_id}
                      onChange={(v) => updateCell(idx, (row) => ({ ...row, granule_id: v }))}
                      error={e.granule_id}
                      placeholder="唯一"
                    />
                  </td>
                  {schema.slots.flatMap((s) => {
                    const slotErr = e.inputs[s.name] ?? {};
                    const baseCells = [
                      <td key={`${s.name}-url`} className="px-2 py-1">
                        <Cell
                          value={r.inputs[s.name]?.url ?? ""}
                          onChange={(v) => updateCell(idx, (row) => ({
                            ...row,
                            inputs: { ...row.inputs, [s.name]: { ...row.inputs[s.name], url: v } },
                          }))}
                          error={slotErr.url}
                          placeholder="https://…"
                          mono
                        />
                      </td>,
                      <td key={`${s.name}-filename`} className="px-2 py-1">
                        <Cell
                          value={r.inputs[s.name]?.filename ?? ""}
                          onChange={(v) => updateCell(idx, (row) => ({
                            ...row,
                            inputs: { ...row.inputs, [s.name]: { ...row.inputs[s.name], filename: v } },
                          }))}
                          error={slotErr.filename}
                          placeholder="留空=自动"
                          mono
                        />
                      </td>,
                    ];
                    if (s.credential) return baseCells;
                    return [
                      ...baseCells,
                      <td key={`${s.name}-credential`} className="px-2 py-1">
                        <Cell
                          value={r.inputs[s.name]?.credential ?? ""}
                          onChange={(v) => updateCell(idx, (row) => ({
                            ...row,
                            inputs: { ...row.inputs, [s.name]: { ...row.inputs[s.name], credential: v } },
                          }))}
                          placeholder="凭证名（可空）"
                        />
                      </td>,
                    ];
                  })}
                  {schema.metaFields.map((m) => (
                    <td key={m.name} className="px-2 py-1">
                      <Cell
                        value={r.meta[m.name] ?? ""}
                        onChange={(v) => updateCell(idx, (row) => ({
                          ...row,
                          meta: { ...row.meta, [m.name]: v },
                        }))}
                        error={e.meta[m.name]}
                        placeholder={m.pattern ?? ""}
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right">
                    <button type="button" onClick={() => removeRow(idx)}
                      className="text-muted hover:text-danger">×</button>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={99} className="px-4 py-4 text-center text-muted">
                  还没有数据粒。点击 "+ 添加行" 或 "粘贴 CSV"。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({
  value, onChange, error, placeholder, mono,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: string;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        title={error}
        className={`w-full rounded-md border bg-bg px-2 py-1 outline-none transition ${
          error ? "border-danger/60" : "border-border focus:border-accent"
        } ${mono ? "font-mono text-[11px]" : "text-xs"}`}
      />
      {error && <div className="mt-0.5 text-[10px] text-danger">{error}</div>}
    </div>
  );
}

function CsvPasteModal({
  schema,
  onClose,
  onImport,
}: {
  schema: { slots: SlotSpec[]; metaFields: MetaSpec[] };
  onClose: () => void;
  onImport: (rows: Row[]) => void;
}) {
  const headers = useMemo(() => {
    const h = ["granule_id"];
    for (const s of schema.slots) {
      h.push(`${s.name}.url`, `${s.name}.filename`);
      if (!s.credential) h.push(`${s.name}.credential`);
    }
    for (const m of schema.metaFields) h.push(`meta.${m.name}`);
    return h;
  }, [schema]);

  const [text, setText] = useState(headers.join(",") + "\n");
  const [parseErr, setParseErr] = useState<string | null>(null);

  const doImport = () => {
    setParseErr(null);
    const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
    if (lines.length < 2) {
      setParseErr("至少需要一行表头 + 一行数据");
      return;
    }
    const delim = lines[0].includes("\t") ? "\t" : ",";
    const head = lines[0].split(delim).map((x) => x.trim());
    const missing = headers.filter((h) => !head.includes(h));
    if (missing.length && !missing.every((h) => h.endsWith(".credential"))) {
      setParseErr(`表头缺少：${missing.join(", ")}`);
      return;
    }
    const rows: Row[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cells = lines[i].split(delim).map((x) => x.trim());
      const byHead: Record<string, string> = {};
      head.forEach((h, idx) => (byHead[h] = cells[idx] ?? ""));
      const row = emptyRow(schema.slots);
      row.granule_id = byHead["granule_id"] ?? "";
      for (const s of schema.slots) {
        row.inputs[s.name].url = byHead[`${s.name}.url`] ?? "";
        row.inputs[s.name].filename = byHead[`${s.name}.filename`] ?? "";
        const credHead = byHead[`${s.name}.credential`];
        if (credHead !== undefined) row.inputs[s.name].credential = credHead;
      }
      for (const m of schema.metaFields) {
        row.meta[m.name] = byHead[`meta.${m.name}`] ?? "";
      }
      rows.push(row);
    }
    if (rows.length === 0) {
      setParseErr("没有解析到任何数据行");
      return;
    }
    onImport(rows);
  };

  return (
    <Modal onClose={onClose} widthClass="w-[720px]" zIndex={60} dirty={text.split(/\r?\n/).length > 2}>
      <h3 className="font-display mb-2 text-base font-semibold tracking-tight">粘贴 CSV / TSV</h3>
      <div className="mb-3 text-[11px] text-muted">
        第一行必须是表头，列顺序不限。自动识别逗号或 Tab 分隔。
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-[11px] outline-none transition hover:border-accent/40 focus:border-accent"
      />
      {parseErr && (
        <div className="mt-2">
          <Alert>{parseErr}</Alert>
        </div>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <ActionButton onClick={onClose}>取消</ActionButton>
        <ActionButton tone="primary" onClick={doImport}>导入</ActionButton>
      </div>
    </Modal>
  );
}

function CredentialsBlock({
  names,
  drafts,
  remember,
  onChange,
  onRememberChange,
  onForget,
}: {
  names: string[];
  drafts: Record<string, CredDraft>;
  remember: Record<string, boolean>;
  onChange: (name: string, d: CredDraft) => void;
  onRememberChange: (name: string, v: boolean) => void;
  onForget: (name: string) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend><FieldLabel>凭证 · 任务包需要 {names.length} 个</FieldLabel></legend>
      <div className="space-y-3 rounded-xl border border-border bg-subtle/40 p-3">
        {names.map((name) => {
          const d = drafts[name] ?? { scheme: "basic", username: "", secret: "" };
          const schemeId = `cred-${name}-scheme`;
          const userId = `cred-${name}-user`;
          const secretId = `cred-${name}-secret`;
          const rememberId = `cred-${name}-remember`;
          const cached = hasCred(name);
          return (
            <div
              key={name}
              className="grid grid-cols-[140px_100px_1fr_2fr_auto] gap-2 items-center text-xs"
            >
              <label htmlFor={secretId} className="font-mono" title="凭证名">
                {name}
              </label>
              <select
                id={schemeId}
                aria-label={`${name} 凭证方案`}
                value={d.scheme}
                onChange={(e) =>
                  onChange(name, { ...d, scheme: e.target.value as "basic" | "bearer" })
                }
                className="rounded-md border border-border bg-bg px-2 py-1 outline-none transition hover:border-accent/40 focus:border-accent"
              >
                <option value="basic">Basic</option>
                <option value="bearer">Bearer</option>
              </select>
              {d.scheme === "basic" ? (
                <input
                  id={userId}
                  aria-label={`${name} 用户名`}
                  autoComplete="off"
                  value={d.username}
                  onChange={(e) => onChange(name, { ...d, username: e.target.value })}
                  placeholder="用户名"
                  className="rounded-md border border-border bg-bg px-2 py-1 outline-none transition hover:border-accent/40 focus:border-accent"
                />
              ) : (
                <div className="text-muted">—</div>
              )}
              <input
                id={secretId}
                aria-label={d.scheme === "basic" ? `${name} 密码` : `${name} Token`}
                autoComplete="off"
                type="password"
                value={d.secret}
                onChange={(e) => onChange(name, { ...d, secret: e.target.value })}
                placeholder={d.scheme === "basic" ? "密码" : "Token"}
                className="rounded-md border border-border bg-bg px-2 py-1 font-mono outline-none transition hover:border-accent/40 focus:border-accent"
              />
              <div className="flex items-center gap-2 whitespace-nowrap">
                <label
                  htmlFor={rememberId}
                  className="flex items-center gap-1 text-[11px] text-muted"
                  title="勾选后，提交成功时把该凭证保存到本浏览器；下次新建任务自动填入。"
                >
                  <input
                    id={rememberId}
                    type="checkbox"
                    checked={remember[name] ?? false}
                    onChange={(e) => onRememberChange(name, e.target.checked)}
                    className="accent-accent"
                  />
                  记住
                </label>
                {cached && (
                  <button
                    type="button"
                    onClick={() => onForget(name)}
                    className="text-[11px] text-muted hover:text-danger"
                    title="从本浏览器删除已保存的凭证"
                  >
                    清除
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="text-[11px] text-muted">
        凭证仅保存于本批次数据库行；worker 在 lease 时一次性取用。轮换 = 创建新批次。
        勾选"记住"后，凭证会被保存在本浏览器的 localStorage（明文，与登录 token 同等级别），下次新建任务自动填入。
      </div>
    </fieldset>
  );
}
