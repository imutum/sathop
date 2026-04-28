import { useQuery } from "@tanstack/react-query";
import { API } from "../api";
import { Alert, Card, Field, PageHeader } from "../ui";

export function Settings() {
  const info = useQuery({ queryKey: ["orch-info"], queryFn: API.orchestratorInfo });

  return (
    <div className="space-y-6">
      <PageHeader title="设置" description="Orchestrator 当前运行时配置（只读）" />

      {info.data?.auth_open && (
        <Alert tone="warn">
          <span className="font-semibold">未启用 API 鉴权。</span>
          {" "}此 Orchestrator 当前未设置 <code className="font-mono">SATHOP_TOKEN</code>，
          任何能访问网络地址的人都可以调用 <code className="font-mono">/api/*</code> 接口。
          生产环境请在容器环境变量中设置该值后重启。
        </Alert>
      )}

      <Card title="系统信息" description="由 GET /api/orchestrator/info 提供">
        {info.data ? (
          <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2">
            <Field label="Orchestrator 版本">{info.data.version}</Field>
            <Field label="Python 版本">{info.data.python_version}</Field>
            <Field label="运行平台" mono>{info.data.platform}</Field>
            <Field label="开发模式">{info.data.dev_mode ? "开启" : "关闭"}</Field>
            <Field label="数据库路径" mono>{info.data.db_path}</Field>
            <Field label="事件保留">
              {info.data.retain_events_days === 0 ? "永久保留" : `${info.data.retain_events_days} 天`}
            </Field>
            <Field label="已删除数据粒保留">
              {info.data.retain_deleted_days === 0 ? "永久保留" : `${info.data.retain_deleted_days} 天`}
            </Field>
            <Field label="保留扫描周期">
              {info.data.retention_sweep_sec === 0 ? "已禁用" : `${info.data.retention_sweep_sec} 秒`}
            </Field>
            <Field label="单 worker 在手上限" hint="SATHOP_MAX_INFLIGHT_PER_WORKER">
              {info.data.max_inflight_per_worker === 0
                ? "不限（仅磁盘水位反压）"
                : `${info.data.max_inflight_per_worker} 条（队列反压）`}
            </Field>
          </div>
        ) : (
          <div className="py-6 text-sm text-muted">加载中…</div>
        )}
      </Card>

      <Card title="凭证说明">
        <p className="text-sm leading-relaxed text-muted">
          凭证已改为<strong className="text-text">按批次指定</strong>——在「新建任务」对话框里，基于任务包所需的凭证名称填入用户名/密码或 Token。
          凭证随批次落库，随 lease 分发给 worker，一次性使用；不再有全局注册表。
          轮换 = 创建新批次。
        </p>
      </Card>
    </div>
  );
}

