import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  API,
  EventRow,
  GranuleRow,
  GranuleState,
  ProgressRow,
  StageStats,
  TimingRow,
  TimingStage,
} from "../api";
import { ActionButton, Badge, Card, CopyButton } from "../ui";
import { TIMING_STAGE_ZH, fmtAge, fmtMs, levelLabel, stateLabel } from "../i18n";
import { useToast } from "../toast";

const STATE_FILTERS: { key: GranuleState | "all"; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "pending", label: "待处理" },
  { key: "downloading", label: "下载中" },
  { key: "processing", label: "处理中" },
  { key: "uploaded", label: "已上传" },
  { key: "acked", label: "已确认" },
  { key: "deleted", label: "已清理" },
  { key: "failed", label: "失败" },
  { key: "blacklisted", label: "已拉黑" },
];

const CANCELLABLE = new Set<GranuleState>([
  "pending", "downloading", "downloaded", "processing", "processed",
]);
const RETRYABLE = new Set<GranuleState>(["failed", "blacklisted"]);

// Worker emits `download:<filename>`; bundles emit anything else verbatim.
const formatStep = (step: string): string =>
  step.startsWith("download:") ? `下载 ${step.slice(9)}` : step;

// Server stores granule_id as `<batch_id>:<user_gid>` so user-supplied IDs only
// have to be unique per batch. In this batch-scoped view we strip the prefix
// for display; comparisons/mutations keep the full form.
const stripBatchPrefix = (gid: string, batchId: string): string =>
  gid.startsWith(`${batchId}:`) ? gid.slice(batchId.length + 1) : gid;

const STAGE_ORDER: TimingStage[] = ["download", "process", "upload"];

