import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { useNavigate } from "react-router-dom";
import { API, GranuleState } from "../api";
import { Badge, Card, Stat } from "../ui";
import { fmtAge, levelLabel, stateLabel } from "../i18n";

const ORDER: GranuleState[] = [
  "pending", "downloading", "downloaded", "processing", "processed", "uploaded", "acked", "deleted",
];

const COLORS: Record<GranuleState, string> = {
  pending: "#475569",
  downloading: "#0ea5e9",
  downloaded: "#0284c7",
  processing: "#6366f1",
  processed: "#4f46e5",
  uploaded: "#8b5cf6",
  acked: "#10b981",
  deleted: "#059669",
  failed: "#f43f5e",
  blacklisted: "#9f1239",
};

export function Dashboard() {
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ["overview"], queryFn: API.overview });
  const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });
  const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
  const inflight = useQuery({ queryKey: ["in-flight"], queryFn: () => API.inFlight(30) });

  const counts = overview.data?.state_counts ?? {};
  const stuck = overview.data?.stuck_by_state ?? {};
  const stuckTotal = Object.values(stuck).reduce((a, b) => a + b, 0);
  const failed = (counts.failed ?? 0) + (counts.blacklisted ?? 0);
  const inflightTotal = ORDER.slice(0, 7).reduce((s, k) => s + (counts[k] ?? 0), 0);
  const done = counts.deleted ?? 0;

  const activeWorkers = (workers.data ?? []).filter(
    (w) => Date.now() - new Date(w.last_seen).getTime() < 120_000,
  ).length;
  const activeReceivers = (receivers.data ?? []).filter(
    (r) => Date.now() - new Date(r.last_seen).getTime() < 120_000,
  ).length;

  // Horizontal bar: one row per non-empty state, ordered top-to-bottom as the
  // pipeline flows. ECharts renders y-axis top-down when we reverse the arrays.
  const barStates = ORDER.filter((s) => (counts[s] ?? 0) > 0);
  const barCategories = [...barStates].reverse().map((s) => stateLabel(s));
  const barValues = [...barStates].reverse().map((s) => ({
    value: counts[s]!,
    itemStyle: { color: COLORS[s] },
  }));

  const active = inflight.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">总览</h1>
        <p className="text-xs text-muted">管道健康一览 · SSE 实时更新</p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="处理中" value={inflightTotal} to="/batches" />
        <Stat label="已完成" value={done} tone="good" to="/batches" />
        <Stat
          label="失败"
          value={failed}
          tone={failed > 0 ? "bad" : "default"}
          to={failed > 0 ? "/events?level=error" : "/batches"}
        />
        <Stat
          label="卡住 > 6 小时"
          value={stuckTotal}
          tone={stuckTotal > 0 ? "warn" : "default"}
          hint={stuckTotal > 0 ? Object.entries(stuck).map(([k, v]) => `${stateLabel(k as GranuleState)}:${v}`).join(" · ") : undefined}
          to="/events?level=warn"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="各阶段数据粒数量" className="lg:col-span-2">
          {barStates.length === 0 ? (
            <div className="flex h-56 items-center justify-center text-sm text-muted">暂无数据粒。</div>
          ) : (
            <ReactECharts
              style={{ height: 256 }}
              option={{
                grid: { left: 80, right: 48, top: 10, bottom: 28, containLabel: false },
                tooltip: {
                  trigger: "axis",
                  axisPointer: { type: "shadow" },
                  formatter: (params: { name: string; value: number }[]) =>
                    params.map((p) => `${p.name}: <b>${p.value.toLocaleString()}</b>`).join("<br/>"),
                },
                xAxis: {
                  type: "value",
                  name: "数据粒数",
                  nameLocation: "middle",
                  nameGap: 22,
                  nameTextStyle: { color: "#94a3b8", fontSize: 10 },
                  axisLine: { lineStyle: { color: "#475569" } },
                  axisLabel: { color: "#94a3b8" },
                  splitLine: { lineStyle: { color: "#1e293b" } },
                  minInterval: 1,
                },
                yAxis: {
                  type: "category",
                  data: barCategories,
                  axisLine: { lineStyle: { color: "#475569" } },
                  axisLabel: { color: "#e2e8f0" },
                },
                series: [
                  {
                    type: "bar",
                    data: barValues,
                    label: {
                      show: true,
                      position: "right",
                      color: "#e2e8f0",
                      formatter: "{c}",
                    },
                    barMaxWidth: 20,
                  },
                ],
              }}
            />
          )}
        </Card>

        <Card title="节点">
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => navigate("/workers")}
              className="flex w-full items-baseline justify-between rounded px-1 py-1 text-left transition hover:bg-bg"
            >
              <span className="text-sm text-muted">在线工作节点 →</span>
              <span className="tabular-nums">
                <span className="text-xl font-semibold">{activeWorkers}</span>
                <span className="text-muted"> / {workers.data?.length ?? 0}</span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => navigate("/receivers")}
              className="flex w-full items-baseline justify-between rounded px-1 py-1 text-left transition hover:bg-bg"
            >
              <span className="text-sm text-muted">在线接收端 →</span>
              <span className="tabular-nums">
                <span className="text-xl font-semibold">{activeReceivers}</span>
                <span className="text-muted"> / {receivers.data?.length ?? 0}</span>
              </span>
            </button>
          </div>
        </Card>
      </div>

      <Card
        title="正在处理"
        action={
          <span className="text-xs text-muted">
            {active.length > 0 ? `${active.length} 条` : "空闲"}
          </span>
        }
      >
        {active.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted">当前没有正在处理的数据粒。</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="pb-2">数据粒</th>
                <th className="pb-2">批次</th>
                <th className="pb-2">当前阶段</th>
                <th className="pb-2">工作节点</th>
                <th className="pb-2">更新</th>
              </tr>
            </thead>
            <tbody>
              {active.map((g) => {
                const href = `/batches/${g.batch_id}?granule=${encodeURIComponent(g.granule_id)}`;
                return (
                  <tr
                    key={g.granule_id}
                    onClick={() => navigate(href)}
                    className="cursor-pointer border-t border-border transition hover:bg-bg"
                    title="跳转到该数据粒详情"
                  >
                    <td className="py-2 pr-4 font-mono text-xs">{g.granule_id}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-muted">{g.batch_id}</td>
                    <td className="py-2 pr-4">
                      <Badge tone={g.state}>{stateLabel(g.state)}</Badge>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-muted">{g.leased_by ?? "—"}</td>
                    <td className="py-2 pr-4 text-xs text-muted">{fmtAge(g.updated_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="最近事件">
        <div className="space-y-1 font-mono text-xs">
          {(overview.data?.last_events ?? []).map((e) => (
            <div key={e.id} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
              <Badge tone={e.level}>{levelLabel(e.level)}</Badge>
              <span className="w-28 shrink-0 truncate text-muted">{e.source}</span>
              <span className="truncate">{e.message}</span>
            </div>
          ))}
          {(overview.data?.last_events.length ?? 0) === 0 && (
            <div className="text-sm text-muted">无近期事件。</div>
          )}
        </div>
      </Card>
    </div>
  );
}
