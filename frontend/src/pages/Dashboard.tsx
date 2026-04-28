import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useMemo } from "react";

// Lazy: ECharts is ~1MB and only renders when there's data. First-run users
// (showing the onboarding card, no chart yet) skip the download entirely.
const ReactECharts = lazy(() => import("echarts-for-react"));
import { Link, useNavigate } from "react-router-dom";
import { API, GranuleState } from "../api";
import { ActionButton, Badge, Card, EmptyState, PageHeader, Spinner, Stat } from "../ui";
import { fmtAge, levelLabel, stateLabel } from "../i18n";
import { useTheme } from "../theme";
import { IconAlert, IconBundles, IconCheck, IconPulse, IconReceivers, IconWorkers } from "../icons";

const ORDER: GranuleState[] = [
  "pending", "downloading", "downloaded", "processing", "processed", "uploaded", "acked", "deleted",
];

const COLORS_DARK: Record<GranuleState, string> = {
  pending: "#64748b",
  downloading: "#38bdf8",
  downloaded: "#0ea5e9",
  processing: "#818cf8",
  processed: "#6366f1",
  uploaded: "#a78bfa",
  acked: "#34d399",
  deleted: "#10b981",
  failed: "#fb7185",
  blacklisted: "#9f1239",
};

const COLORS_LIGHT: Record<GranuleState, string> = {
  pending: "#94a3b8",
  downloading: "#0284c7",
  downloaded: "#0369a1",
  processing: "#4f46e5",
  processed: "#4338ca",
  uploaded: "#7c3aed",
  acked: "#059669",
  deleted: "#047857",
  failed: "#e11d48",
  blacklisted: "#9f1239",
};