export function BatchDetail() {
  const { batchId = "" } = useParams();
  const [search] = useSearchParams();
  const highlight = search.get("granule");
  const qc = useQueryClient();
  const [filter, setFilter] = useState<(GranuleState | "all")>("all");
  const [logLevel, setLogLevel] = useState<"all" | "warn" | "error">("all");
  const highlightedRef = useRef<HTMLTableRowElement | null>(null);

  const batch = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => API.batch(batchId),
    enabled: !!batchId,
  });

  const granules = useQuery({
    queryKey: ["granules", batchId, filter],
    queryFn: () => API.granules(batchId, filter === "all" ? undefined : filter),
    enabled: !!batchId,
  });

  const events = useQuery({
    queryKey: ["batch-events", batchId, logLevel],
    queryFn: () => API.batchEvents(batchId, logLevel === "all" ? undefined : logLevel, 200),
    enabled: !!batchId,
  });

  const latestProgress = useQuery({
    queryKey: ["batch-progress-latest", batchId],
    queryFn: () => API.batchProgressLatest(batchId),
    enabled: !!batchId,
  });

  const [expanded, setExpanded] = useState<string | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["granules", batchId] });
    qc.invalidateQueries({ queryKey: ["batch", batchId] });
    qc.invalidateQueries({ queryKey: ["batches"] });
  };

  const toast = useToast();
  const cancel = useMutation({
    mutationFn: (g: string) => API.cancelGranule(batchId, g),
    onSuccess: (_r, g) => {
      invalidate();
      toast.success(`已取消数据粒 ${g}`);
    },
    onError: (e: Error, g) => toast.error(`取消 ${g} 失败：${e.message}`),
  });
  const retry = useMutation({
    mutationFn: (g: string) => API.retryGranule(batchId, g),
    onSuccess: (_r, g) => {
      invalidate();
      toast.success(`已重试数据粒 ${g}`);
    },
    onError: (e: Error, g) => toast.error(`重试 ${g} 失败：${e.message}`),
  });

  useEffect(() => {
    if (highlight && highlightedRef.current) {
      highlightedRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlight, granules.data]);

  if (!batchId) return null;

  const b = batch.data;
  const rows = granules.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-3">
        <Link to="/batches" className="text-sm text-muted hover:text-text">
          ← 批次列表
        </Link>
        <h1 className="text-xl font-semibold">{b?.name ?? batchId}</h1>
        <span className="font-mono text-xs text-muted">
          {batchId}
          <CopyButton value={batchId} title="复制批次 ID" />
        </span>
      </div>

      {b && (
        <Card>
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wide text-muted">处理包</div>
              <div className="mt-1 break-all font-mono text-xs">{b.bundle_ref}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-muted">目标接收端</div>
              <div className="mt-1">
                <Badge tone="info">{b.target_receiver_id ?? "任意"}</Badge>
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-muted">创建时间</div>
              <div className="mt-1 text-xs">{fmtAge(b.created_at)}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-muted">状态</div>
              <div className="mt-1 text-xs">{b.status}</div>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
            {Object.entries(b.counts).map(([state, n]) => (
              <Badge key={state} tone={state}>
                {stateLabel(state as GranuleState)}：{n}
              </Badge>
            ))}
          </div>
        </Card>
      )}

      <Card
        title="数据粒"
        action={
          <div className="flex flex-wrap gap-1">
            {STATE_FILTERS.map((f) => {
              const count =
                f.key === "all"
                  ? Object.values(b?.counts ?? {}).reduce((s, n) => s + (n ?? 0), 0)
                  : (b?.counts?.[f.key as GranuleState] ?? 0);
              const dim = count === 0 && f.key !== "all";
              return (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={`rounded px-2 py-1 text-xs tabular-nums ${
                    filter === f.key
                      ? "bg-bg text-text"
                      : dim
                      ? "text-muted/40 hover:text-muted"
                      : "text-muted hover:bg-bg hover:text-text"
                  }`}
                >
                  {f.label} <span className="text-muted">({count})</span>
                </button>
              );
            })}
          </div>
        }
      >
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2">数据粒</th>
              <th className="pb-2">状态</th>
              <th className="pb-2">重试次数</th>
              <th className="pb-2">领取方</th>
              <th className="pb-2">更新时间</th>
              <th className="pb-2">错误</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g: GranuleRow) => {
              const latest = latestProgress.data?.[g.granule_id];
              const isOpen = expanded === g.granule_id;
              return (
                <Fragment key={g.granule_id}>
                  <tr
                    key={g.granule_id}
                    ref={g.granule_id === highlight ? highlightedRef : undefined}
                    className={`border-t border-border align-top ${
                      g.granule_id === highlight ? "bg-accent/10" : ""
                    }`}
                  >
                    <td className="py-2 pr-4 font-mono text-xs">
                      <button
                        onClick={() => setExpanded(isOpen ? null : g.granule_id)}
                        className="mr-1 inline-block w-3 text-muted hover:text-text"
                        title={isOpen ? "收起进度" : "展开进度"}
                      >
                        {isOpen ? "▾" : "▸"}
                      </button>
                      {stripBatchPrefix(g.granule_id, batchId)}
                      {latest && (
                        <div className="mt-0.5 ml-4 text-[11px] text-muted">
                          ▸ {formatStep(latest.step)}
                          {latest.pct != null ? ` · ${latest.pct.toFixed(0)}%` : ""}
                          {latest.detail ? ` · ${latest.detail}` : ""}
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge tone={g.state}>{stateLabel(g.state)}</Badge>
                    </td>
                    <td className="py-2 pr-4 text-xs tabular-nums">{g.retry_count}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-muted">{g.leased_by ?? "—"}</td>
                    <td className="py-2 pr-4 text-xs text-muted">{fmtAge(g.updated_at)}</td>
                    <td className="max-w-[320px] py-2 pr-4 font-mono text-xs text-rose-400">
                      <ErrorCell error={g.error} />
                    </td>
                    <td className="space-x-1 py-2 text-right whitespace-nowrap">
                      {CANCELLABLE.has(g.state) && (
                        <ActionButton
                          tone="danger"
                          onClick={() => {
                            if (confirm(`取消数据粒 ${stripBatchPrefix(g.granule_id, batchId)}？`)) {
                              cancel.mutate(g.granule_id);
                            }
                          }}
                          pending={cancel.isPending && cancel.variables === g.granule_id}
                          pendingLabel="取消中"
                          className="!px-2 !py-0.5"
                        >
                          取消
                        </ActionButton>
                      )}
                      {RETRYABLE.has(g.state) && (
                        <ActionButton
                          onClick={() => retry.mutate(g.granule_id)}
                          pending={retry.isPending && retry.variables === g.granule_id}
                          pendingLabel="重试中"
                          className="!px-2 !py-0.5"
                        >
                          重试
                        </ActionButton>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-t-0 bg-bg/50">
                      <td colSpan={7} className="px-4 py-3 space-y-3">
                        <StageTimingStrip granuleId={g.granule_id} />
                        <ProgressTimeline granuleId={g.granule_id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-sm text-muted">
                  该筛选条件下没有数据粒。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      <BatchTimingCard batchId={batchId} />

      <Card
        title="日志"
        action={
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted">
              {events.data ? `${events.data.length} 条` : "加载中"}
            </span>
            <div className="flex gap-1">
              {(
                [
                  ["all", "全部"],
                  ["warn", "警告"],
                  ["error", "错误"],
                ] as const
              ).map(([f, label]) => (
                <button
                  key={f}
                  onClick={() => setLogLevel(f)}
                  className={`rounded px-2 py-1 text-xs ${
                    logLevel === f
                      ? "bg-bg text-text"
                      : "text-muted hover:bg-bg hover:text-text"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        }
      >
        <div className="max-h-[50vh] space-y-1 overflow-auto font-mono text-xs">
          {(events.data ?? []).map((e: EventRow) => (
            <div key={e.id} className="flex items-start gap-3 border-b border-border/50 py-1 last:border-0">
              <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
              <Badge tone={e.level}>{levelLabel(e.level)}</Badge>
              <span className="w-24 shrink-0 truncate text-muted">{e.source}</span>
              {e.granule_id ? (
                <span className="w-40 shrink-0 truncate text-muted" title={e.granule_id}>
                  {stripBatchPrefix(e.granule_id, batchId)}
                </span>
              ) : (
                <span className="w-40 shrink-0 text-muted">—</span>
              )}
              <span className="flex-1 break-all">{e.message}</span>
            </div>
          ))}
          {(events.data ?? []).length === 0 && (
            <div className="py-8 text-center text-sm text-muted">
              暂无该批次的事件。
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function ErrorCell({ error }: { error: string | null }) {
  const [open, setOpen] = useState(false);
  if (!error) return null;
  const isLong = error.length > 80 || error.includes("\n");
  if (!isLong) {
    return <span>{error}</span>;
  }
  if (!open) {
    return (
      <span className="block">
        <span className="block truncate" title="点击查看完整错误">{error}</span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-0.5 rounded bg-rose-950/30 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-950/60"
        >
          展开完整错误（{error.length} 字符）
        </button>
      </span>
    );
  }
  return (
    <span className="block">
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded border border-rose-900/60 bg-rose-950/20 p-2 text-[11px]">
        {error}
      </pre>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="mt-1 rounded bg-rose-950/30 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-950/60"
      >
        收起
      </button>
    </span>
  );
}

function BatchTimingCard({ batchId }: { batchId: string }) {
  const q = useQuery({
    queryKey: ["batch-timing", batchId],
    queryFn: () => API.batchTiming(batchId),
    enabled: !!batchId,
  });
  const data = q.data;
  return (
    <Card title="耗时统计">
      {q.isLoading && <div className="text-xs text-muted">加载中…</div>}
      {data && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2">阶段</th>
              <th className="pb-2 text-right">样本数</th>
              <th className="pb-2 text-right">平均</th>
              <th className="pb-2 text-right">P50</th>
              <th className="pb-2 text-right">P95</th>
              <th className="pb-2 text-right">最大</th>
            </tr>
          </thead>
          <tbody>
            {STAGE_ORDER.map((st) => {
              const s: StageStats = data[st];
              const dim = s.count === 0;
              return (
                <tr key={st} className={`border-t border-border ${dim ? "text-muted" : ""}`}>
                  <td className="py-2">{TIMING_STAGE_ZH[st]}</td>
                  <td className="py-2 text-right tabular-nums">{s.count}</td>
                  <td className="py-2 text-right tabular-nums">{dim ? "—" : fmtMs(s.avg_ms)}</td>
                  <td className="py-2 text-right tabular-nums">{dim ? "—" : fmtMs(s.p50_ms)}</td>
                  <td className="py-2 text-right tabular-nums">{dim ? "—" : fmtMs(s.p95_ms)}</td>
                  <td className="py-2 text-right tabular-nums">{dim ? "—" : fmtMs(s.max_ms)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="mt-2 text-[11px] text-muted">
        样本数 = 闭合阶段次数（同一数据粒重试会计入多次）。失败未闭合的阶段不计入。
      </div>
    </Card>
  );
}

function StageTimingStrip({ granuleId }: { granuleId: string }) {
  const q = useQuery({
    queryKey: ["granule-timing", granuleId],
    queryFn: () => API.granuleTiming(granuleId),
  });
  const rows = q.data ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-3 text-xs text-muted">
      {rows.map((r: TimingRow, i: number) => (
        <span key={r.id} className="font-mono">
          {TIMING_STAGE_ZH[r.stage]} <span className="text-text">{fmtMs(r.duration_ms)}</span>
          {i < rows.length - 1 && <span className="ml-3 text-border">·</span>}
        </span>
      ))}
    </div>
  );
}

function ProgressTimeline({ granuleId }: { granuleId: string }) {
  const q = useQuery({
    queryKey: ["granule-progress", granuleId],
    queryFn: () => API.granuleProgress(granuleId),
  });
  if (q.isLoading) return <div className="text-xs text-muted">加载中…</div>;
  const rows = q.data ?? [];
  if (rows.length === 0) {
    return <div className="text-xs text-muted">暂无进度上报（bundle 可能未接入 $SATHOP_PROGRESS_URL）</div>;
  }
  return (
    <ol className="space-y-1 border-l border-border pl-4 text-xs">
      {rows.map((p: ProgressRow) => (
        <li key={p.id} className="relative">
          <span className="absolute -left-[1.3rem] top-1 h-2 w-2 rounded-full bg-accent" />
          <span className="w-20 text-muted">{fmtAge(p.ts)}</span>
          <span className="ml-3 font-medium">{formatStep(p.step)}</span>
          {p.pct != null && <span className="ml-2 text-muted">{p.pct.toFixed(0)}%</span>}
          {p.detail && <span className="ml-2 text-muted">— {p.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
