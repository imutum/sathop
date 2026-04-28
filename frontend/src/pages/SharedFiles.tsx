import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { API, SharedFileInfo } from "../api";
import { ActionButton, Alert, Card, CopyButton, EmptyState, FieldLabel, Modal, PageHeader, fmtBytes } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";
import { IconShared, IconUpload } from "../icons";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/;

export function SharedFiles() {
  const qc = useQueryClient();
  const toast = useToast();
  const [showUpload, setShowUpload] = useState(false);
  const [replaceTarget, setReplaceTarget] = useState<SharedFileInfo | null>(null);

  const list = useQuery({
    queryKey: ["shared-files"],
    queryFn: API.sharedFiles,
  });

  const del = useMutation({
    mutationFn: (name: string) => API.deleteSharedFile(name),
    onSuccess: (_r, name) => {
      qc.invalidateQueries({ queryKey: ["shared-files"] });
      toast.success(`已删除 ${name}`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const rows = list.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="共享文件"
        description={
          <>
            被任务包通过 <code className="rounded bg-subtle px-1.5 py-0.5 font-mono text-[11px]">shared_files</code> 引用的辅助资源，
            Worker 按需拉取到 <code className="rounded bg-subtle px-1.5 py-0.5 font-mono text-[11px]">$SATHOP_SHARED_DIR</code>。
          </>
        }
        actions={
          <ActionButton tone="primary" onClick={() => setShowUpload(true)}>
            <IconUpload width={13} height={13} />
            上传文件
          </ActionButton>
        }
      />

      <Card padded={false}>
        {rows.length === 0 && !list.isLoading ? (
          <EmptyState
            icon={<IconShared />}
            title="还没有共享文件"
            description='点击上方"上传文件"添加第一个。'
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
                <tr>
                  <th className="px-5 py-3">名称</th>
                  <th className="px-2 py-3">大小</th>
                  <th className="px-2 py-3">SHA256</th>
                  <th className="px-2 py-3">描述</th>
                  <th className="px-2 py-3">上传</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((f) => (
                  <tr key={f.name} className="border-t border-border/60 transition hover:bg-subtle/40">
                    <td className="px-5 py-3 font-mono text-[12px] font-medium">{f.name}</td>
                    <td className="px-2 py-3 text-[11.5px] text-muted tabular-nums">
                      {fmtBytes(f.size)}
                    </td>
                    <td className="px-2 py-3 text-[11.5px]">
                      <span className="font-mono" title={f.sha256}>
                        {f.sha256.slice(0, 12)}…
                      </span>
                      <CopyButton value={f.sha256} title="复制完整 SHA256" />
                    </td>
                    <td className="px-2 py-3 text-[11.5px] text-muted">
                      {f.description || <span className="text-muted/50">—</span>}
                    </td>
                    <td className="px-2 py-3 text-[11.5px] text-muted">{fmtAge(f.uploaded_at)}</td>
                    <td className="px-5 py-3 text-right">
                      <div className="inline-flex gap-1.5">
                        <ActionButton size="sm" onClick={() => setReplaceTarget(f)}>
                          替换
                        </ActionButton>
                        <ActionButton
                          tone="danger"
                          size="sm"
                          pending={del.isPending && del.variables === f.name}
                          pendingLabel="删除中…"
                          onClick={() => {
                            if (
                              confirm(
                                `删除共享文件 ${f.name}？\n\n若仍被某个任务包的 shared_files 引用，将返回 409。`,
                              )
                            ) {
                              del.mutate(f.name);
                            }
                          }}
                        >
                          删除
                        </ActionButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showUpload && (
        <UploadSharedModal
          onClose={() => setShowUpload(false)}
          onUploaded={() => {
            qc.invalidateQueries({ queryKey: ["shared-files"] });
            setShowUpload(false);
          }}
        />
      )}

      {replaceTarget && (
        <UploadSharedModal
          lockName={replaceTarget.name}
          currentDescription={replaceTarget.description ?? ""}
          onClose={() => setReplaceTarget(null)}
          onUploaded={() => {
            qc.invalidateQueries({ queryKey: ["shared-files"] });
            setReplaceTarget(null);
          }}
        />
      )}
    </div>
  );
}

function UploadSharedModal({
  onClose,
  onUploaded,
  lockName,
  currentDescription = "",
}: {
  onClose: () => void;
  onUploaded: (d: SharedFileInfo) => void;
  lockName?: string;
  currentDescription?: string;
}) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState(lockName ?? "");
  const [description, setDescription] = useState(currentDescription);
  const [err, setErr] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => API.uploadSharedFile(name, file!, description || undefined),
    onSuccess: (d) => {
      toast.success(lockName ? `已替换 ${d.name}` : `已上传 ${d.name}`);
      onUploaded(d);
    },
    onError: (e: Error) => {
      setErr(e.message);
      toast.error(`上传失败：${e.message}`);
    },
  });

  const dirty = !!file || name !== (lockName ?? "") || description !== currentDescription;

  return (
    <Modal onClose={onClose} widthClass="w-[520px]" dirty={dirty}>
      <h2 className="font-display mb-5 text-lg font-semibold tracking-tight">
        {lockName ? `替换 ${lockName}` : "上传共享文件"}
      </h2>
      <div className="space-y-4 text-sm">
        <label className="block">
          <FieldLabel>名称</FieldLabel>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!!lockName}
            placeholder="mask.tif"
            className="mt-2 w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-xs outline-none transition hover:border-accent/40 focus:border-accent disabled:opacity-60"
          />
          <div className="mt-1.5 text-[10.5px] text-muted/80">
            允许字符：字母、数字、<code>.</code> <code>_</code> <code>-</code>；不能以点开头；最长 255 字节。
          </div>
        </label>
        <label className="block">
          <FieldLabel>文件</FieldLabel>
          <input
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f && !lockName && !name) setName(f.name);
            }}
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
            placeholder="简短说明这个文件是什么"
            className="mt-2 w-full rounded-lg border border-border bg-bg px-3 py-2 outline-none transition hover:border-accent/40 focus:border-accent"
          />
        </label>
        {err && <Alert>{err}</Alert>}
        <div className="flex justify-end gap-2 pt-2">
          <ActionButton onClick={onClose}>取消</ActionButton>
          <ActionButton
            tone="primary"
            onClick={() => {
              setErr(null);
              if (!file) return setErr("请先选择文件");
              if (!name) return setErr("请填写名称");
              if (!NAME_RE.test(name))
                return setErr(
                  "名称不合法：仅允许字母数字和 . _ -，不能以点开头，最长 255 字节。",
                );
              upload.mutate();
            }}
            pending={upload.isPending}
            pendingLabel="上传中…"
          >
            {lockName ? "替换" : "上传"}
          </ActionButton>
        </div>
      </div>
    </Modal>
  );
}
