# SatHop

> 遥感数据加速下载 + 可编程预处理流水线。多节点并行下载、中继加速、多级计算，结果按需拉取。

[![CI](https://github.com/imutum/sathop/actions/workflows/ci.yml/badge.svg)](https://github.com/imutum/sathop/actions/workflows/ci.yml)
[![Release](https://github.com/imutum/sathop/actions/workflows/release.yml/badge.svg)](https://github.com/imutum/sathop/actions/workflows/release.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

```
           ┌──────────────┐   ① 源清单 + 下载任务
           │ orchestrator │──────────────┐
           │  (调度节点)   │              │
           │  + Web UI    │◀─── ② lease │
           │  + SQLite    │              ▼
           └──────┬───────┘      ┌──────────────┐
                  │              │    worker    │   ③ 下载 → 跑 bundle → 本地存储
                  │              │  (计算节点)   │───── MinIO / static HTTP
                  │              └──────┬───────┘
                  │              ④ 成品就位 URL 回报
                  │◀─────────────────────┘
                  │
                  │  ⑤ /api/receivers/pull  →  object URLs
                  ▼
           ┌──────────────┐
           │   receiver   │───── ⑥ 直连 worker 拉字节
           │  (接收节点)  │
           └──────────────┘
```

## Features

- **加速下载** — 单节点 aria2c 多线程加速中转，多 worker 并行下载，吞吐线性扩展
- **可编程预处理** — 用户 bundle 无依赖时复用 worker 当前 Python 环境；声明 pip 依赖时才构建隔离 venv，支持多级计算流水线
- **Lease 制任务分发** — 30 分钟自动回收，passive + active 双重保障
- **双后端基建** — 下载器 httpx / aria2c、存储 FS / MinIO，env 开关切换
- **SSE + Web UI** — 实时状态推送，浏览器管理全部任务
- **热更新** — 代码推送到 GitHub 后，Web UI 一键重启即可更新，无需重建镜像
- **Prometheus 监控** — `GET /api/metrics`，直接接 Prometheus 即可
- **多架构镜像** — linux/amd64 + linux/arm64

## 快速部署

### 1. 启动 Orchestrator

```bash
docker run -d --name sathop-orch \
  --restart unless-stopped \
  -e SATHOP_ROLE=orchestrator \
  -e SATHOP_TOKEN=your-secret-token \
  -p 8000:8000 \
  -v sathop-data:/app/data \
  -v sathop-repo:/app/repo \
  ghcr.io/imutum/sathop/runtime
```

浏览器访问 `http://<host>:8000/`，输入 Token 登录。

### 2. 添加 Worker / Receiver

登录 Web UI 后，在「工作节点」或「接收端」页面点击「接入新节点」，按向导生成部署命令。

Worker 还提供**一键云服务器部署**选项——自动检测公网 IP、生成随机 ID、选择可用端口，适合批量扩容。

### 3. 开始使用

1. 上传 script bundle（用户处理脚本）
2. 创建 batch，选择 bundle + 填写数据源凭证
3. Worker 自动 lease → 下载 → 处理 → 上传
4. Receiver 自动拉取成品到本地归档

### 更新

代码更新不需要重建镜像。推送到 GitHub 后：
- **Orchestrator** — 设置页点「更新并重启」
- **Worker / Receiver** — 节点卡片点「重启」

仅当 `pyproject.toml`（依赖变化）或 `deploy/runtime/`（运行时环境变化）修改时才需重建镜像。

## HTTPS

项目本体只跑 HTTP，TLS 由运维层独立处理。暴露到不可信网络前，请在 orchestrator 前部署反代（Caddy / Lucky / nginx / 云 LB）终止 TLS。反代需关闭 SSE buffering 并放宽长连接 idle timeout，否则 `/api/stream` 实时推送会断。

## CLI 工具

安装包后即可使用（`uv sync` 或 `pip install .`）：

| 命令 | 用途 |
|------|------|
| `sathop-validate-bundle <dir>` | 上传前本地校验 bundle |
| `sathop-upload-bundle <dir> --url sathop://TOKEN@host:port` | 校验 + 打包 + 上传 bundle |
| `sathop-reconcile --url sathop://TOKEN@host:port` | 运维状态报告 |

## 开发

```bash
uv sync --all-extras --dev                 # Python 依赖
cd frontend && npm ci && cd ..             # 前端依赖（Vue 3）
.venv/Scripts/python.exe -m pytest         # 测试（~20s）
.venv/Scripts/ruff.exe check . --fix       # lint + auto-fix
```

## License

[MIT](./LICENSE)