export function Dashboard() {
  const navigate = useNavigate();
  const { effective } = useTheme();
  const overview = useQuery({ queryKey: ["overview"], queryFn: API.overview });
  const workers = useQuery({ queryKey: ["workers"], queryFn: API.workers });
  const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
  const inflight = useQuery({ queryKey: ["in-flight"], queryFn: () => API.inFlight(30) });

  const isDark = effective === "dark";
  const COLORS = isDark ? COLORS_DARK : COLORS_LIGHT;
  const axisColor = isDark ? "#94a3b8" : "#64748b";
  const axisLine = isDark ? "#334155" : "#cbd5e1";
  const splitLine = isDark ? "#1e293b" : "#e2e8f0";
  const labelColor = isDark ? "#e2e8f0" : "#0f172a";

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

  const barStates = ORDER.filter((s) => (counts[s] ?? 0) > 0);
  // Stable serialization so memo doesn't re-run when overview refetches but
  // counts are value-equal — ECharts notMerge:true would otherwise rebuild.
  const countsKey = ORDER.map((s) => `${s}:${counts[s] ?? 0}`).join("|");
  const chartOption = useMemo(() => {
    const cats = [...barStates].reverse().map((s) => stateLabel(s));
    const vals = [...barStates].reverse().map((s) => ({
      value: counts[s]!,
      itemStyle: { color: COLORS[s], borderRadius: [0, 4, 4, 0] },
    }));
    return {
      grid: { left: 80, right: 56, top: 12, bottom: 32, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        backgroundColor: isDark ? "rgba(15,23,42,0.95)" : "rgba(255,255,255,0.97)",
        borderColor: axisLine,
        textStyle: { color: labelColor, fontSize: 12 },
        formatter: (params: { name: string; value: number }[]) =>
          params.map((p) => `${p.name}: <b>${p.value.toLocaleString()}</b>`).join("<br/>"),
      },
      xAxis: {
        type: "value" as const,
        name: "数据粒数",
        nameLocation: "middle" as const,
        nameGap: 22,
        nameTextStyle: { color: axisColor, fontSize: 10 },
        axisLine: { lineStyle: { color: axisLine } },
        axisLabel: { color: axisColor },
        splitLine: { lineStyle: { color: splitLine } },
        minInterval: 1,
      },
      yAxis: {
        type: "category" as const,
        data: cats,
        axisLine: { lineStyle: { color: axisLine } },
        axisLabel: { color: labelColor, fontSize: 12 },
        axisTick: { show: false },
      },
      series: [
        {
          type: "bar" as const,
          data: vals,
          label: { show: true, position: "right" as const, color: labelColor, formatter: "{c}", fontSize: 11 },
          barMaxWidth: 18,
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countsKey, isDark]);

  const active = inflight.data ?? [];

  // First-run hint: nothing has happened yet AND no worker has connected.
  // Equivalent to "fresh deployment" — surface a 3-step path to first batch.
  const firstRun =
    overview.isSuccess &&
    workers.isSuccess &&
    Object.keys(counts).length === 0 &&
    (workers.data?.length ?? 0) === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="总览"
        description="管道健康一览 · SSE 实时更新"
      />

      {firstRun && <OnboardingCard />}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat
          label="处理中"
          value={inflightTotal.toLocaleString()}
          icon={<IconPulse />}
          to="/batches"
        />
        <Stat
          label="已完成"
          value={done.toLocaleString()}
          tone="good"
          icon={<IconCheck />}
          to="/batches"
        />
        <Stat
          label="失败"
          value={failed.toLocaleString()}
          tone={failed > 0 ? "bad" : "default"}
          icon={<IconAlert />}
          to={failed > 0 ? "/events?level=error" : "/batches"}
        />
        <Stat
          label="卡住 > 6 小时"
          value={stuckTotal.toLocaleString()}
          tone={stuckTotal > 0 ? "warn" : "default"}
          hint={
            stuckTotal > 0
              ? Object.entries(stuck)
                  .map(([k, v]) => `${stateLabel(k as GranuleState)}:${v}`)
                  .join(" · ")
              : "一切顺利"
          }
          to="/events?level=warn"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          title="各阶段数据粒数量"
          description="管线各阶段当前驻留数据粒"
          className="lg:col-span-2"
        >
          {barStates.length === 0 ? (
            <div className="flex h-56 items-center justify-center">
              <EmptyState title="暂无数据粒" />
            </div>
          ) : (
            <Suspense
              fallback={
                <div className="flex h-[280px] items-center justify-center text-xs text-muted">
                  <Spinner />
                  <span className="ml-2">加载图表…</span>
                </div>
              }
            >
              <ReactECharts
                style={{ height: 280 }}
                opts={{ renderer: "svg" }}
                option={chartOption}
                notMerge
              />
            </Suspense>
          )}
        </Card>

        <Card title="节点" description="集群健康度">
          <div className="space-y-3">
            <NodeStat
              icon={<IconWorkers />}
              label="工作节点"
              value={activeWorkers}
              total={workers.data?.length ?? 0}
              onClick={() => navigate("/workers")}
            />
            <NodeStat
              icon={<IconReceivers />}
              label="接收端"
              value={activeReceivers}
              total={receivers.data?.length ?? 0}
              onClick={() => navigate("/receivers")}
            />
          </div>
        </Card>
      </div>

      <Card
        title="正在处理"
        description="近 30 条非终态数据粒"
        action={
          <span className="rounded-full border border-border bg-subtle px-2.5 py-0.5 text-[11px] font-medium text-muted tabular-nums">
            {active.length > 0 ? `${active.length} 条` : "空闲"}
          </span>
        }
        padded={false}
      >
        {active.length === 0 ? (
          <EmptyState
            title="当前没有正在处理的数据粒"
            description="新建批次后，活动条目会自动出现在这里。"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-subtle/50 text-left text-[10.5px] font-semibold uppercase tracking-[0.10em] text-muted">
                <tr>
                  <th className="px-5 py-2.5">数据粒</th>
                  <th className="px-2 py-2.5">批次</th>
                  <th className="px-2 py-2.5">当前阶段</th>
                  <th className="px-2 py-2.5">工作节点</th>
                  <th className="px-5 py-2.5">更新</th>
                </tr>
              </thead>
              <tbody>
                {active.map((g) => {
                  const href = `/batches/${g.batch_id}?granule=${encodeURIComponent(g.granule_id)}`;
                  return (
                    <tr
                      key={g.granule_id}
                      onClick={() => navigate(href)}
                      className="cursor-pointer border-t border-border/70 transition hover:bg-subtle/50"
                      title="跳转到该数据粒详情"
                    >
                      <td className="px-5 py-2.5 font-mono text-[11.5px]">{g.granule_id}</td>
                      <td className="px-2 py-2.5 font-mono text-[11.5px] text-muted">{g.batch_id}</td>
                      <td className="px-2 py-2.5">
                        <Badge tone={g.state} dot>{stateLabel(g.state)}</Badge>
                      </td>
                      <td
                        className="px-2 py-2.5 font-mono text-[11.5px] text-muted"
                        onClick={(e) => g.leased_by && e.stopPropagation()}
                      >
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
                      <td className="px-5 py-2.5 text-[11.5px] text-muted">{fmtAge(g.updated_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="最近事件" description="后台 10 条" padded={false}>
        <div className="divide-y divide-border/60">
          {(overview.data?.last_events ?? []).map((e) => (
            <div
              key={e.id}
              className="flex items-center gap-3 px-5 py-2.5 font-mono text-[11.5px] transition hover:bg-subtle/50"
            >
              <span className="w-20 shrink-0 text-muted">{fmtAge(e.ts)}</span>
              <Badge tone={e.level} dot>{levelLabel(e.level)}</Badge>
              <span className="w-32 shrink-0 truncate text-muted">{e.source}</span>
              <span className="flex-1 truncate text-text">{e.message}</span>
            </div>
          ))}
          {(overview.data?.last_events.length ?? 0) === 0 && (
            <EmptyState title="暂无事件" />
          )}
        </div>
      </Card>
    </div>
  );
}

function NodeStat({
  label,
  value,
  total,
  icon,
  onClick,
}: {
  label: string;
  value: number;
  total: number;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  const ratio = total > 0 ? value / total : 0;
  const tone = total === 0 ? "muted" : ratio === 1 ? "success" : ratio >= 0.5 ? "warning" : "danger";
  const colorMap = {
    muted: "text-muted",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center justify-between rounded-xl border border-border bg-subtle/40 p-3.5 text-left transition hover:border-accent/40 hover:bg-subtle"
    >
      <div className="flex items-center gap-3">
        <span
          className={`grid h-9 w-9 place-items-center rounded-lg bg-surface text-muted shadow-soft transition group-hover:text-accent`}
        >
          {icon}
        </span>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.10em] text-muted">{label}</div>
          <div className="mt-1 text-[13px] text-text">在线 / 已注册</div>
        </div>
      </div>
      <div className="flex items-baseline gap-1.5 tabular-nums">
        <span className={`font-display text-2xl font-semibold tracking-tight ${colorMap[tone]}`}>
          {value}
        </span>
        <span className="text-sm text-muted">/ {total}</span>
      </div>
    </button>
  );
}

function OnboardingCard() {
  return (
    <Card
      title="首次使用 SatHop？"
      description="集群里还没有任务包或工作节点。三步完成首个批次："
    >
      <ol className="grid gap-4 md:grid-cols-3">
        <Step
          n={1}
          icon={<IconWorkers />}
          title="启动 worker"
          body={
            <>
              在 worker 主机上配置 <Code>deploy/worker/.env</Code>，
              <br />
              <Code>docker compose up -d</Code> 拉起即可注册。
            </>
          }
        />
        <Step
          n={2}
          icon={<IconBundles />}
          title="上传任务包"
          body={<>用户脚本入口、依赖、输入/输出契约。</>}
          action={
            <Link to="/bundles">
              <ActionButton tone="primary">前往任务包</ActionButton>
            </Link>
          }
        />
        <Step
          n={3}
          icon={<IconPulse />}
          title="新建批次"
          body={<>选定任务包 + 凭证，提交首组数据粒。</>}
          action={
            <Link to="/batches">
              <ActionButton tone="outline">前往批次</ActionButton>
            </Link>
          }
        />
      </ol>
    </Card>
  );
}

function Step({
  n,
  icon,
  title,
  body,
  action,
}: {
  n: number;
  icon: React.ReactNode;
  title: string;
  body: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <li className="flex h-full flex-col rounded-xl border border-border bg-subtle/40 p-4">
      <div className="flex items-center gap-2.5">
        <span className="font-display grid h-7 w-7 place-items-center rounded-lg bg-accent/15 text-[12.5px] font-semibold text-accent tabular-nums">
          {n}
        </span>
        <span className="text-muted">{icon}</span>
        <span className="text-sm font-semibold text-text">{title}</span>
      </div>
      <p className="mt-3 flex-1 text-xs leading-relaxed text-muted">{body}</p>
      {action && <div className="mt-3">{action}</div>}
    </li>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-subtle px-1.5 py-0.5 font-mono text-[10.5px] text-text">
      {children}
    </code>
  );
}
