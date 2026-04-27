import { useQuery } from "@tanstack/react-query";
import { API } from "../api";
import { Badge, Card, CopyButton, fmtGB } from "../ui";
import { PLATFORM_ZH, fmtAge } from "../i18n";

export function Receivers() {
  const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">接收端</h1>
      {(receivers.data ?? []).length === 0 && (
        <Card>
          <div className="py-8 text-center text-sm text-muted">暂无已注册的接收端。</div>
        </Card>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(receivers.data ?? []).map((r) => {
          const sec = (Date.now() - new Date(r.last_seen).getTime()) / 1000;
          let tone: "acked" | "warn" | "error" = "error";
          let label = "离线";
          if (sec < 60) {
            tone = "acked";
            label = "在线";
          } else if (sec < 300) {
            tone = "warn";
            label = "待机";
          }
          return (
            <Card key={r.receiver_id}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1 font-mono text-sm font-semibold">
                  <span className="truncate">{r.receiver_id}</span>
                  <CopyButton value={r.receiver_id} title="复制接收端 ID" />
                </div>
                <Badge tone={tone}>{label}</Badge>
              </div>
              <div className="text-xs text-muted">平台：{PLATFORM_ZH[r.platform] ?? r.platform}</div>
              <div className="text-xs text-muted">心跳：{fmtAge(r.last_seen)}</div>
              <div className="mt-3 text-sm">
                剩余磁盘：<span className="tabular-nums">{fmtGB(r.disk_free_gb)}</span>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
