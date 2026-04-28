import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { API, BundleDetail, BundleFileEntry, BundleSummary } from "../api";
import { ActionButton, Alert, Badge, Card, CopyButton, EmptyState, Field, FieldLabel, Modal, PageHeader, fmtBytes } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";
import { IconArrowRight, IconBundles, IconDownload, IconTrash, IconUpload } from "../icons";

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

  useEffect(() => {
    const n = search.get("name");
    const v = search.get("version");
    if (n && v && (selected?.name !== n || selected?.version !== v)) {
      setSelected({ name: n, version: v });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const list = useQuery({ queryKey: ["bundles"], queryFn: API.bundles });
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
      <PageHeader
        title="任务包"
        description="用户脚本注册表 · 批次通过 orch:<name>@<version> 引用"
        actions={
          <ActionButton tone="primary" onClick={() => setShowUpload(true)}>
            <IconUpload width={13} height={13} />
            上传 ZIP
          </ActionButton>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card padded={false}>
          {rows.length === 0 ? (
            <EmptyState
              icon={<IconBundles />}
              title="还没有任务包"
              description='点击上方"上传 ZIP"开始添加。'
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
                  <tr>
                    <th className="px-5 py-3">名称</th>
                    <th className="px-2 py-3">版本</th>
                    <th className="px-2 py-3">大小</th>
                    <th className="px-2 py-3" title="引用此包的批次数">引用</th>
                    <th className="px-5 py-3">上传</th>
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
                        className={`cursor-pointer border-t border-border/60 transition ${
                          isActive
                            ? "bg-accent-soft/60"
                            : "hover:bg-subtle/50"
                        }`}
                      >
                        <td className="px-5 py-2.5 font-mono text-[12px] font-medium">{b.name}</td>
                        <td className="px-2 py-2.5">
                          <Badge tone="info">{b.version}</Badge>
                        </td>
                        <td className="px-2 py-2.5 text-[11.5px] text-muted tabular-nums">{fmtBytes(b.size)}</td>
                        <td className="px-2 py-2.5 text-[11.5px] tabular-nums">
                          {b.in_use_count > 0 ? (
                            <span className="font-medium text-text">{b.in_use_count}</span>
                          ) : (
                            <span className="text-muted/60">0</span>
                          )}
                        </td>
                        <td className="px-5 py-2.5 text-[11.5px] text-muted">{fmtAge(b.uploaded_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          {!selected && (
            <EmptyState
              icon={<IconBundles />}
              title="未选择任务包"
              description="选择左侧任意任务包查看清单 / 文件浏览。"
            />
          )}
          {selected && detail.isLoading && (
            <div className="py-8 text-center text-sm text-muted">加载中…</div>
          )}
          {selected && detail.data && (
            <BundleManifestView
              d={detail.data}
              onDelete={() => del.mutate(selected)}
              pending={del.isPending}
              error={del.error?.message ?? null}
            />
          )}
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
    <div className="space-y-5 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="font-mono text-[14px]">
              <span className="font-semibold">{d.name}</span>
              <span className="text-muted">@{d.version}</span>
            </div>
            {d.in_use_count > 0 && (
              <span title="被批次引用 — 删除会被拒绝">
                <Badge tone="info">{d.in_use_count} 批次引用中</Badge>
              </span>
            )}
          </div>
          {d.description && (
            <div className="mt-1.5 text-xs text-muted">{d.description}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <CreateBatchWithBundleButton name={d.name} version={d.version} />
          <DownloadButton name={d.name} version={d.version} />
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
            <IconTrash width={13} height={13} />
            删除
          </ActionButton>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}

      <div className="grid grid-cols-2 gap-4 rounded-xl border border-border bg-subtle/40 p-4 text-xs sm:grid-cols-3">
        <Field label="SHA256">
          <span className="font-mono" title={d.sha256}>{d.sha256.slice(0, 16)}…</span>
          <CopyButton value={d.sha256} title="复制完整 SHA256" />
        </Field>
        <Field label="大小"><span className="font-mono tabular-nums">{fmtBytes(d.size)}</span></Field>
        <Field label="入口"><span className="break-all font-mono">{m.execution.entrypoint}</span></Field>
        <Field label="超时">
          {m.execution.timeout_sec ? `${m.execution.timeout_sec}s` : "默认"}
        </Field>
        <Field label="输出目录"><span className="font-mono">{m.outputs.watch_dir}</span></Field>
        <Field label="输出扩展名">
          {m.outputs.extensions?.length ? m.outputs.extensions.join(", ") : "全部"}
        </Field>
      </div>

      <Section title={`Python 依赖 · pip`} count={pip.length}>
        {pip.length === 0 ? (
          <div className="text-xs text-muted">无</div>
        ) : (
          <ul className="space-y-0.5 font-mono text-[11.5px]">
            {pip.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
      </Section>

      {apt.length > 0 && (
        <Section title="系统依赖 · apt" count={apt.length}>
          <ul className="space-y-0.5 font-mono text-[11.5px]">
            {apt.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </Section>
      )}

      {Object.keys(env).length > 0 && (
        <Section title="默认环境变量" count={Object.keys(env).length}>
          <table className="w-full font-mono text-[11.5px]">
            <tbody>
              {Object.entries(env).map(([k, v]) => (
                <tr key={k} className="border-t border-border/50">
                  <td className="py-1.5 pr-3 text-muted">{k}</td>
                  <td className="break-all py-1.5">{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {creds.length > 0 && (
        <Section title="所需凭证" count={creds.length}>
          <div className="flex flex-wrap gap-1.5">
            {creds.map((c) => <Badge key={c} tone="info">{c}</Badge>)}
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
    return <Alert>无法列出文件：{(files.error as Error).message}</Alert>;
  }
  const rows = files.data ?? [];
  if (rows.length === 0) {
    return <div className="py-4 text-xs text-muted">（包为空）</div>;
  }

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(180px,280px)_1fr]">
      <ul className="max-h-[420px] overflow-auto rounded-xl border border-border bg-subtle/40 py-1">
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
                className={`flex w-full items-center justify-between px-2 py-1 text-left font-mono text-[11px] transition ${
                  active
                    ? "bg-accent-soft text-accent"
                    : "text-muted hover:bg-subtle hover:text-text"
                }`}
                title={f.path}
                style={{ paddingLeft: `${8 + depth * 14}px` }}
              >
                <span className="truncate">
                  {depth > 0 && <span className="mr-1 select-none text-muted/50">└</span>}
                  {leaf}
                  {dir && <span className="ml-2 text-[10px] text-muted/60">{dir}/</span>}
                </span>
                <span className="ml-2 shrink-0 text-[10px] text-muted">{fmtBytes(f.size)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="rounded-xl border border-border bg-subtle/30">
        {content.isLoading && (
          <div className="p-3 text-xs text-muted">加载 {sel}…</div>
        )}
        {content.isError && (
          <div className="p-3 text-xs text-danger">
            读取失败：{(content.error as Error).message}
          </div>
        )}
        {content.data && (
          <div>
            <div className="flex items-center justify-between border-b border-border px-3 py-2 text-[11px] text-muted">
              <span className="font-mono">{content.data.path}</span>
              <span className="flex gap-2">
                <span className="tabular-nums">{fmtBytes(content.data.size)}</span>
                {content.data.truncated && (
                  <span className="text-warning">已截断（512 KB 上限）</span>
                )}
              </span>
            </div>
            {content.data.binary ? (
              <div className="p-3 text-xs text-muted">二进制文件，无法预览。</div>
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

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border/60 pt-4">
      <div className="mb-2.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted">
        <span>{title}</span>
        {count !== undefined && (
          <span className="rounded-full bg-subtle px-1.5 py-px text-[10px] tabular-nums text-muted">
            {count}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function CreateBatchWithBundleButton({ name, version }: { name: string; version: string }) {
  const navigate = useNavigate();
  return (
    <ActionButton
      tone="primary"
      onClick={() => navigate(`/batches?bundle=${encodeURIComponent(`${name}@${version}`)}`)}
      title="跳转到批次页并预选此任务包"
    >
      新建批次
      <IconArrowRight width={13} height={13} />
    </ActionButton>
  );
}

function DownloadButton({ name, version }: { name: string; version: string }) {
  const toast = useToast();
  const [pending, setPending] = useState(false);
  const onClick = async () => {
    setPending(true);
    try {
      await API.downloadBundle(name, version);
    } catch (e) {
      toast.error(`下载失败：${(e as Error).message}`);
    } finally {
      setPending(false);
    }
  };
  return (
    <ActionButton onClick={onClick} pending={pending} pendingLabel="下载中…" title="下载原始 ZIP 包">
      <IconDownload width={13} height={13} />
      下载
    </ActionButton>
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
      <h2 className="font-display mb-5 text-lg font-semibold tracking-tight">上传任务包</h2>
      <div className="space-y-4 text-sm">
        <label className="block">
          <FieldLabel>ZIP 文件 · 内含 manifest.yaml</FieldLabel>
          <input
            type="file"
            accept=".zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-2 block w-full cursor-pointer rounded-lg border border-dashed border-border bg-subtle/40 px-3 py-3 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-accent-fg hover:border-accent/40"
          />
          {file && (
            <div className="mt-1.5 text-[10.5px] text-muted">
              已选：<span className="font-mono">{file.name}</span> · {fmtBytes(file.size)}
            </div>
          )}
        </label>
        <label className="block">
          <FieldLabel>描述（可选）</FieldLabel>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简短说明这个 bundle 做什么"
            className="mt-2 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none transition hover:border-accent/40 focus:border-accent"
          />
        </label>
        {err && <Alert>{err}</Alert>}
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
