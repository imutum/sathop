import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { API, SharedFileInfo } from "../api";
import { ActionButton, Card, CopyButton, Modal } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// Matches orchestrator's _NAME_RE. Keep client-side check identical so users
// see the rule up front rather than eating a 400 after upload.
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">共享文件</h1>
          <p className="mt-1 text-xs text-muted">
            被任务包通过 <code className="font-mono">shared_files</code> 引用的文件，
            Worker 按需拉取到 <code className="font-mono">$SATHOP_SHARED_DIR</code>。
          </p>
        </div>
        <ActionButton tone="primary" onClick={() => setShowUpload(true)}>
          上传文件
        </ActionButton>
      </div>

      <Card>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2">名称</th>
              <th className="pb-2">大小</th>
              <th className="pb-2">SHA256</th>
              <th className="pb-2">描述</th>
              <th className="pb-2">上传时间</th>
              <th className="pb-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.name} className="border-t border-border">
                <td className="py-2 pr-3 font-mono text-xs">{f.name}</td>
                <td className="py-2 pr-3 text-xs text-muted tabular-nums">
                  {fmtBytes(f.size)}
                </td>
                <td className="py-2 pr-3 text-xs">
                  <span className="font-mono" title={f.sha256}>
                    {f.sha256.slice(0, 12)}…
                  </span>
                  <CopyButton value={f.sha256} title="复制完整 SHA256" />
                </td>
                <td className="py-2 pr-3 text-xs text-muted">
                  {f.description || <span className="text-muted/50">—</span>}
                </td>
                <td className="py-2 pr-3 text-xs text-muted">{fmtAge(f.uploaded_at)}</td>
                <td className="py-2 pr-3 text-right">
                  <div className="inline-flex gap-2">
                    <ActionButton onClick={() => setReplaceTarget(f)}>替换</ActionButton>
                    <ActionButton
                      tone="danger"
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
            {rows.length === 0 && !list.isLoading && (
              <tr>
                <td colSpan={6} className="py-10 text-center text-sm text-muted">
                  还没有共享文件。点击上方"上传文件"添加第一个。
                </td>
              </tr>
            )}
          </tbody>
        </table>
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
  const inputRef = useRef<HTMLInputElement>(null);

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
      <h2 className="mb-4 text-base font-semibold">
        {lockName ? `替换 ${lockName}` : "上传共享文件"}
      </h2>
      <div className="space-y-3 text-sm">
        <label className="block">
          <span className="text-xs text-muted">
            名称 <span className="text-muted/70">（任务包在 manifest.shared_files 里引用的字符串）</span>
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!!lockName}
            placeholder="mask.tif"
            className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 font-mono text-xs outline-none focus:border-accent disabled:opacity-60"
          />
          <div className="mt-1 text-[10px] text-muted/70">
            允许字符：字母、数字、<code>.</code> <code>_</code> <code>-</code>；不能以点开头；最长 255 字节。
          </div>
        </label>
        <label className="block">
          <span className="text-xs text-muted">文件</span>
          <input
            ref={inputRef}
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              // Prefill name from the file picked, unless we're locked to replace
              if (f && !lockName && !name) setName(f.name);
            }}
            className="mt-1 block w-full text-xs"
          />
          {file && (
            <div className="mt-1 text-[10px] text-muted">
              已选：<span className="font-mono">{file.name}</span> · {fmtBytes(file.size)}
            </div>
          )}
        </label>
        <label className="block">
          <span className="text-xs text-muted">描述（可选）</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简短说明这个文件是什么"
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
