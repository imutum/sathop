import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API, EventRow } from "../api";
import { Badge, Card } from "../ui";
import { fmtAge, levelLabel } from "../i18n";

const LEVEL_FILTERS: { key: "all" | "warn" | "error"; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "warn", label: "警告" },
  { key: "error", label: "错误" },
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

  // Reflect filter state back into the URL so deep links + share links work.
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
      const merged = [...q.data!.filter((r) => !seen.has(r.id)), ...prev];
      return merged.slice(0, 500);
    });
  }, [q.data]);

  // Unique batch IDs seen so far — for the quick batch filter dropdown
  const batches = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) if (r.batch_id) s.add(r.batch_id);
    return Array.from(s).sort();
  }, [rows]);

  const needle = search.trim().toLowerCase();
  const visible = rows.filter((r) => {
    if (filter !== "all" && r.level !== filter) return false;
    if (batchFilter && r.batch_id !== batchFilter) return false;
    if (needle) {
      const hay = `${r.source} ${r.message} ${r.granule_id ?? ""} ${r.batch_id ?? ""}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });

  const toggle = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">事件日志</h1>
        <div className="text-xs text-muted tabular-nums">
          {visible.length} / {rows.length} 条
        </div>
      </div>

      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索：message / source / granule_id / batch_id"
            aria-label="搜索事件"
            className="flex-1 min-w-[240px] rounded border border-border bg-bg px-3 py-1.5 text-xs outline-none focus:border-accent"
          />
          <select
            value={batchFilter}
            onChange={(e) => setBatchFilter(e.target.value)}
            aria-label="按批次过滤"
            className="rounded border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
          >
            <option value="">所有批次</option>
            {batches.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <div className="flex gap-1">
            {LEVEL_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded px-3 py-1 text-xs ${
                  filter === f.key
                    ? "bg-accent text-white"
                    : "border border-border bg-bg text-muted hover:text-text"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          {(search || batchFilter || filter !== "all") && (
            <button
              onClick={() => {
                setSearch("");
                setBatchFilter("");
                setFilter("all");
              }}
              className="rounded border border-border bg-bg px-2 py-1.5 text-xs text-muted hover:text-text"
            >
              清除
            </button>
          )}
        </div>

        <div className="max-h-[70vh] space-y-1 overflow-auto font-mono text-xs">
          {visible.map((e) => {
            const isLong = e.message.length > 160 || e.message.includes("\n");
            const open = expanded.has(e.id);
            return (
              <div
                key={e.id}
                className="flex items-start gap-3 border-b border-border/50 py-1 last:border-0"
              >
                <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
                <Badge tone={e.level}>{levelLabel(e.level)}</Badge>
                <span className="w-32 shrink-0 truncate text-muted" title={e.source}>
                  {e.source}
                </span>
                <span
                  className={`flex-1 ${isLong && !open ? "truncate cursor-pointer hover:text-text" : "break-all whitespace-pre-wrap"}`}
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
                      className="shrink-0 truncate text-muted hover:text-accent"
                      title={`跳转到 ${e.batch_id} 中的 ${e.granule_id}`}
                    >
                      {e.granule_id}
                    </Link>
                  ) : (
                    <span className="shrink-0 truncate text-muted">{e.granule_id}</span>
                  ))}
              </div>
            );
          })}
          {visible.length === 0 && (
            <div className="py-8 text-center text-sm text-muted">
              {rows.length === 0 ? "暂无事件。" : "当前筛选条件下没有匹配。"}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

/** Highlight occurrences of `needle` inside `text`. Case-insensitive. */
function highlight(text: string, needle: string) {
  if (!needle) return text;
  const idx = text.toLowerCase().indexOf(needle);
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-amber-500/30 px-0.5 text-amber-100">
        {text.slice(idx, idx + needle.length)}
      </mark>
      {text.slice(idx + needle.length)}
    </>
  );
}
