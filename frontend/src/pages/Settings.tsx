import { useQuery } from "@tanstack/react-query";
import { API } from "../api";
import { Card } from "../ui";

export function Settings() {
  const info = useQuery({ queryKey: ["orch-info"], queryFn: API.orchestratorInfo });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">设置</h1>

      <Card title="系统信息">
        {info.data ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Info label="Orchestrator 版本" value={info.data.version} />
            <Info label="Python 版本" value={info.data.python_version} />
            <Info label="运行平台" value={info.data.platform} mono />
            <Info label="开发模式" value={info.data.dev_mode ? "开启" : "关闭"} />
            <Info label="数据库路径" value={info.data.db_path} mono />
            <Info
              label="事件保留"
              value={info.data.retain_events_days === 0 ? "永久保留" : `${info.data.retain_events_days} 天`}
            />
            <Info
              label="已删除数据粒保留"
              value={info.data.retain_deleted_days === 0 ? "永久保留" : `${info.data.retain_deleted_days} 天`}
            />
            <Info
              label="保留扫描周期"
              value={info.data.retention_sweep_sec === 0 ? "已禁用" : `${info.data.retention_sweep_sec} 秒`}
            />
            <Info
              label="单 worker 在手上限"
              value={
                info.data.max_inflight_per_worker === 0
                  ? "不限（仅磁盘水位反压）"
                  : `${info.data.max_inflight_per_worker} 条（队列反压）`
              }
              hint="SATHOP_MAX_INFLIGHT_PER_WORKER"
            />
          </dl>
        ) : (
          <div className="py-6 text-sm text-muted">加载中…</div>
        )}
      </Card>

      <Card title="凭证说明">
        <div className="text-sm text-muted leading-relaxed">
          凭证已改为<strong className="text-text">按批次指定</strong>——在「新建任务」对话框里，基于任务包所需的凭证名称填入用户名/密码或 Token。
          凭证随批次落库，随 lease 分发给 worker，一次性使用；不再有全局注册表。
          轮换 = 创建新批次。
        </div>
      </Card>
    </div>
  );
}

function Info(props: { label: string; value: string; mono?: boolean; hint?: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{props.label}</dt>
      <dd className={`mt-1 break-all ${props.mono ? "font-mono text-xs" : "text-sm"}`}>
        {props.value}
        {props.hint && <span className="ml-2 text-xs text-amber-400">（{props.hint}）</span>}
      </dd>
    </div>
  );
}
