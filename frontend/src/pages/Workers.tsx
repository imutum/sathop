import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API, WorkerInfo } from "../api";
import { Badge, Card, CopyButton, EmptyState, NodeLifecycleActions, PageHeader, ProgressBar, fmtGB, nodeStatusBadge } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";
import { IconWorkers } from "../icons";

export function Workers() {
  const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });
  const list = workers.data ?? [];
  // Deep-link target: /workers?id=<worker_id> scrolls + ring-highlights one
  // card. Used by leased_by cells in BatchDetail / Dashboard so investigating
  // "what's that worker doing" is one click instead of scan-the-list.
  const [params] = useSearchParams();
  const focusId = params.get("id");
  const focusedRef = useRef<HTMLDivElement | null>(null);
  // Scroll once per (focusId, list-loaded) so SSE refetches don't re-scroll.
  const lastScrolled = useRef<string | null>(null);
  useEffect(() => {
    if (!focusId || !focusedRef.current) return;
    if (lastScrolled.current === focusId) return;
    focusedRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    lastScrolled.current = focusId;
  }, [focusId, list]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="工作节点"
        description="集群内已注册的 Worker · 心跳 / 资源 / 队列"
      />

      {list.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconWorkers />}
            title="暂无已注册的工作节点"
            description="启动 worker 容器后会自动出现在此。"
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((w) => {
            const diskPct = w.disk_total_gb > 0 ? (w.disk_used_gb / w.disk_total_gb) * 100 : 0;
            let diskTone: "bad" | "warn" | "accent" = "accent";
            if (diskPct > 80) diskTone = "bad";
            else if (diskPct > 60) diskTone = "warn";
            const isFocused = focusId === w.worker_id;
            return (
              <div
                key={w.worker_id}
                ref={isFocused ? focusedRef : undefined}
                className={isFocused ? "rounded-2xl ring-2 ring-accent/60 ring-offset-2 ring-offset-bg" : undefined}
              >
              <Card padded={false}>
                <div className="flex items-start justify-between gap-2 border-b border-border/60 px-5 py-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1 font-mono text-[13px] font-semibold">
                      <span className="truncate">{w.worker_id}</span>
                      <CopyButton value={w.worker_id} title="复制节点 ID" />
                    </div>
                    <div
                      className="mt-0.5 truncate font-mono text-[11px] text-muted"
                      title={w.public_url ?? ""}
                    >
                      {w.public_url ?? "—"}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {w.paused && (
                      <span title={`worker 已自我暂停 — 当前磁盘 ${diskPct.toFixed(0)}%，等待降到恢复阈值再领新任务`}>
                        <Badge tone="warn">已暂停</Badge>
                      </span>
                    )}
                    {(() => {
                      const { tone, label } = nodeStatusBadge(w.enabled, w.last_seen);
                      return <Badge tone={tone} dot>{label}</Badge>;
                    })()}
                  </div>
                </div>

                <div className="space-y-4 px-5 py-4">
                  <MetricGrid>
                    <Metric label="CPU" value={`${w.cpu_percent.toFixed(0)}%`} />
                    <Metric label="内存" value={`${w.mem_percent.toFixed(0)}%`} />
                    <Metric label="月出站" value={fmtGB(w.monthly_egress_gb)} />
                  </MetricGrid>

                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-[11px] text-muted">
                      <span className="font-medium uppercase tracking-[0.10em]">磁盘</span>
                      <span className="tabular-nums">
                        {fmtGB(w.disk_used_gb)} / {fmtGB(w.disk_total_gb)}
                      </span>
                    </div>
                    <ProgressBar value={w.disk_used_gb} max={w.disk_total_gb} tone={diskTone} />
                  </div>

                  <div className="grid grid-cols-3 gap-3 rounded-xl border border-border bg-subtle/60 p-3 text-center">
                    <QueueCell label="下载" value={w.queue_downloading} />
                    <QueueCell label="处理" value={w.queue_processing} />
                    <QueueCell label="上传" value={w.queue_uploading} />
                  </div>

                  <div className="flex items-center justify-between border-t border-border/60 pt-3 text-[11px] text-muted">
                    <CapacityEditor worker={w} />
                    <div className="flex items-center gap-3">
                      <EnableToggle worker={w} />
                      <span>心跳 {fmtAge(w.last_seen)}</span>
                    </div>
                  </div>
                </div>
              </Card>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetricGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-3 gap-3">{children}</div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10.5px] font-medium uppercase tracking-[0.10em] text-muted">
        {label}
      </div>
      <div className="font-display mt-0.5 text-[15px] font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function QueueCell({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[10.5px] font-medium uppercase tracking-[0.10em] text-muted">
        {label}
      </div>
      <div className="font-display mt-0.5 text-base font-semibold tabular-nums text-text">
        {value}
      </div>
    </div>
  );
}

function EnableToggle({ worker }: { worker: WorkerInfo }) {
  const qc = useQueryClient();
  const toast = useToast();
  const enable = useMutation({
    mutationFn: (next: boolean) => API.setWorkerEnabled(worker.worker_id, next),
    onSuccess: (_r, next) => {
      qc.invalidateQueries({ queryKey: ["workers"] });
      toast.success(next ? "已启用" : "已禁用，已在手任务排空后停止接新单");
    },
    onError: (e: Error) => toast.error(`失败：${e.message}`),
  });
  const forget = useMutation({
    mutationFn: () => API.forgetWorker(worker.worker_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workers"] });
      toast.success(`已删除节点 ${worker.worker_id}`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });
  return (
    <NodeLifecycleActions
      enabled={worker.enabled}
      pending={enable.isPending || forget.isPending}
      onSetEnabled={enable.mutate}
      onForget={forget.mutate}
      disableConfirm={`禁用 worker ${worker.worker_id}？\n\n已 lease 的任务继续完成；不会再领新任务。`}
      forgetConfirm={`从注册表中移除 ${worker.worker_id}？\n\n仅删除元数据；如果它仍持有任务会被服务端拒绝。`}
      disableTitle="禁用此节点（在手任务继续）"
      forgetTitle="永久从注册表中删除（仅在已禁用且无任务时允许）"
    />
  );
}

function CapacityEditor({ worker }: { worker: WorkerInfo }) {
  const qc = useQueryClient();
  const toast = useToast();
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
            className="w-14 rounded-md border border-border bg-bg px-1.5 py-0.5 text-[11px] tabular-nums outline-none focus:border-accent"
          />
          <button
            onClick={submit}
            disabled={m.isPending}
            className="rounded-md bg-accent/15 px-1.5 py-0.5 text-[10.5px] font-medium text-accent hover:bg-accent/25 disabled:opacity-50"
          >
            保存
          </button>
          <button
            onClick={() => setDraft(null)}
            disabled={m.isPending}
            className="text-[10.5px] text-muted hover:text-text"
          >
            取消
          </button>
        </>
      ) : (
        <button
          onClick={startEdit}
          className="rounded-md border border-border bg-surface px-1.5 py-0.5 text-[10.5px] text-muted transition hover:border-accent/40 hover:text-text"
          title="改实际并发上限（不超过容器启动设置的容量）"
        >
          {worker.desired_capacity != null ? "改" : "限流"}
        </button>
      )}
    </span>
  );
}
