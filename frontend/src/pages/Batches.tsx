import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API, BatchSummary, GranuleState } from "../api";
import { ActionButton, Badge, Card, CopyButton, ProgressBar } from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";
import { CreateBatchModal } from "./CreateBatchModal";

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const ERRORED: GranuleState[] = ["failed", "blacklisted"];
const IN_FLIGHT: GranuleState[] = [
  "pending", "downloading", "downloaded", "processing", "processed",
];

function total(b: BatchSummary): number {
  return Object.values(b.counts).reduce((a, c) => a + (c ?? 0), 0);
}
function done(b: BatchSummary): number {
  return TERMINAL.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
}
function errors(b: BatchSummary): number {
  return ERRORED.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
}
function inFlight(b: BatchSummary): number {
  return IN_FLIGHT.reduce((s, k) => s + (b.counts[k] ?? 0), 0);
}

export function Batches() {
  const qc = useQueryClient();
  const toast = useToast();
  const batches = useQuery({ queryKey: ["batches"], queryFn: API.batches });
  const [showCreate, setShowCreate] = useState(false);
  const [urlParams, setUrlParams] = useSearchParams();
  const [search, setSearch] = useState(urlParams.get("q") ?? "");
  const [scope, setScope] = useState<"active" | "all">(
    urlParams.get("scope") === "all" ? "all" : "active",
  );

  const setSearchSynced = (v: string) => {
    setSearch(v);
    const next = new URLSearchParams(urlParams);
    if (v) next.set("q", v);
    else next.delete("q");
    setUrlParams(next, { replace: true });
  };
  const setScopeSynced = (v: "active" | "all") => {
    setScope(v);
    const next = new URLSearchParams(urlParams);
    if (v === "all") next.set("scope", "all");
    else next.delete("scope");
    setUrlParams(next, { replace: true });
  };

  const needle = search.trim().toLowerCase();
  const visible = useMemo(() => {
    const all = batches.data ?? [];
    return all.filter((b) => {
      if (scope === "active") {
        const d = done(b);
        const t = total(b);
        if (t > 0 && d === t && errors(b) === 0) return false;
      }
      if (needle) {
        const hay = `${b.name} ${b.batch_id} ${b.bundle_ref}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [batches.data, scope, needle]);

  const retry = useMutation({
    mutationFn: (id: string) => API.retryFailed(id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      toast.success(`已重置 ${res.reset} 条失败数据粒为待处理`);
    },
    onError: (e: Error) => toast.error(`重试失败：${e.message}`),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => API.cancelBatch(id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      toast.success(`已取消 ${res.cancelled} 条数据粒`);
    },
    onError: (e: Error) => toast.error(`取消失败：${e.message}`),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">批次</h1>
        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearchSynced(e.target.value)}
            placeholder="搜索：名称 / ID / 任务包"
            aria-label="搜索批次"
            className="w-64 rounded border border-border bg-bg px-3 py-1.5 text-xs outline-none focus:border-accent"
          />
          <div className="flex gap-1">
            {([
              ["active", "进行中"],
              ["all", "全部"],
            ] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setScopeSynced(k)}
                className={`rounded px-3 py-1 text-xs ${
                  scope === k
                    ? "bg-accent text-white"
                    : "border border-border bg-bg text-muted hover:text-text"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <ActionButton tone="primary" onClick={() => setShowCreate(true)}>
            新建任务
          </ActionButton>
        </div>
      </div>
      <div className="text-xs text-muted tabular-nums">
        {visible.length} / {batches.data?.length ?? 0} 个批次
      </div>

      {showCreate && (
        <CreateBatchModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            qc.invalidateQueries({ queryKey: ["batches"] });
          }}
        />
      )}

      <Card>
        <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2">批次</th>
              <th className="pb-2">处理包</th>
              <th className="pb-2">目标接收端</th>
              <th className="pb-2">进度</th>
              <th className="pb-2">创建时间</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((b) => {
              const t = total(b);
              const d = done(b);
              const err = errors(b);
              const pct = t > 0 ? (d / t) * 100 : 0;
              return (
                <tr key={b.batch_id} className="border-t border-border">
                  <td className="py-3 pr-4">
                    <Link to={`/batches/${b.batch_id}`} className="block hover:text-accent">
                      <div className="font-medium">{b.name}</div>
                      <div className="font-mono text-xs text-muted">
                        {b.batch_id}
                        <CopyButton value={b.batch_id} title="复制批次 ID" />
                      </div>
                    </Link>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-muted">
                    {b.bundle_ref.startsWith("orch:") ? (
                      <Link
                        to={`/bundles?name=${encodeURIComponent(b.bundle_ref.slice(5).split("@")[0])}&version=${encodeURIComponent(b.bundle_ref.slice(5).split("@")[1] ?? "")}`}
                        className="hover:text-accent"
                        title="在任务包页查看"
                      >
                        {b.bundle_ref}
                      </Link>
                    ) : (
                      b.bundle_ref
                    )}
                  </td>
                  <td className="py-3 pr-4">
                    <Badge tone="info">{b.target_receiver_id ?? "任意"}</Badge>
                  </td>
                  <td className="w-[260px] py-3 pr-4">
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="tabular-nums">
                        {d} / {t} <span className="text-muted">({pct.toFixed(0)}%)</span>
                      </span>
                      {err > 0 && <span className="text-rose-400">失败 {err}</span>}
                    </div>
                    <ProgressBar value={d} max={t} tone={err > 0 ? "warn" : "good"} />
                  </td>
                  <td className="py-3 pr-4 text-xs text-muted">{fmtAge(b.created_at)}</td>
                  <td className="space-x-2 py-3 text-right whitespace-nowrap">
                    {err > 0 && (
                      <ActionButton
                        onClick={() => retry.mutate(b.batch_id)}
                        pending={retry.isPending && retry.variables === b.batch_id}
                        pendingLabel="重试中…"
                      >
                        重试失败项 ({err})
                      </ActionButton>
                    )}
                    {inFlight(b) > 0 && (
                      <ActionButton
                        tone="danger"
                        onClick={() => {
                          if (
                            confirm(
                              `取消批次 "${b.name}" 中尚未完成的 ${inFlight(b)} 条数据粒？\n\n已上传/已确认的不会被取消。`,
                            )
                          ) {
                            cancel.mutate(b.batch_id);
                          }
                        }}
                        pending={cancel.isPending && cancel.variables === b.batch_id}
                        pendingLabel="取消中…"
                      >
                        取消 ({inFlight(b)})
                      </ActionButton>
                    )}
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-sm text-muted">
                  {(batches.data ?? []).length === 0 ? (
                    <>
                      暂无批次。可通过 <code className="text-text">scripts/import_*.py</code> 脚本或 <code className="text-text">POST /api/batches</code> 创建。
                    </>
                  ) : (
                    "当前筛选条件下没有匹配的批次。"
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        </div>
      </Card>
    </div>
  );
}
