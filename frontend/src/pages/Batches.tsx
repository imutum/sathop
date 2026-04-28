import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API, BatchSummary, GranuleState } from "../api";
import {
  ActionButton,
  Badge,
  Card,
  CopyButton,
  EmptyState,
  PageHeader,
  ProgressBar,
  Segmented,
  TextInput,
} from "../ui";
import { fmtAge } from "../i18n";
import { useToast } from "../toast";
import { CreateBatchModal } from "./CreateBatchModal";
import { IconPlus, IconSearch } from "../icons";

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
  const [urlParams, setUrlParams] = useSearchParams();
  // ?bundle=<name>@<version> opens the create modal with that bundle pre-selected.
  // Strip the param immediately so a refresh/back navigation doesn't re-open it.
  const initialBundle = urlParams.get("bundle");
  const [showCreate, setShowCreate] = useState(!!initialBundle);
  const [pendingBundle, setPendingBundle] = useState<string | null>(initialBundle);
  useEffect(() => {
    if (!initialBundle) return;
    const next = new URLSearchParams(urlParams);
    next.delete("bundle");
    setUrlParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
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

  const allCount = batches.data?.length ?? 0;
  const activeCount = (batches.data ?? []).filter((b) => {
    const d = done(b);
    const t = total(b);
    return !(t > 0 && d === t && errors(b) === 0);
  }).length;

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
      <PageHeader
        title="批次"
        description="管线提交单元 · 一个批次承载一组数据粒、统一的任务包与凭证"
        actions={
          <ActionButton tone="primary" onClick={() => setShowCreate(true)}>
            <IconPlus width={13} height={13} />
            新建任务
          </ActionButton>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="w-72">
            <TextInput
              value={search}
              onChange={(e) => setSearchSynced(e.target.value)}
              placeholder="搜索：名称 / ID / 任务包"
              aria-label="搜索批次"
              leftIcon={<IconSearch width={13} height={13} />}
            />
          </div>
          <Segmented<"active" | "all">
            value={scope}
            onChange={setScopeSynced}
            options={[
              { value: "active", label: "进行中", count: activeCount },
              { value: "all", label: "全部", count: allCount },
            ]}
          />
        </div>
        <div className="text-xs text-muted tabular-nums">
          显示 <span className="font-medium text-text">{visible.length}</span> / {allCount}
        </div>
      </div>

      {showCreate && (
        <CreateBatchModal
          initialBundle={pendingBundle ?? undefined}
          onClose={() => {
            setShowCreate(false);
            setPendingBundle(null);
          }}
          onCreated={() => {
            setShowCreate(false);
            setPendingBundle(null);
            qc.invalidateQueries({ queryKey: ["batches"] });
          }}
        />
      )}

      <Card padded={false}>
        {visible.length === 0 ? (
          <EmptyState
            title={
              (batches.data ?? []).length === 0
                ? "还没有任何批次"
                : "当前筛选条件下没有匹配"
            }
            description={
              (batches.data ?? []).length === 0
                ? "通过页面右上角“新建任务”创建第一个批次。"
                : undefined
            }
            action={
              (batches.data ?? []).length === 0 && (
                <ActionButton tone="primary" onClick={() => setShowCreate(true)}>
                  <IconPlus width={13} height={13} />
                  新建任务
                </ActionButton>
              )
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
                <tr>
                  <th className="px-5 py-3">批次</th>
                  <th className="px-2 py-3">处理包</th>
                  <th className="px-2 py-3">目标接收端</th>
                  <th className="px-2 py-3">进度</th>
                  <th className="px-2 py-3">创建时间</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((b) => {
                  const t = total(b);
                  const d = done(b);
                  const err = errors(b);
                  const pct = t > 0 ? (d / t) * 100 : 0;
                  return (
                    <tr key={b.batch_id} className="border-t border-border/60 transition hover:bg-subtle/40">
                      <td className="px-5 py-3.5">
                        <Link to={`/batches/${b.batch_id}`} className="block">
                          <div className="font-medium text-text transition hover:text-accent">{b.name}</div>
                          <div className="mt-0.5 inline-flex items-center font-mono text-[11px] text-muted">
                            {b.batch_id}
                            <CopyButton value={b.batch_id} title="复制批次 ID" />
                          </div>
                        </Link>
                      </td>
                      <td className="px-2 py-3.5 font-mono text-[11.5px] text-muted">
                        {b.bundle_ref.startsWith("orch:") ? (
                          <Link
                            to={`/bundles?name=${encodeURIComponent(b.bundle_ref.slice(5).split("@")[0])}&version=${encodeURIComponent(b.bundle_ref.slice(5).split("@")[1] ?? "")}`}
                            className="transition hover:text-accent"
                            title="在任务包页查看"
                          >
                            {b.bundle_ref}
                          </Link>
                        ) : (
                          b.bundle_ref
                        )}
                      </td>
                      <td className="px-2 py-3.5">
                        <Badge tone="info">{b.target_receiver_id ?? "任意"}</Badge>
                      </td>
                      <td className="w-[280px] px-2 py-3.5">
                        <div className="mb-1 flex items-center justify-between text-[11.5px]">
                          <span className="tabular-nums">
                            <span className="font-medium text-text">{d}</span>
                            <span className="text-muted"> / {t}</span>
                            <span className="ml-1 text-muted">({pct.toFixed(0)}%)</span>
                          </span>
                          {err > 0 && <span className="text-danger">失败 {err}</span>}
                        </div>
                        <ProgressBar value={d} max={t} tone={err > 0 ? "warn" : "good"} />
                      </td>
                      <td className="px-2 py-3.5 text-[11.5px] text-muted">{fmtAge(b.created_at)}</td>
                      <td className="space-x-1.5 whitespace-nowrap px-5 py-3.5 text-right">
                        {err > 0 && (
                          <ActionButton
                            onClick={() => retry.mutate(b.batch_id)}
                            pending={retry.isPending && retry.variables === b.batch_id}
                            pendingLabel="重试中…"
                            size="sm"
                          >
                            重试失败 ({err})
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
                            size="sm"
                          >
                            取消 ({inFlight(b)})
                          </ActionButton>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
