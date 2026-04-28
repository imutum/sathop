import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API, ReceiverInfo } from "../api";
import { Badge, Card, CopyButton, EmptyState, NodeLifecycleActions, PageHeader, fmtGB, nodeStatusBadge } from "../ui";
import { PLATFORM_ZH, fmtAge } from "../i18n";
import { useToast } from "../toast";
import { IconReceivers } from "../icons";

export function Receivers() {
  const receivers = useQuery({ queryKey: ["receivers"], queryFn: API.receivers });
  const list = receivers.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="接收端"
        description="拉取 Worker 已上传产物的下游消费者"
      />

      {list.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconReceivers />}
            title="暂无已注册的接收端"
            description="启动 receiver 容器后会自动出现在此。"
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((r) => {
            const { tone, label } = nodeStatusBadge(r.enabled, r.last_seen);
            return (
              <Card key={r.receiver_id} padded={false}>
                <div className="flex items-start justify-between gap-2 border-b border-border/60 px-5 py-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1 font-mono text-[13px] font-semibold">
                      <span className="truncate">{r.receiver_id}</span>
                      <CopyButton value={r.receiver_id} title="复制接收端 ID" />
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted">
                      平台 · {PLATFORM_ZH[r.platform] ?? r.platform}
                    </div>
                  </div>
                  <Badge tone={tone} dot>{label}</Badge>
                </div>
                <div className="grid grid-cols-2 gap-4 px-5 py-4">
                  <div>
                    <div className="text-[10.5px] font-medium uppercase tracking-[0.10em] text-muted">
                      剩余磁盘
                    </div>
                    <div className="font-display mt-1 text-base font-semibold tabular-nums">
                      {fmtGB(r.disk_free_gb)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10.5px] font-medium uppercase tracking-[0.10em] text-muted">
                      心跳
                    </div>
                    <div className="mt-1 text-[12.5px]">{fmtAge(r.last_seen)}</div>
                  </div>
                </div>
                <div className="flex justify-end border-t border-border/60 px-5 py-2.5">
                  <ReceiverEnableToggle receiver={r} />
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReceiverEnableToggle({ receiver }: { receiver: ReceiverInfo }) {
  const qc = useQueryClient();
  const toast = useToast();
  const enable = useMutation({
    mutationFn: (next: boolean) => API.setReceiverEnabled(receiver.receiver_id, next),
    onSuccess: (_r, next) => {
      qc.invalidateQueries({ queryKey: ["receivers"] });
      toast.success(next ? "已启用" : "已禁用，下次 pull 会被拒绝");
    },
    onError: (e: Error) => toast.error(`失败：${e.message}`),
  });
  const forget = useMutation({
    mutationFn: () => API.forgetReceiver(receiver.receiver_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["receivers"] });
      toast.success(`已删除接收端 ${receiver.receiver_id}`);
    },
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });
  return (
    <NodeLifecycleActions
      enabled={receiver.enabled}
      pending={enable.isPending || forget.isPending}
      onSetEnabled={enable.mutate}
      onForget={forget.mutate}
      disableConfirm={`禁用 receiver ${receiver.receiver_id}？\n\n已下载的对象可继续 ack；不会再被分到新对象。`}
      forgetConfirm={`从注册表中移除 ${receiver.receiver_id}？\n\n仅删除元数据；目标已绑定此接收端的批次将无法 pull。`}
      disableTitle="禁用此接收端"
      forgetTitle="永久从注册表中删除（仅在已禁用时允许）"
    />
  );
}
