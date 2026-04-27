import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { API, WorkerInfo } from "../api";
import { Badge, Card, CopyButton, ProgressBar, fmtGB } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";

function onlineBadge(lastSeenISO: string) {
  const sec = (Date.now() - new Date(lastSeenISO).getTime()) / 1000;
  if (sec < 60) return <Badge tone="acked">在线</Badge>;
  if (sec < 300) return <Badge tone="warn">待机</Badge>;
  return <Badge tone="error">离线</Badge>;
}

export function Workers() {
  const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">工作节点</h1>
      {(workers.data ?? []).length === 0 && (
        <Card>
          <div className="py-8 text-center text-sm text-muted">暂无已注册的工作节点。</div>
        </Card>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(workers.data ?? []).map((w) => {
          const diskPct = w.disk_total_gb > 0 ? (w.disk_used_gb / w.disk_total_gb) * 100 : 0;
          let diskTone: "bad" | "warn" | "accent" = "accent";
          if (diskPct > 80) diskTone = "bad";
          else if (diskPct > 60) diskTone = "warn";
          return (
            <Card key={w.worker_id}>
              <div className="mb-3 flex items-center justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-1 font-mono text-sm font-semibold">
                    <span className="truncate">{w.worker_id}</span>
                    <CopyButton value={w.worker_id} title="复制节点 ID" />
                  </div>
                  <div className="truncate font-mono text-xs text-muted" title={w.public_url ?? ""}>
                    {w.public_url ?? "—"}
                  </div>
                </div>
                {onlineBadge(w.last_seen)}
              </div>

              <div className="grid grid-cols-3 gap-3 text-xs">
                <div>
                  <div className="text-muted">CPU</div>
                  <div className="text-sm tabular-nums">{w.cpu_percent.toFixed(0)}%</div>
                </div>
                <div>
                  <div className="text-muted">内存</div>
                  <div className="text-sm tabular-nums">{w.mem_percent.toFixed(0)}%</div>
                </div>
                <div>
                  <div className="text-muted">月出站</div>
                  <div className="text-sm tabular-nums">{fmtGB(w.monthly_egress_gb)}</div>
                </div>
              </div>

              <div className="mt-3 text-xs">
                <div className="mb-1 flex items-center justify-between text-muted">
                  <span>磁盘</span>
                  <span>
                    {fmtGB(w.disk_used_gb)} / {fmtGB(w.disk_total_gb)}
                  </span>
                </div>
                <ProgressBar
                  value={w.disk_used_gb}
                  max={w.disk_total_gb}
                  tone={diskTone}
                />
              </div>

              <div className="mt-3 grid grid-cols-3 gap-3 rounded bg-bg p-2 text-center text-xs">
                <div>
                  <div className="text-muted">下载</div>
                  <div className="text-sm font-semibold">{w.queue_downloading}</div>
                </div>
                <div>
                  <div className="text-muted">处理</div>
                  <div className="text-sm font-semibold">{w.queue_processing}</div>
                </div>
                <div>
                  <div className="text-muted">上传</div>
                  <div className="text-sm font-semibold">{w.queue_uploading}</div>
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between text-xs text-muted">
                <CapacityEditor worker={w} />
                <span>心跳 {fmtAge(w.last_seen)}</span>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function CapacityEditor({ worker }: { worker: WorkerInfo }) {
  const qc = useQueryClient();
  const toast = useToast();
  // null ⇒ not editing; the displayed value derives from props every render.
  const [draft, setDraft] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: (n: number | null) => API.setWorkerCapacity(worker.worker_id, n),
    onSuccess: (_r, n) => {
      qc.invalidateQueries({ queryKey: ["workers"] });
      toast.success(n == null ? "已清除并发上限" : `已设并发上限 ${n}`);
      setDraft(null);
    },
    onError: (e: Error) => toast.error(`设置失败：${e.message}`),
  });

  const submit = () => {
    const t = (draft ?? "").trim();
    if (t === "") return m.mutate(null);
    const n = Number(t);
    if (!Number.isInteger(n) || n < 1 || n > worker.capacity) {
      toast.error(`并发上限必须是 1–${worker.capacity} 的整数`);
      return;
    }
    m.mutate(n);
  };

  const effective = Math.min(worker.capacity, worker.desired_capacity ?? worker.capacity);
  const startEdit = () =>
    setDraft(worker.desired_capacity != null ? String(worker.desired_capacity) : "");

  return (
    <span className="flex items-center gap-1.5">
      <span>容量 {effective}/{worker.capacity}</span>
      {draft !== null ? (
        <>
          <input
            type="number"
            min={1}
            max={worker.capacity}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") setDraft(null);
            }}
            autoFocus
            disabled={m.isPending}
            placeholder="env"
            className="w-14 rounded border border-border bg-bg px-1.5 py-0.5 text-xs tabular-nums"
          />
          <button
            onClick={submit}
            disabled={m.isPending}
            className="rounded bg-accent/20 px-1.5 py-0.5 text-[11px] text-accent hover:bg-accent/40 disabled:opacity-50"
          >
            保存
          </button>
          <button
            onClick={() => setDraft(null)}
            disabled={m.isPending}
            className="text-[11px] text-muted hover:text-text"
          >
            取消
          </button>
        </>
      ) : (
        <button
          onClick={startEdit}
          className="text-[11px] text-muted hover:text-text"
          title="改实际并发上限（不超过容器启动设置的容量）"
        >
          {worker.desired_capacity != null ? "改" : "限流"}
        </button>
      )}
    </span>
  );
}
