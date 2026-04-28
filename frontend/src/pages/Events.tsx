import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API, EventRow } from "../api";
import { Badge, Card, EmptyState, PageHeader, Segmented, Spinner, TextInput } from "../ui";
import { fmtAge, levelLabel } from "../i18n";
import { IconSearch } from "../icons";

const LEVEL_FILTERS: { value: "all" | "warn" | "error"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "warn", label: "警告" },
  { value: "error", label: "错误" },
];

export function Events() {
  const [urlParams, setUrlParams] = useSearchParams();
  const initLevel = (urlParams.get("level") as "all" | "warn" | "error" | null) ?? "all";
  const initSearch = urlParams.get("q") ?? "";
  const initBatch = urlParams.get("batch") ?? "";
  const [filter, setFilter] = useState<"all" | "warn" | "error">(
    ["all", "warn", "error"].includes(initLevel) ? initLevel : "all",
  );
  const [search, setSearch] = useState(initSearch);
  const [batchFilter, setBatchFilter] = useState<string>(initBatch);
  const [rows, setRows] = useState<EventRow[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMoreOlder, setHasMoreOlder] = useState(true);

  useEffect(() => {
    const next = new URLSearchParams();
    if (filter !== "all") next.set("level", filter);
    if (search) next.set("q", search);
    if (batchFilter) next.set("batch", batchFilter);
    setUrlParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, search, batchFilter]);

  const q = useQuery({
    queryKey: ["events"],
    queryFn: async () => API.events(rows[0]?.id ?? 0, 200),
  });

  useEffect(() => {
    if (!q.data || q.data.length === 0) return;
    setRows((prev) => {
      const seen = new Set(prev.map((r) => r.id));
      const fresh = q.data!.filter((r) => !seen.has(r.id));
      if (fresh.length === 0) return prev;
      return [...fresh, ...prev].slice(0, 500);
    });
  }, [q.data]);

  const loadOlder = async () => {
    const oldest = rows[rows.length - 1]?.id;
    if (oldest === undefined || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const older = await API.events(0, 200, oldest);
      if (older.length === 0) {
        setHasMoreOlder(false);
        return;
      }
      setRows((prev) => {
        const seen = new Set(prev.map((r) => r.id));
        return [...prev, ...older.filter((r) => !seen.has(r.id))];
      });
      if (older.length < 200) setHasMoreOlder(false);
    } finally {
      setLoadingOlder(false);
    }
  };

  const batches = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) if (r.batch_id) s.add(r.batch_id);
    return Array.from(s).sort();
  }, [rows]);

  const needle = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      rows.filter((r) => {
        if (filter !== "all" && r.level !== filter) return false;
        if (batchFilter && r.batch_id !== batchFilter) return false;
        if (needle) {
          const hay = `${r.source} ${r.message} ${r.granule_id ?? ""} ${r.batch_id ?? ""}`.toLowerCase();
          if (!hay.includes(needle)) return false;
        }
        return true;
      }),
    [rows, filter, batchFilter, needle],
  );

  const toggle = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-6">
      <PageHeader
        title="事件日志"
        description="所有 Orchestrator / Worker / Receiver 上报事件的合并视图"
        actions={
          <span className="rounded-full border border-border bg-subtle px-3 py-1 text-[11px] font-medium tabular-nums text-muted">
            <span className="text-text">{visible.length}</span> / {rows.length} 条
          </span>
        }
      />

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-5 py-3.5">
          <div className="min-w-[260px] flex-1">
            <TextInput
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索：message / source / granule_id / batch_id"
              aria-label="搜索事件"
              leftIcon={<IconSearch width={13} height={13} />}
            />
          </div>
          <select
            value={batchFilter}
            onChange={(e) => setBatchFilter(e.target.value)}
            aria-label="按批次过滤"
            className="h-8 rounded-lg border border-border bg-surface px-2.5 text-xs text-text outline-none transition hover:border-accent/40 focus:border-accent"
          >
            <option value="">所有批次</option>
            {batches.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <Segmented<"all" | "warn" | "error">
            value={filter}
            onChange={setFilter}
            options={LEVEL_FILTERS}
          />
          {(search || batchFilter || filter !== "all") && (
            <button
              onClick={() => {
                setSearch("");
                setBatchFilter("");
                setFilter("all");
              }}
              className="h-8 rounded-lg border border-border bg-surface px-2.5 text-xs text-muted transition hover:border-accent/40 hover:text-text"
            >
              清除
            </button>
          )}
        </div>

        <div className="max-h-[70vh] overflow-auto font-mono">
          {visible.length === 0 ? (
            <EmptyState
              title={rows.length === 0 ? "暂无事件" : "当前筛选条件下没有匹配"}
            />
          ) : (
            <ul className="divide-y divide-border/50">
              {visible.map((e) => {
                const isLong = e.message.length > 160 || e.message.includes("\n");
                const open = expanded.has(e.id);
                return (
                  <li key={e.id} className="flex items-start gap-3 px-5 py-2 text-[11.5px] transition hover:bg-subtle/40">
                    <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
                    <Badge tone={e.level} dot>{levelLabel(e.level)}</Badge>
                    <span className="w-32 shrink-0 truncate text-muted" title={e.source}>
                      {e.source}
                    </span>
                    <span
                      className={`flex-1 ${isLong && !open ? "cursor-pointer truncate hover:text-text" : "break-all whitespace-pre-wrap"}`}
                      onClick={() => isLong && toggle(e.id)}
                      title={isLong && !open ? "点击展开完整消息" : undefined}
                    >
                      {highlight(e.message, needle)}
                      {isLong && (
                        <button
                          type="button"
                          onClick={(ev) => {
                            ev.stopPropagation();
                            toggle(e.id);
                          }}
                          className="ml-2 text-[10px] text-muted hover:text-accent"
                        >
                          {open ? "收起" : "展开"}
                        </button>
                      )}
                    </span>
                    {e.granule_id &&
                      (e.batch_id ? (
                        <Link
                          to={`/batches/${e.batch_id}?granule=${encodeURIComponent(e.granule_id)}`}
                          className="shrink-0 truncate text-muted transition hover:text-accent"
                          title={`跳转到 ${e.batch_id} 中的 ${e.granule_id}`}
                        >
                          {e.granule_id}
                        </Link>
                      ) : (
                        <span className="shrink-0 truncate text-muted">{e.granule_id}</span>
                      ))}
                  </li>
                );
              })}
            </ul>
          )}
          {rows.length > 0 && (
            <div className="flex items-center justify-center border-t border-border/60 px-5 py-3">
              {hasMoreOlder ? (
                <button
                  type="button"
                  onClick={loadOlder}
                  disabled={loadingOlder}
                  className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-[11.5px] text-muted transition hover:border-accent/40 hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loadingOlder && <Spinner size={12} />}
                  {loadingOlder ? "加载中…" : "加载更早事件"}
                </button>
              ) : (
                <span className="text-[11px] text-muted">已加载到最早事件</span>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function highlight(text: string, needle: string) {
  if (!needle) return text;
  const idx = text.toLowerCase().indexOf(needle);
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-warning/30 px-0.5 text-warning">
        {text.slice(idx, idx + needle.length)}
      </mark>
      {text.slice(idx + needle.length)}
    </>
  );
}
