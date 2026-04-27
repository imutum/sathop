import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API, BundleDetail, BundleFileEntry, BundleSummary } from "../api";
import { ActionButton, Badge, Card, CopyButton, Modal } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function Bundles() {
  const qc = useQueryClient();
  const toast = useToast();
  const [search] = useSearchParams();
  const [selected, setSelected] = useState<{ name: string; version: string } | null>(
    () => {
      const n = search.get("name");
      const v = search.get("version");
      return n && v ? { name: n, version: v } : null;
    },
  );
  const [showUpload, setShowUpload] = useState(false);

  // Re-sync when URL changes (e.g. user clicked a different batch's bundle_ref
  // link while already on this page).
  useEffect(() => {
    const n = search.get("name");
    const v = search.get("version");
    if (n && v && (selected?.name !== n || selected?.version !== v)) {
      setSelected({ name: n, version: v });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const list = useQuery({
    queryKey: ["bundles"],
    queryFn: API.bundles,
  });

  const detail = useQuery({
    queryKey: ["bundle-detail", selected?.name, selected?.version],
    queryFn: () => API.bundleDetail(selected!.name, selected!.version),
    enabled: !!selected,
  });

  const del = useMutation({
    mutationFn: ({ name, version }: { name: string; version: string }) =>
      API.deleteBundle(name, version),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ["bundles"] });
      setSelected(null);
      toast.success(`已删除任务包 ${v.name}@${v.version}`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const rows = list.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">任务包</h1>
        <ActionButton tone="primary" onClick={() => setShowUpload(true)}>
          上传 ZIP
        </ActionButton>
      </div>

      <div className="grid grid-cols-[2fr_3fr] gap-6">
        <Card>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="pb-2">名称</th>
                <th className="pb-2">版本</th>
                <th className="pb-2">大小</th>
                <th className="pb-2">上传时间</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b: BundleSummary) => {
                const isActive =
                  selected?.name === b.name && selected?.version === b.version;
                return (
                  <tr
                    key={`${b.name}@${b.version}`}
                    onClick={() => setSelected({ name: b.name, version: b.version })}
                    className={`cursor-pointer border-t border-border ${
                      isActive ? "bg-accent/10" : "hover:bg-bg/50"
                    }`}
                  >
                    <td className="py-2 pr-3 font-mono text-xs">{b.name}</td>
                    <td className="py-2 pr-3 text-xs">
                      <Badge tone="info">{b.version}</Badge>
                    </td>
                    <td className="py-2 pr-3 text-xs text-muted">{fmtBytes(b.size)}</td>
                    <td className="py-2 pr-3 text-xs text-muted">{fmtAge(b.uploaded_at)}</td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-10 text-center text-sm text-muted">
                    暂无任务包。点击上方"上传 ZIP"开始添加。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>

        <Card>
          {!selected && (
            <div className="py-12 text-center text-sm text-muted">
              选择左侧任意任务包查看清单。
            </div>
          )}
          {selected && detail.isLoading && (
            <div className="py-8 text-center text-sm text-muted">加载中…</div>
          )}
          {selected && detail.data && <BundleManifestView d={detail.data} onDelete={() => del.mutate(selected)} pending={del.isPending} error={del.error?.message ?? null} />}
        </Card>
      </div>

      {showUpload && (
        <UploadBundleModal
          onClose={() => setShowUpload(false)}
          onUploaded={(d) => {
            qc.invalidateQueries({ queryKey: ["bundles"] });
            setSelected({ name: d.name, version: d.version });
            setShowUpload(false);
          }}
        />
      )}
    </div>
  );
}

function BundleManifestView({
  d,
  onDelete,
  pending,
  error,
}: {
  d: BundleDetail;
  onDelete: () => void;
  pending: boolean;
  error: string | null;
}) {
  const m = d.manifest;
  const pip = m.requirements?.pip ?? [];
  const apt = m.requirements?.apt ?? [];
  const creds = m.requirements?.credentials ?? [];
  const env = m.execution?.env ?? {};

  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-mono text-sm">
            <span className="font-semibold">{d.name}</span>
            <span className="text-muted">@{d.version}</span>
          </div>
          {d.description && (
            <div className="mt-1 text-xs text-muted">{d.description}</div>
          )}
        </div>
        <ActionButton
          tone="danger"
          onClick={() => {
            if (
              confirm(
                `删除任务包 ${d.name}@${d.version}？\n\n此操作不可撤销；已引用它的批次会拒绝删除。`,
              )
            ) {
              onDelete();
            }
          }}
          pending={pending}
          pendingLabel="删除中…"
        >
          删除
        </ActionButton>
      </div>
      {error && (
        <div className="rounded border border-rose-900 bg-rose-950/30 px-3 py-2 text-xs text-rose-400">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 border-t border-border pt-3 text-xs">
        <Field label="SHA256">
          <span className="font-mono" title={d.sha256}>{d.sha256.slice(0, 16)}…</span>
          <CopyButton value={d.sha256} title="复制完整 SHA256" />
        </Field>
        <Field label="大小"><span className="font-mono">{fmtBytes(d.size)}</span></Field>
        <Field label="入口"><span className="font-mono">{m.execution.entrypoint}</span></Field>
        <Field label="超时">
          {m.execution.timeout_sec ? `${m.execution.timeout_sec}s` : "默认"}
        </Field>
        <Field label="输出目录"><span className="font-mono">{m.outputs.watch_dir}</span></Field>
        <Field label="输出扩展名">
          {m.outputs.extensions?.length ? m.outputs.extensions.join(", ") : "全部"}
        </Field>
      </div>

      <Section title={`Python 依赖（pip · ${pip.length}）`}>
        {pip.length === 0 ? (
          <div className="text-xs text-muted">无</div>
        ) : (
          <ul className="space-y-0.5 font-mono text-xs">
            {pip.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </Section>

      {apt.length > 0 && (
        <Section title={`系统依赖（apt · ${apt.length}）`}>
          <ul className="space-y-0.5 font-mono text-xs">
            {apt.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Section>
      )}

      {Object.keys(env).length > 0 && (
        <Section title={`默认环境变量（${Object.keys(env).length}）`}>
          <table className="w-full font-mono text-xs">
            <tbody>
              {Object.entries(env).map(([k, v]) => (
                <tr key={k} className="border-t border-border/50">
                  <td className="py-1 pr-3 text-muted">{k}</td>
                  <td className="py-1 break-all">{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {creds.length > 0 && (
        <Section title={`所需凭证（${creds.length}）`}>
          <div className="flex flex-wrap gap-1.5">
            {creds.map((c) => (
              <Badge key={c} tone="info">{c}</Badge>
            ))}
          </div>
        </Section>
      )}

      <Section title="包内文件">
        <BundleFileBrowser name={d.name} version={d.version} />
      </Section>
    </div>
  );
}

function BundleFileBrowser({ name, version }: { name: string; version: string }) {
  const [sel, setSel] = useState<string>("manifest.yaml");
  const files = useQuery({
    queryKey: ["bundle-files", name, version],
    queryFn: () => API.bundleFiles(name, version),
  });
  const content = useQuery({
    queryKey: ["bundle-file", name, version, sel],
    queryFn: () => API.bundleFile(name, version, sel),
    enabled: !!sel,
  });

  if (files.isLoading) {
    return <div className="py-4 text-xs text-muted">加载文件列表…</div>;
  }
  if (files.isError) {
    return (
      <div className="rounded border border-rose-900 bg-rose-950/30 px-3 py-2 text-xs text-rose-400">
        无法列出文件：{(files.error as Error).message}
      </div>
    );
  }
  const rows = files.data ?? [];
  if (rows.length === 0) {
    return <div className="py-4 text-xs text-muted">（包为空）</div>;
  }

  return (
    <div className="grid grid-cols-[minmax(180px,280px)_1fr] gap-3">
      <ul className="max-h-[420px] overflow-auto rounded border border-border bg-bg/50 py-1">
        {rows.map((f: BundleFileEntry) => {
          const active = f.path === sel;
          const parts = f.path.split("/");
          const depth = parts.length - 1;
          const leaf = parts[parts.length - 1];
          const dir = parts.slice(0, -1).join("/");
          return (
            <li key={f.path}>
              <button
                onClick={() => setSel(f.path)}
                className={`flex w-full items-center justify-between px-2 py-1 text-left font-mono text-[11px] ${
                  active ? "bg-accent/20 text-text" : "text-muted hover:bg-bg"
                }`}
                title={f.path}
                style={{ paddingLeft: `${8 + depth * 14}px` }}
              >
                <span className="truncate">
                  {depth > 0 && (
                    <span className="mr-1 select-none text-muted/50">└</span>
                  )}
                  {leaf}
                  {dir && (
                    <span className="ml-2 text-[10px] text-muted/60">{dir}/</span>
                  )}
                </span>
                <span className="ml-2 shrink-0 text-[10px] text-muted">{fmtBytes(f.size)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="rounded border border-border bg-bg/50">
        {content.isLoading && (
          <div className="p-3 text-xs text-muted">加载 {sel}…</div>
        )}
        {content.isError && (
          <div className="p-3 text-xs text-rose-400">
            读取失败：{(content.error as Error).message}
          </div>
        )}
        {content.data && (
          <div>
            <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-[11px] text-muted">
              <span className="font-mono">{content.data.path}</span>
              <span className="flex gap-2">
                <span>{fmtBytes(content.data.size)}</span>
                {content.data.truncated && (
                  <span className="text-amber-400">已截断（512 KB 上限）</span>
                )}
              </span>
            </div>
            {content.data.binary ? (
              <div className="p-3 text-xs text-muted">
                二进制文件，无法预览。
              </div>
            ) : (
              <pre className="max-h-[400px] overflow-auto whitespace-pre p-3 font-mono text-[11px] leading-relaxed">
                {content.data.content}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border pt-3">
      <div className="mb-2 text-xs uppercase tracking-wide text-muted">{title}</div>
      {children}
    </div>
  );
}

function UploadBundleModal({
  onClose,
  onUploaded,
}: {
  onClose: () => void;
  onUploaded: (d: BundleDetail) => void;
}) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: () => API.uploadBundle(file!, description || undefined),
    onSuccess: (d) => {
      toast.success(`已上传 ${d.name}@${d.version}`);
      onUploaded(d);
    },
    onError: (e: Error) => {
      setErr(e.message);
      toast.error(`上传失败：${e.message}`);
    },
  });

  const dirty = !!file || description.trim() !== "";

  return (
    <Modal onClose={onClose} widthClass="w-[520px]" dirty={dirty}>
      <h2 className="mb-4 text-base font-semibold">上传任务包</h2>
      <div className="space-y-3 text-sm">
        <label className="block">
          <span className="text-xs text-muted">ZIP 文件（内含 manifest.yaml）</span>
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-xs"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted">描述（可选）</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简短说明这个 bundle 做什么"
            className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 outline-none focus:border-accent"
          />
        </label>
        {err && (
          <div className="rounded border border-rose-900 bg-rose-950/30 px-3 py-2 text-xs text-rose-400">
            {err}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <ActionButton onClick={onClose}>取消</ActionButton>
          <ActionButton
            tone="primary"
            onClick={() => {
              setErr(null);
              if (!file) {
                setErr("请先选择一个 ZIP 文件");
                return;
              }
              upload.mutate();
            }}
            pending={upload.isPending}
            pendingLabel="上传中…"
          >
            上传
          </ActionButton>
        </div>
      </div>
    </Modal>
  );
}
