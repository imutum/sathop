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
import { ActionButton, Badge, Card, CopyButton, EmptyState, Field, PageHeader, Segmented } from "../ui";
import { TIMING_STAGE_ZH, fmtAge, fmtDuration, fmtMs, fmtPerMinute, levelLabel, stateLabel } from "../i18n";
import { useToast } from "../toast";
import { IconArrowLeft } from "../icons";

const STATE_FILTERS: { value: GranuleState | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待处理" },
  { value: "downloading", label: "下载中" },
  { value: "processing", label: "处理中" },
  { value: "uploaded", label: "已上传" },
  { value: "acked", label: "已确认" },
  { value: "deleted", label: "已清理" },
  { value: "failed", label: "失败" },
  { value: "blacklisted", label: "已拉黑" },
];

const CANCELLABLE = new Set<GranuleState>([
  "pending", "downloading", "downloaded", "processing", "processed",
]);
const RETRYABLE = new Set<GranuleState>(["failed", "blacklisted"]);
// Same set as CANCELLABLE — used to compute the batch-level "in-flight" count
// surfaced in the page-header "取消 (N)" action.
const INFLIGHT_STATES: GranuleState[] = [
  "pending", "downloading", "downloaded", "processing", "processed",
];

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
  const [filter, setFilter] = useState<GranuleState | "all">("all");
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
  const retryAll = useMutation({
    mutationFn: () => API.retryFailed(batchId),
    onSuccess: (res) => {
      invalidate();
      toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
    },
    onError: (e: Error) => toast.error(`重试失败：${e.message}`),
  });
  const cancelAll = useMutation({
    mutationFn: () => API.cancelBatch(batchId),
    onSuccess: (res) => {
      invalidate();
      toast.success(`已取消 ${res.cancelled} 条数据粒`);
    },
    onError: (e: Error) => toast.error(`取消失败：${e.message}`),
  });

  // Scroll once per highlight value — granules.data churns on every poll/SSE
  // nudge and would otherwise restart smooth-scroll continuously.
  const lastScrolledHighlight = useRef<string | null>(null);
  useEffect(() => {
    if (!highlight || !highlightedRef.current) return;
    if (lastScrolledHighlight.current === highlight) return;
    highlightedRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    lastScrolledHighlight.current = highlight;
  }, [highlight, granules.data]);

  if (!batchId) return null;

  const b = batch.data;
  const rows = granules.data ?? [];
  const failedCount = (b?.counts?.failed ?? 0) + (b?.counts?.blacklisted ?? 0);
  const inflightCount = INFLIGHT_STATES.reduce((s, k) => s + (b?.counts?.[k] ?? 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/batches"
          className="inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-text"
        >
          <IconArrowLeft width={12} height={12} /> 批次列表
        </Link>
        <div className="mt-2">
          <PageHeader
            title={b?.name ?? batchId}
            description={
              <span className="inline-flex items-center font-mono text-[11.5px] text-muted">
                {batchId}
                <CopyButton value={batchId} title="复制批次 ID" />
              </span>
            }
            actions={
              b && (
                <>
                  {failedCount > 0 && (
                    <ActionButton
                      onClick={() => retryAll.mutate()}
                      pending={retryAll.isPending}
                      pendingLabel="重试中…"
                      size="sm"
                    >
                      重试失败 ({failedCount})
                    </ActionButton>
                  )}
                  {inflightCount > 0 && (
                    <ActionButton
                      tone="danger"
                      size="sm"
                      onClick={() => {
                        if (
                          confirm(
                            `取消批次 "${b.name}" 中尚未完成的 ${inflightCount} 条数据粒？\n\n已上传/已确认的不会被取消。`,
                          )
                        ) {
                          cancelAll.mutate();
                        }
                      }}
                      pending={cancelAll.isPending}
                      pendingLabel="取消中…"
                    >
                      取消 ({inflightCount})
                    </ActionButton>
                  )}
                </>
              )
            }
          />
        </div>
      </div>

      {b && (
        <Card padded={false}>
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-4">
            <Field label="处理包" mono>
              {b.bundle_ref}
            </Field>
            <Field label="目标接收端">
              <Badge tone="info">{b.target_receiver_id ?? "任意"}</Badge>
            </Field>
            <Field label="创建时间">
              <span className="text-xs">{fmtAge(b.created_at)}</span>
            </Field>
            <Field label="状态">
              <span className="text-xs">{b.status}</span>
            </Field>
          </div>
          <div className="flex flex-wrap gap-1.5 border-t border-border/60 px-5 py-3">
            {Object.entries(b.counts).map(([state, n]) => (
              <Badge key={state} tone={state} dot>
                {stateLabel(state as GranuleState)} <span className="ml-1 tabular-nums">{n}</span>
              </Badge>
            ))}
          </div>
        </Card>
      )}

      <Card
        title="数据粒"
        description="按状态筛选 · 点击行展开阶段计时 / 进度时间线 / 该粒事件"
        padded={false}
        action={
          <Segmented<GranuleState | "all">
            value={filter}
            onChange={setFilter}
            size="sm"
            options={STATE_FILTERS.map((f) => {
              const count =
                f.value === "all"
                  ? Object.values(b?.counts ?? {}).reduce((s, n) => s + (n ?? 0), 0)
                  : (b?.counts?.[f.value as GranuleState] ?? 0);
              return {
                value: f.value,
                label: f.label,
                count,
                dim: count === 0 && f.value !== "all",
              };
            })}
          />
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
              <tr>
                <th className="px-5 py-3">数据粒</th>
                <th className="px-2 py-3">状态</th>
                <th className="px-2 py-3">重试</th>
                <th className="px-2 py-3">领取方</th>
                <th className="px-2 py-3">更新</th>
                <th className="px-2 py-3">错误</th>
                <th className="px-5 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g: GranuleRow) => {
                const latest = latestProgress.data?.[g.granule_id];
                const isOpen = expanded === g.granule_id;
                return (
                  <Fragment key={g.granule_id}>
                    <tr
                      ref={g.granule_id === highlight ? highlightedRef : undefined}
                      className={`border-t border-border/60 align-top transition hover:bg-subtle/40 ${
                        g.granule_id === highlight ? "bg-accent-soft/40" : ""
                      }`}
                    >
                      <td className="px-5 py-2.5 font-mono text-[11.5px]">
                        <button
                          onClick={() => setExpanded(isOpen ? null : g.granule_id)}
                          className="mr-1 inline-block w-3 text-muted hover:text-text"
                          title={isOpen ? "收起进度" : "展开进度"}
                        >
                          {isOpen ? "▾" : "▸"}
                        </button>
                        {stripBatchPrefix(g.granule_id, batchId)}
                        {latest && (
                          <div className="ml-4 mt-0.5 text-[11px] text-muted">
                            ▸ {formatStep(latest.step)}
                            {latest.pct != null ? ` · ${latest.pct.toFixed(0)}%` : ""}
                            {latest.detail ? ` · ${latest.detail}` : ""}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2.5">
                        <Badge tone={g.state} dot>{stateLabel(g.state)}</Badge>
                      </td>
                      <td className="px-2 py-2.5 text-[11.5px] tabular-nums">{g.retry_count}</td>
                      <td className="px-2 py-2.5 font-mono text-[11.5px] text-muted">
                        {g.leased_by ? (
                          <Link
                            to={`/workers?id=${encodeURIComponent(g.leased_by)}`}
                            className="transition hover:text-accent"
                            title="跳转到该 worker 卡片"
                          >
                            {g.leased_by}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-2 py-2.5 text-[11.5px] text-muted">{fmtAge(g.updated_at)}</td>
                      <td className="max-w-[320px] px-2 py-2.5 font-mono text-[11.5px] text-danger">
                        <ErrorCell error={g.error} />
                      </td>
                      <td className="space-x-1 whitespace-nowrap px-5 py-2.5 text-right">
                        {CANCELLABLE.has(g.state) && (
                          <ActionButton
                            tone="danger"
                            size="sm"
                            onClick={() => {
                              if (confirm(`取消数据粒 ${stripBatchPrefix(g.granule_id, batchId)}？`)) {
                                cancel.mutate(g.granule_id);
                              }
                            }}
                            pending={cancel.isPending && cancel.variables === g.granule_id}
                            pendingLabel="取消"
                          >
                            取消
                          </ActionButton>
                        )}
                        {RETRYABLE.has(g.state) && (
                          <ActionButton
                            size="sm"
                            onClick={() => retry.mutate(g.granule_id)}
                            pending={retry.isPending && retry.variables === g.granule_id}
                            pendingLabel="重试"
                          >
                            重试
                          </ActionButton>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-subtle/40">
                        <td colSpan={7} className="space-y-3 px-5 py-3">
                          <StageTimingStrip granuleId={g.granule_id} />
                          <ProgressTimeline granuleId={g.granule_id} />
                          <GranuleEvents granuleId={g.granule_id} batchId={batchId} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <EmptyState title="该筛选条件下没有数据粒" />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <BatchTimingCard batchId={batchId} remaining={inflightCount} />

      <Card
        title="日志"
        description="按级别筛选 · 仅本批次的事件"
        padded={false}
        action={
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-muted tabular-nums">
              {events.data ? `${events.data.length} 条` : "加载中"}
            </span>
            <Segmented<"all" | "warn" | "error">
              value={logLevel}
              onChange={setLogLevel}
              size="sm"
              options={[
                { value: "all", label: "全部" },
                { value: "warn", label: "警告" },
                { value: "error", label: "错误" },
              ]}
            />
          </div>
        }
      >
        <div className="max-h-[50vh] overflow-auto font-mono">
          {(events.data ?? []).length === 0 ? (
            <EmptyState title="暂无该批次的事件" />
          ) : (
            <ul className="divide-y divide-border/50">
              {(events.data ?? []).map((e: EventRow) => (
                <li
                  key={e.id}
                  className="flex items-start gap-3 px-5 py-2 text-[11.5px] transition hover:bg-subtle/40"
                >
                  <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
                  <Badge tone={e.level} dot>{levelLabel(e.level)}</Badge>
                  <span className="w-24 shrink-0 truncate text-muted">{e.source}</span>
                  {e.granule_id ? (
                    <span className="w-40 shrink-0 truncate text-muted" title={e.granule_id}>
                      {stripBatchPrefix(e.granule_id, batchId)}
                    </span>
                  ) : (
                    <span className="w-40 shrink-0 text-muted">—</span>
                  )}
                  <span className="flex-1 break-all">{e.message}</span>
                </li>
              ))}
            </ul>
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
  if (!isLong) return <span>{error}</span>;
  if (!open) {
    return (
      <span className="block">
        <span className="block truncate" title="点击查看完整错误">{error}</span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger transition hover:bg-danger/25"
        >
          展开完整错误（{error.length} 字符）
        </button>
      </span>
    );
  }
  return (
    <span className="block">
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-danger/30 bg-danger/5 p-2.5 text-[11px]">
        {error}
      </pre>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="mt-1 rounded-md bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger transition hover:bg-danger/25"
      >
        收起
      </button>
    </span>
  );
}

function BatchTimingCard({ batchId, remaining }: { batchId: string; remaining: number }) {
  const q = useQuery({
    queryKey: ["batch-timing", batchId],
    queryFn: () => API.batchTiming(batchId),
    enabled: !!batchId,
  });
  const data = q.data;
  // Throughput uses the upload count: a granule that's "done" from the
  // operator's perspective is one whose upload stage closed. Download/process
  // counts inflate with retries.
  const doneCount = data?.stages.upload.count ?? 0;
  // ETA only when there's enough signal: at least 3 done granules to compute a
  // meaningful per-min rate, and remaining > 0 (i.e. batch is still running).
  const showEta = !!data && data.wall_ms > 0 && doneCount >= 3 && remaining > 0;
  const etaMs = showEta ? Math.round((data.wall_ms / doneCount) * remaining) : 0;
  return (
    <Card
      title="耗时统计"
      description="样本数 = 闭合阶段次数（同一数据粒重试会计入多次）。失败未闭合的阶段不计入。"
      padded={false}
    >
      {q.isLoading && <div className="px-5 py-4 text-xs text-muted">加载中…</div>}
      {data && (
        <>
          {data.wall_ms > 0 && (
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-border/60 px-5 py-4 sm:grid-cols-4">
              <Field label="总耗时（端到端）" hint="wall clock">
                <span className="tabular-nums">{fmtDuration(data.wall_ms)}</span>
              </Field>
              <Field label="完成数据粒">
                <span className="tabular-nums">{doneCount}</span>
              </Field>
              <Field label="平均吞吐">
                <span className="tabular-nums">{fmtPerMinute(doneCount, data.wall_ms)}</span>
              </Field>
              {showEta && (
                <Field
                  label={`预计剩余 (${remaining} 条)`}
                  hint="按当前吞吐外推"
                >
                  <span className="tabular-nums">≈ {fmtDuration(etaMs)}</span>
                </Field>
              )}
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
                <tr>
                  <th className="px-5 py-3">阶段</th>
                  <th className="px-2 py-3 text-right">样本数</th>
                  <th className="px-2 py-3 text-right">平均</th>
                  <th className="px-2 py-3 text-right">P50</th>
                  <th className="px-2 py-3 text-right">P95</th>
                  <th className="px-5 py-3 text-right">最大</th>
                </tr>
              </thead>
              <tbody>
                {STAGE_ORDER.map((st) => {
                  const s: StageStats = data.stages[st];
                  const dim = s.count === 0;
                  return (
                    <tr
                      key={st}
                      className={`border-t border-border/60 ${dim ? "text-muted" : ""}`}
                    >
                      <td className="px-5 py-2.5">{TIMING_STAGE_ZH[st]}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums">{s.count}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums">{dim ? "—" : fmtMs(s.avg_ms)}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums">{dim ? "—" : fmtMs(s.p50_ms)}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums">{dim ? "—" : fmtMs(s.p95_ms)}</td>
                      <td className="px-5 py-2.5 text-right tabular-nums">{dim ? "—" : fmtMs(s.max_ms)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
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
    <div className="flex flex-wrap gap-2">
      {rows.map((r: TimingRow) => (
        <span
          key={r.id}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1 font-mono text-[11px] shadow-soft"
        >
          <span className="text-muted">{TIMING_STAGE_ZH[r.stage]}</span>
          <span className="text-text">{fmtMs(r.duration_ms)}</span>
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
    return (
      <div className="text-[11.5px] text-muted">
        暂无进度上报（bundle 可能未接入 $SATHOP_PROGRESS_URL）
      </div>
    );
  }
  return (
    <ol className="space-y-1.5 border-l border-border pl-4 text-xs">
      {rows.map((p: ProgressRow) => (
        <li key={p.id} className="relative">
          <span className="absolute -left-[1.4rem] top-1.5 h-2 w-2 rounded-full bg-accent shadow-glow" />
          <span className="w-20 text-muted">{fmtAge(p.ts)}</span>
          <span className="ml-3 font-medium">{formatStep(p.step)}</span>
          {p.pct != null && <span className="ml-2 text-muted tabular-nums">{p.pct.toFixed(0)}%</span>}
          {p.detail && <span className="ml-2 text-muted">— {p.detail}</span>}
        </li>
      ))}
    </ol>
  );
}

function GranuleEvents({ granuleId, batchId }: { granuleId: string; batchId: string }) {
  const q = useQuery({
    queryKey: ["granule-events", granuleId],
    queryFn: () => API.granuleEvents(granuleId, 50),
  });
  const rows = q.data ?? [];
  return (
    <div>
      <div className="mb-1.5 flex items-baseline gap-2">
        <span className="text-[10.5px] font-medium uppercase tracking-[0.10em] text-muted">
          事件 · 仅本数据粒
        </span>
        <Link
          to={`/events?q=${encodeURIComponent(stripBatchPrefix(granuleId, batchId))}`}
          className="text-[10.5px] text-muted transition hover:text-accent"
        >
          全屏 →
        </Link>
      </div>
      {q.isLoading ? (
        <div className="text-[11px] text-muted">加载中…</div>
      ) : rows.length === 0 ? (
        <div className="text-[11px] text-muted">暂无事件</div>
      ) : (
        <ul className="max-h-56 space-y-1 overflow-auto rounded-lg border border-border/60 bg-bg/40 p-2 font-mono">
          {rows.map((e: EventRow) => (
            <li key={e.id} className="flex items-start gap-2 text-[11px]">
              <span className="w-16 shrink-0 text-muted">{fmtAge(e.ts)}</span>
              <Badge tone={e.level} dot>{levelLabel(e.level)}</Badge>
              <span className="w-24 shrink-0 truncate text-muted" title={e.source}>{e.source}</span>
              <span className="flex-1 break-all whitespace-pre-wrap">{e.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
