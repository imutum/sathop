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
- **可编程预处理** — 用户 bundle 隔离 venv 运行，支持多级计算流水线，核心与数据产品解耦
- **Lease 制任务分发** — 30 分钟自动回收，passive + active 双重保障
- **双后端基建** — 下载器 httpx / aria2c、存储 FS / MinIO，env 开关切换
- **SSE + Web UI** — 实时状态推送，浏览器管理全部任务
- **Prometheus 监控** — `GET /api/metrics`，直接接 Prometheus 即可
- **多架构镜像** — linux/amd64 + linux/arm64，压缩后 80–112 MB

## 快速部署

所有配置通过环境变量传入，一条 `docker run` 即可启动。

### 1. Orchestrator（调度节点）

```bash
docker run -d --name sathop-orch \
  -e SATHOP_TOKEN=your-secret-token \
  -p 8000:8000 \
  -v sathop-data:/app/data \
  ghcr.io/imutum/sathop/orchestrator
```

浏览器访问 `http://<host>:8000/`，输入 Token 登录。

### 2. Worker（计算节点，可多台）

```bash
docker run -d --name sathop-worker \
  -e SATHOP_WORKER_ID=worker-1 \
  -e SATHOP_URL=sathop://your-secret-token@<orchestrator-host>:8000 \
  -e SATHOP_PUBLIC_URL=http://<worker-host>:9000 \
  -p 9000:9000 \
  -v sathop-worker:/app/data \
  ghcr.io/imutum/sathop/worker
```

### 3. Receiver（接收节点）

```bash
docker run -d --name sathop-recv \
  -e SATHOP_RECEIVER_ID=recv-1 \
  -e SATHOP_URL=sathop://your-secret-token@<orchestrator-host>:8000 \
  -v /your/archive:/data/archive \
  ghcr.io/imutum/sathop/receiver
```

### 开始使用

1. 浏览器打开 orchestrator → Token 登录
2. 上传 script bundle（用户处理脚本）
3. 创建 batch，选择 bundle + 填写数据源凭证
4. Worker 自动 lease → 下载 → 处理 → 上传
5. Receiver 自动拉取成品到本地归档

## 环境变量

### Orchestrator

| 变量 | 必填 | 默认值 | 说明 |
|------|:----:|--------|------|
| `SATHOP_TOKEN` | ✓ | | API 鉴权 Token |
| `SATHOP_PORT` | | `8000` | 监听端口 |
| `SATHOP_DB` | | `/app/data/orchestrator.db` | SQLite 路径 |
| `SATHOP_RETAIN_EVENTS_DAYS` | | `30` | 事件日志保留天数（0=永久） |
| `SATHOP_RETAIN_DELETED_DAYS` | | `7` | 已删除 granule 保留天数 |

### Worker

| 变量 | 必填 | 默认值 | 说明 |
|------|:----:|--------|------|
| `SATHOP_WORKER_ID` | ✓ | | 唯一标识 |
| `SATHOP_URL` | ✓ | | `sathop://TOKEN@host:port`（旧分体形式 `SATHOP_ORCH_URL` + `SATHOP_TOKEN` 仍作 fallback） |
| `SATHOP_PUBLIC_URL` | ✓ | | 本节点可达地址（receiver 直连） |
| `SATHOP_CAPACITY` | | `20` | 并发 lease 数 |
| `SATHOP_ARIA2_RPC` | | | aria2c RPC 地址（空=用 httpx） |
| `SATHOP_MINIO_ACCESS_KEY` | | | MinIO AK（空=用本地 FS） |
| `SATHOP_MINIO_SECRET_KEY` | | | MinIO SK |
| `SATHOP_DISK_PAUSE_PCT` | | `0.85` | 磁盘水位暂停阈值 |
| `SATHOP_DISK_RESUME_PCT` | | `0.70` | 磁盘水位恢复阈值 |

### Receiver

| 变量 | 必填 | 默认值 | 说明 |
|------|:----:|--------|------|
| `SATHOP_RECEIVER_ID` | ✓ | | 唯一标识 |
| `SATHOP_URL` | ✓ | | `sathop://TOKEN@host:port`（旧分体形式 `SATHOP_ORCH_URL` + `SATHOP_TOKEN` 仍作 fallback） |
| `SATHOP_STORAGE_DIR` | | `/data/archive` | 容器内归档路径 |
| `SATHOP_POLL_INTERVAL` | | `10` | 轮询间隔（秒） |
| `SATHOP_CONCURRENT_PULLS` | | `4` | 并发拉取数 |

## Docker Compose（生产部署）

Worker 如需 MinIO + aria2c 侧车，可用 `deploy/worker/docker-compose.yml`。完整 compose 模板见 [`deploy/`](deploy/)。

## HTTPS

项目本体只跑 HTTP，TLS 由运维层独立处理。暴露到不可信网络前，请在 orchestrator 前部署你自己的反代（Caddy / Lucky / nginx / 云 LB 任选）终止 TLS。注意反代需关闭 SSE buffering 并放宽长连接 idle timeout，否则 `/api/stream` 实时推送会断。

## CLI 工具

安装包后即可使用（`uv sync` 或 `pip install .`）：

| 命令 | 用途 |
|------|------|
| `sathop-validate-bundle <dir>` | 上传前本地校验 bundle |
| `sathop-upload-bundle <dir> --url sathop://TOKEN@host:port` | 校验 + 打包 + 上传 bundle |
| `sathop-reconcile --url sathop://TOKEN@host:port` | 运维状态报告 |

## Script Bundle

用户处理逻辑打包为 bundle（`manifest.yaml` + 脚本）。Python 依赖可放在 bundle 内 `requirements.txt`（优先），或写在 `manifest.yaml` 的 `requirements.pip` 字段里。上传到 orchestrator 后 worker 自动拉取并在隔离 venv 中执行。

## 开发

```bash
uv sync --all-extras --dev                 # Python 依赖
cd frontend && npm ci && cd ..             # 前端依赖（Vue 3）
.venv/Scripts/python.exe -m pytest         # 测试（~20s）
.venv/Scripts/ruff.exe check . --fix       # lint + auto-fix
```

从源码构建镜像：

```bash
docker build -f deploy/orchestrator/Dockerfile -t sathop/orchestrator .
docker build -f deploy/worker/Dockerfile      -t sathop/worker .
docker build -f deploy/receiver/Dockerfile    -t sathop/receiver .
```

## License

[MIT](./LICENSE)
