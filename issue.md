# Issues

本文件由只读审查模型维护，用于记录项目中发现的问题。  
这里不做最终决策，也不直接修改代码。后续模型会根据这些问题进行排序、决策和修复。

## Summary

- 审查时间：2026-05-11（第三轮增量 — 扫描 CLI 工具、worker 辅助模块、frontend router/composables、orchestrator background/pubsub、shared config）
- 审查范围：全项目 — src/sathop/{shared,orchestrator,worker,receiver,cli}/、frontend/src/、tests/、deploy/、pyproject.toml、Dockerfiles、compose files
- 总问题数：47（修复 7 项 — 2 medium + 5 low）
- 高优先级问题数：10
- 中优先级问题数：22（M-007/M-008 已修）
- 低优先级问题数：11（L-001/L-002/L-003/L-011/L-016 已修）
- 交叉问题数：4
- 本轮修复（2026-05-11）：
  - **M-007** SHA256 统一到 `sathop.shared.hashing.sha256_file`
  - **M-008** 抽取 `sathop.shared.locks.NamedLockRegistry`
  - **L-001** 提取 `BUNDLE_REF_PREFIX` + `format_bundle_ref/parse_bundle_ref` 到 shared.protocol
  - **L-002** 抽取 `detect_wrapper_dir` 到 `sathop.shared.bundle_archive`，双侧调用
  - **L-003** 移除 `SATHOP_VENV_PYTHON` 兼容别名（含 docs/tests）
  - **L-011** 前端 `stripBatchPrefix` 收敛到 `lib/utils.ts`
  - **L-016** `resolve_orch` 缺 env 抛 `RuntimeError` + 描述信息
- 已验证干净的模块：tls.py、stages.py、cleanup.py、_paths.py、progress.py、pubsub.py（已覆盖）、background.py（sweeper 设计良好含竞态防护）、router.ts、useAuthGate.ts、usePermissions.ts、reconcile.py、upload_bundle.py、validate_bundle.py、pull.py（已覆盖）
- 主要风险领域：路径穿越、进程清理、event loop 阻塞、重复代码/概念、测试覆盖缺口、配置安全、暗色模式、静默错误吞没

---

## High Priority

### H-001: Worker agent 在 401 时硬杀进程绕过所有清理逻辑

- 类型：错误处理 / 资源泄漏
- 位置：`src/sathop/worker/agent.py:47-53` `OrchestratorClient._check_auth()`
- 证据：
  ```python
  if r.status_code == 401:
      log.error("orch %s returned 401 — SATHOP_TOKEN mismatch; exiting for container restart", path)
      os._exit(1)
  ```
  `os._exit(1)` 立即终止进程，不执行任何 `finally` 块、`atexit` 处理器、`__del__` 方法或 asyncio 任务清理。
- 问题描述：
  1. `_check_auth()` 在所有 `_post`/`_get` 调用中执行（`_post` 内部），包括 heartbeat、lease、state report 等。任何一次 401 都直接杀进程。
  2. 此时可能留有：部分下载的 `.part` 文件、半成品 venv `.building.<tid>` 目录、活跃的 asyncio handler tasks。
  3. 虽然 docker restart 最终会清理，但数据目录会累积孤儿文件，且磁盘空间可能被耗尽。
  4. 接收端的 `OrchestratorClient`（`receiver/agent.py`）没有这个行为，两个 client 类已经行为分化。
- 长期影响：磁盘空间泄漏、垃圾数据累积、容器反复崩溃重启掩盖根本原因。
- 可能方向：将 401 转为异常由调用方处理（或仅对心跳/租约循环区分对待），避免 `os._exit`；或至少增加退出前的清理步骤。
- 置信度：高

### H-002: Receiver drain watchdog 使用 os._exit(0) 绕过清理

- 类型：资源泄漏
- 位置：`src/sathop/receiver/runtime.py:73,81`
- 证据：
  ```python
  log.info("drain complete — all pulls finished, exiting")
  os._exit(0)    # line 73
  ...
  log.warning("drain timeout ... forcing exit")
  os._exit(0)    # line 81
  ```
- 问题描述：与 H-001 相同模式 — `os._exit(0)` 跳过 `finally`、context manager `__aexit__`、httpx client `aclose()`。虽然 drain 场景下影响较小（进程本来就要退出），但未关闭的 HTTP 连接和临时文件仍然被遗弃。
- 长期影响：连接泄漏（对端 TIME_WAIT 堆积）、临时 `.part-*` 文件残留。
- 可能方向：正常路径用 `asyncio.get_running_loop().stop()` 或抛出 `SystemExit(0)`；超时路径至少尝试 `aclose()` 后再 `os._exit`。
- 置信度：高

### H-003: 两个重复的 OrchestratorClient 类已经行为分化

- 类型：重复代码 / 维护风险
- 位置：`src/sathop/worker/agent.py` 和 `src/sathop/receiver/agent.py`
- 证据：
  - Worker 版有 `_check_auth()` → `os._exit(1)` 逻辑；Receiver 版没有
  - Worker 版有 `_post`/`_get` 包装方法（含 `raise_for_status`）；Receiver 版直接用 `self._client.post/get`
  - 两者都实现了 `register()`、`heartbeat()`、`aclose()`，结构高度相似
- 问题描述：两个类本质上是同一概念（"与 orchestrator 通信的 HTTP client"），但已各自演化出不同行为。任何对错误处理、重试、超时的改进都需要在两边各自实现。
- 长期影响：每增加一个 endpoint，两边都要改；安全/错误处理的修复只在一处生效。
- 可能方向：抽取共享基类或组合模式，worker/receiver 差异通过配置或策略注入。或者至少在 `shared/` 中提供统一的 `OrchClient`。
- 置信度：高

### H-004: add_granules 端点缺少 granule schema 验证

- 类型：输入验证缺失
- 位置：`src/sathop/orchestrator/api/batches.py:212-230`
- 证据：`create` 端点（line 103）对每个 granule 调用 `validate_granule(schema, ...)`（line 146），但 `add_granules`（line 212）直接调用 `_new_granule()` 插入，完全跳过验证。注释和 `batch_transitions` 中也没有任何保护。
- 问题描述：用户可以在批次创建后通过 `POST /api/batches/{id}/granules` 注入格式错误的 granule，worker lease 到这些 granule 后会在处理阶段崩溃。
- 长期影响：数据完整性被破坏；worker 反复失败消耗资源。
- 可能方向：在 `add_granules` 中加载 bundle manifest 和 schema，对每个新 granule 执行 `validate_granule`。
- 置信度：高

### H-005: 9 个源模块完全没有测试覆盖

- 类型：测试缺口
- 位置：
  - `src/sathop/shared/config.py` — URL 解析、token 提取（5+ 分支）
  - `src/sathop/shared/http.py` — bearer header、client 工厂
  - `src/sathop/worker/drain.py` — 信号处理、优雅关闭（含 `os._exit(0)`）
  - `src/sathop/worker/runtime_helpers.py` — 6 个纯函数（`auth_for`, `render_key` 等）
  - `src/sathop/worker/main.py` — 入口点
  - `src/sathop/receiver/main.py` — 入口点
  - `src/sathop/receiver/health.py` — HealthServer 类
  - `src/sathop/cli/reconcile.py` — 138 行 reconcile 逻辑
  - `src/sathop/cli/upload_bundle.py` — zip 构建 + HTTP 上传
- 证据：grep 所有测试文件的 import 语句，以上模块均未被引用。
- 问题描述：这些模块包含关键逻辑（URL 解析决定连接正确性、drain 决定进程退出行为、runtime_helpers 被每个 granule 处理调用），但没有任何测试保护。
- 长期影响：重构或依赖升级后这些路径静默失败。
- 可能方向：优先覆盖 `shared/config.py`（URL 解析多分支）、`runtime_helpers.py`（纯函数易测）、`drain.py`（关键生命周期）。
- 置信度：高

### H-006: 测试中通过 object.__setattr__ 修改 frozen Settings 单例 — 27 个测试文件

- 类型：测试基础设施风险
- 位置：所有使用 `object.__setattr__(settings, ...)` 的 orchestrator 测试文件
- 证据：典型模式：
  ```python
  object.__setattr__(settings, "db_path", tmp_path / "test.db")
  object.__setattr__(settings, "token", "")
  ```
  这出现在 27 个测试文件中。
- 问题描述：
  1. 绕过 frozen dataclass 的不可变性约定
  2. Settings 是模块级单例 — 测试间共享可变状态，pytest-xdist 下会崩溃
  3. 如果 Settings 从 frozen dataclass 重构为其他形式，所有 27 个文件的测试都会静默失败
  4. try/finally 中恢复设置的测试如果在设置恢复前崩溃，状态泄漏到后续测试
- 长期影响：测试基础设施极度脆弱，Settings 重构的成本是 27 个文件的手动修改。
- 可能方向：引入 `monkeypatch.setenv` 或测试用 Settings factory，避免直接修改单例。
- 置信度：高

### H-007: 所有三个 Docker 镜像以 root 用户运行

- 类型：安全
- 位置：`deploy/orchestrator/Dockerfile`、`deploy/worker/Dockerfile`、`deploy/receiver/Dockerfile`
- 证据：三个 Dockerfile 均无 `USER` 指令，CMD 以 root 执行。
- 问题描述：数据管道处理外部凭证和下载 — 以 root 运行意味着任何 bundle 中的恶意代码（虽然不在容器内）、依赖库漏洞、或 worker 的文件系统操作都具有 root 权限。
- 长期影响：安全合规风险；容器逃逸后的影响面最大化。
- 可能方向：创建非 root 用户（如 `app` 或 `sathop`），在 COPY 源码后 `USER app`。
- 置信度：高

### H-008: CI 流程无类型检查步骤

- 类型：CI/CD 缺口
- 位置：`.github/workflows/ci.yml`
- 证据：CI 运行 ruff lint + format check + pytest，但没有 pyright 或 mypy 步骤。`pyrightconfig.json` 存在于仓库中（`reportMissingImports: "error"`），但从未在 CI 中执行。
- 问题描述：类型错误直接流入生产环境而未被检测到。Python 3.13（pyrightconfig 指定）与 Python 3.11（CI/生产实际使用）之间的版本差异会进一步产生误报或漏报。
- 长期影响：类型相关 bug 在 CI 不可见，只能在运行时暴露。
- 可能方向：在 CI 中添加 `pyright` 步骤（或使用 `basedpyright`），并将 `pythonVersion` 对齐到 3.11。
- 置信度：高

### H-009: Shared files 名称存在路径穿越风险

- 类型：安全
- 位置：`src/sathop/worker/shared.py:144`、`src/sathop/worker/shared.py:42`、`src/sathop/orchestrator/bundle_schema.py:118-137`
- 证据：
  ```python
  dest = shared_root / name   # shared.py:144 — name 直接来自 bundle manifest
  ```
  `parse_shared_files` (bundle_schema.py) 只验证 name 是非空字符串，不检查 `../`、路径分隔符或绝对路径。恶意 bundle 可以声明 `shared_files: ["../../../etc/cronjob"]`，worker 的 `_sync_one` 将下载内容写入缓存目录之外。
- 问题描述：攻击者上传恶意 bundle → worker lease 到该 bundle → `ensure()` 调用 `shared_sync.sync()` → `dest = shared_root / "../../../etc/cronjob"` → 文件写入预期目录之外。
- 长期影响：worker 节点文件系统被污染；可能覆盖关键系统文件（取决于 worker 的运行用户权限）。
- 可能方向：在 `parse_shared_files` 中拒绝含 `/`、`\`、`..` 的 name，或在 `_sync_one` 中对解析后的路径做 containment 检查。
- 置信度：高

### H-010: InputSpec.filename 存在路径穿越风险

- 类型：安全
- 位置：`src/sathop/worker/runtime.py:323`
- 证据：
  ```python
  dst = input_dir / spec.filename   # filename 来自 orchestrator lease 响应
  ```
  `InputSpec.filename` 无任何格式约束。虽然 orchestrator 被认为是可信的，但 DB 损坏或被攻破的 orchestrator 可以下发包含 `../../` 的 filename，使 worker 写入任意路径。
- 问题描述：与 H-009 相同模式 — 用户提供的路径段直接拼接到基础目录上，不做 sanitization。
- 长期影响：低概率但高影响 — 需要 orchestrator 先被攻破或 DB 损坏。
- 可能方向：在 worker 端对 `filename` 做防御性验证（拒绝含路径分隔符的值），或使用 `Path.resolve()` + containment check。
- 置信度：中

---

## Medium Priority

### M-001: json_dict_or_empty 和 credential_map 静默吞掉数据损坏

- 类型：错误处理
- 位置：`src/sathop/orchestrator/api/worker_leases.py:44-58`
- 证据：
  ```python
  def json_dict_or_empty(raw):
      try:
          value = json.loads(raw)
      except json.JSONDecodeError:
          return {}
      return value if isinstance(value, dict) else {}
  
  def credential_map(raw):
      try:
          return {k: Credential.model_validate(v) for k, v in json_dict_or_empty(raw).items()}
      except ValueError:
          return {}
  ```
- 问题描述：两层静默失败 — JSON 损坏返回 `{}`，credential 验证失败也返回 `{}`。如果 DB 中 `credentials_json` 损坏，worker 将拿到空凭证，下载失败的原因难以排查。
- 长期影响：数据损坏无法被及时发现，问题定位困难。
- 可能方向：至少加 log.warning；考虑在 lease 时对损坏数据让该 granule 进入 failed 状态而非继续尝试。
- 置信度：高

### M-002: log_event 在 commit 前 publish — SSE 客户端可能看到不存在的 event

- 类型：并发一致性
- 位置：`src/sathop/orchestrator/pubsub.py:54-62`
- 证据：
  ```python
  async def log_event(s, source, message, ...):
      s.add(Event(...))
      publish({"scope": "events"})  # publish BEFORE caller's commit
  ```
- 问题描述：`publish()` 立即发出 SSE 通知，但 Event 行尚未 commit。SSE 客户端收到 nudge 后立即查询 `/api/events` 可能查不到这条 event。进程崩溃时这条 event 永久丢失。
- 长期影响：SSE 流不可靠；事件偶尔"消失"。
- 可能方向：将 `publish` 移到 `commit_and_publish` 之后，或让 `log_event` 返回一个回调由调用方在 commit 后执行。
- 置信度：高

### M-003: SSE stream generator 缺少异常保护

- 类型：健壮性
- 位置：`src/sathop/orchestrator/api/stream.py:28-36`
- 证据：`gen()` 中的 `while True` 循环只捕获 `TimeoutError`。如果 `q.get()` 抛出其他异常（如 `CancelledError`），或 `json.dumps(evt)` 失败（事件包含不可序列化对象），异常直接传播到 starlette，终止 SSE 连接。
- 问题描述：所有连接的 SSE 客户端同时断开。UI 的实时更新静默停止，直到用户刷新页面（或 TanStack Query 的 60s 安全网触发）。
- 长期影响：SSE 不可靠，降低 UI 实时性体验。
- 可能方向：在循环体内加宽泛的 try/except（log + continue），或对事件做 `repr()` 兜底。
- 置信度：中

### M-004: 使用 assert 做运行时校验 — `-O` 下会失效

- 类型：错误处理
- 位置：
  - `src/sathop/orchestrator/background.py:22,73` — `assert db._session_maker is not None`
  - `src/sathop/orchestrator/db.py:284` — `assert _session_maker is not None, "init_db() not called"`
- 证据：Python `assert` 在 `-O`（优化模式）下被编译器移除。这些检查如果失败（`init_db()` 未调用或失败），会触发 `AssertionError`（非 `-O`）或 `AttributeError`（`-O` 下 `None` 对象无属性）。
- 问题描述：生产环境使用 `-O` 时，`db.py` 的 session() 依赖会在 `None._session_maker()` 处抛出晦涩的 `AttributeError`，而非明确的 `init_db() not called` 错误信息。
- 长期影响：故障排查困难；背景任务静默失败。
- 可能方向：将 `assert` 替换为显式的 `if ... is None: raise RuntimeError(...)`。
- 置信度：中

### M-005: Deletable endpoint 存在 N+1 查询

- 类型：性能
- 位置：`src/sathop/orchestrator/api/workers.py:226-232`
- 证据：对每个有 acked object 的 granule，发起一次独立的 `SELECT * FROM granule_objects WHERE granule_id = ?` 查询。
- 问题描述：worker 持有 100 个 granule 时产生 101 次查询。可用单个 `GROUP BY` + `HAVING` 查询替代。
- 长期影响：在大量 granule 场景下请求延迟线性增长。
- 可能方向：用单次 SQL 查询替代 N+1 模式（`COUNT(*) = COUNT(acked_at)` 的 HAVING 条件）。
- 置信度：中

### M-006: urllib.request（同步阻塞）用于文件下载，无法取消

- 类型：并发 / 架构
- 位置：`src/sathop/worker/bundle.py:193-210`、`src/sathop/worker/shared.py:78-149`
- 证据：两个文件都使用 `urllib.request.urlopen()`（同步阻塞 I/O）。`ensure()` 包裹在 `asyncio.to_thread` 中，但底层 `urlopen` 一旦开始就无法从 async 侧取消。
- 问题描述：
  1. orchestrator 不可达或网速极慢时，线程池线程被永久占用
  2. `asyncio.to_thread` 的取消只取消对线程结果的等待，不取消线程内的阻塞调用
  3. 项目已依赖 `httpx`（用于 API 调用），但文件下载却用 urllib — 不一致
- 长期影响：线程池耗尽导致所有 granule 处理停滞；无法实现优雅取消。
- 可能方向：将 bundle/shared 下载迁移到 `httpx.AsyncClient`（与 API 调用统一），利用其 streaming + 超时 + 取消支持。
- 置信度：中

### M-009: 环境变量白名单包含敏感路径目录

- 类型：安全
- 位置：`src/sathop/worker/processor.py:50-83`
- 证据：`_ENV_WHITELIST` 包含 `APPDATA`、`LOCALAPPDATA`、`USERPROFILE`、`HOME`。恶意 bundle 可以读取 `~/.aws/credentials`、`~/.ssh/id_rsa`、云厂商配置等。
- 问题描述：设计意图是提供可用的 shell 环境，但白名单范围过宽。Windows 上 `APPDATA` 包含大量凭证文件，`HOME` 下通常有 `.aws/`、`.config/gcloud/` 等。
- 长期影响：bundle 中的恶意代码可能窃取 worker 节点的云凭证。
- 可能方向：将白名单收紧为仅必要的路径解析变量（`PATH`、`SYSTEMROOT`、`TMP`），其余由 bundle 通过 `manifest.execution.env` 显式声明。
- 置信度：中（取决于 bundle 的信任模型和部署环境）

### M-010: gc_bundles 和 shared delete 在 commit 前操作文件系统

- 类型：事务安全
- 位置：
  - `src/sathop/orchestrator/api/admin.py:138-148` — blob unlink (line 138-144) 仍在 `commit_and_publish` (line 148) **之前**执行
  - `src/sathop/orchestrator/api/shared.py:205-207` — 同上模式
- 证据：blob 文件在事务 commit 前被删除。如果 commit 失败（DB 约束冲突等），文件已删除但 DB 行仍然存在 — 数据不一致。
- 问题描述：后续对已删除 blob 的下载请求返回 500，而 DB 显示 bundle 存在。
- 更新：`ad74096` 将 gc_bundles 路径从裸 `s.commit()` 迁移至 `commit_and_publish()`，但 blob unlink 仍在 commit 之前发生。commit 消息承认 shared.py::delete 的 commit→unlink→publish 顺序是有意为之。
- 长期影响：静默数据损坏。
- 可能方向：先 commit，成功后再删除文件（文件删除失败比 DB 不一致更容易恢复）。
- 置信度：中

### M-011: Compose 文件中使用未固定版本的镜像

- 类型：部署风险
- 位置：`deploy/worker/docker-compose.yml:3,17`
- 证据：`minio/minio:latest` 和 `p3terx/aria2-pro:latest` — 使用 `latest` 标签。
- 问题描述：`latest` 标签随时可能引入不兼容的 API 变更。MinIO 在历史上多次进行过 breaking changes。
- 长期影响：生产环境意外升级导致 pipeline 中断。
- 可能方向：固定到具体版本标签（如 `minio/minio:RELEASE.2024-12-18T00-00-00Z`）。
- 置信度：高

### M-012: bundle blob upload 存在 TOCTOU 竞态

- 类型：并发安全
- 位置：`src/sathop/orchestrator/api/bundles.py:137-140`
- 证据：
  ```python
  if not blob.exists():
      tmp = blob.with_suffix(".zip.part")
      tmp.write_bytes(data)
      tmp.rename(blob)  # raises FileExistsError on Windows if target created between exists() and rename()
  ```
- 问题描述：两个并发上传相同 sha256 的 bundle 请求，可能在 `exists()` 检查和 `rename()` 之间产生竞态。Windows 上 `Path.rename()` 对已存在目标抛出 `FileExistsError`。
- 长期影响：并发上传相同 bundle 时偶发 500 错误。
- 可能方向：使用 `tmp.replace(blob)` 并捕获 `FileExistsError` 后静默成功（内容相同），或用 `os.replace`。
- 置信度：中

### M-013: Orchestrator HEALTHCHECK 硬编码端口 8000

- 类型：部署配置
- 位置：`deploy/orchestrator/Dockerfile:41`
- 证据：`http://127.0.0.1:8000/api/health` — 端口 8000 硬编码。如果 `SATHOP_PORT` 被覆盖，healthcheck 将命中错误端口。
- 问题描述：容器被标记为 unhealthy，触发重启循环。
- 长期影响：非默认端口部署不可用。
- 可能方向：使用 `http://127.0.0.1:${SATHOP_PORT:-8000}/api/health`（在 CMD 或 HEALTHCHECK 中展开环境变量）。
- 置信度：中

### M-014: 测试中存在依赖时序的 sleep

- 类型：测试可靠性
- 位置：
  - `tests/test_worker_resilience.py:134` — `await asyncio.sleep(2.5)` 驱动 2 个心跳周期
  - `tests/test_receiver_pipeline.py:167` — `elapsed < 1.0` 断言在 0.6s 慢任务 + 3 个快任务的总时间
- 证据：硬编码 sleep 在高负载 CI 上可能不够；时间断言在资源竞争时过于激进。
- 问题描述：flaky tests — 在高负载 CI 环境随机失败。
- 长期影响：开发者对 CI 结果失去信任。
- 可能方向：用 `asyncio.Event` 或 `MockClock` 代替 sleep；放宽时间断言。
- 置信度：中

### M-015: pyrightconfig.json 指定 Python 3.13 而 CI 和生产使用 3.11

- 类型：配置不一致
- 位置：`pyrightconfig.json:4` vs `.github/workflows/ci.yml:22` vs `pyproject.toml:5`
- 证据：pyrightconfig 指定 `"pythonVersion": "3.13"`，但 CI 使用 3.11，pyproject.toml 声明 `>=3.11`。
- 问题描述：pyright 可能接受仅在 3.12+ 可用的语法/stdlib 用法，而这些在 3.11 生产环境不可用。反之亦然 — 3.11 上的问题（如某些类型的弃用警告）pyright 不会报告。
- 长期影响：类型检查结果不可信。
- 可能方向：将 `pythonVersion` 对齐为 `"3.11"`。
- 置信度：高

### M-016: MinioStorage.put() 和 delete() 在 event loop 上执行同步阻塞 I/O

- 类型：并发 / 性能
- 位置：`src/sathop/worker/storage.py:95`、`src/sathop/worker/storage.py:101-103`、`src/sathop/worker/runtime.py:385,461-462`
- 证据：
  ```python
  # storage.py:95 — MinioStorage.put()
  self._client.fput_object(self._bucket, object_key, str(src))  # 同步 S3 API 调用
  ```
  `runtime.py:385` 调用 `self.storage.put(out, key)` — 直接在 asyncio event loop 上执行，未包裹 `asyncio.to_thread`。对于 MinIO-over-WAN 部署，S3 上传可能持续数秒到数分钟，期间整个 event loop 被阻塞：心跳停止、lease 停止、其他 granule handler 停止。
- 问题描述：`MinioStorage.put()` 和 `MinioStorage.delete()` 都是同步方法，调用方未将其放入线程。`LocalStorage.put()` 是本地文件移动（几乎瞬时），所以 `LocalStorage` 不受影响。
- 长期影响：MinIO 部署下 worker 的心跳超时，orchestrator 误判 worker 离线，lease 被错误回收。
- 可能方向：将 `storage.put()` 和 `storage.delete()` 改为 async，在 MinioStorage 实现中用 `asyncio.to_thread` 包裹 minio-py 调用；或让调用方统一包裹。
- 置信度：高

### M-017: MinioStorage bucket 创建存在竞态

- 类型：并发
- 位置：`src/sathop/worker/storage.py:89-90`
- 证据：
  ```python
  if not self._client.bucket_exists(bucket):
      self._client.make_bucket(bucket)
  ```
  多 worker 共享同一 MinIO 实例时：两个 worker 同时启动，都检查 `bucket_exists=False`，都调用 `make_bucket`，第二个调用抛出 `BucketAlreadyOwnedByYou` 异常 → worker 启动失败。
- 问题描述：TOCTOU 竞态 — check 和 create 不是原子操作。
- 长期影响：多 worker 部署时偶发启动失败。
- 可能方向：捕获 `BucketAlreadyOwnedByYou` / `BucketAlreadyExists` 异常并静默继续。
- 置信度：中

### M-018: Frontend 存在 5 处死代码路径

- 类型：死代码
- 位置：
  - `frontend/src/main.ts:2,25` — Pinia 注册但零 store
  - `frontend/src/composables/useToast.ts:16-25` — `useMutationToast` 导出但无导入
  - `frontend/src/directives/permission.ts` + `main.ts:28` — `v-permission` 指令注册但无模板使用
  - `frontend/src/env.d.ts:12-18` + `router.ts:53-60` — 路由权限守卫逻辑完整但无路由声明 `meta.permission`
  - 9 个组件使用 `font-display` class 但该 class 未在 Tailwind 配置或 CSS 中定义
- 证据：grep 全项目确认以上符号无引用。
- 问题描述：死代码增加维护负担和构建体积。权限系统尤其浪费 — 完整的 directive + route guard + type augmentation 但从未激活。
- 长期影响：开发者可能误用 `v-permission` 以为它有效；`font-display` 无效让字体回退到默认。
- 可能方向：删除未使用的注册（Pinia、permission directive）和未使用的导出（useMutationToast）；要么实现权限要么删除整个权限框架；在 Tailwind 配置中定义 `font-display` 或从模板中移除。
- 置信度：高

### M-019: Frontend 硬编码 Tailwind 颜色在暗色模式下不兼容

- 类型：UI / 主题一致性
- 位置：`frontend/src/features/batch/components/PipelineHealth.vue:10-22`、`frontend/src/features/batch/components/StateBarChart.vue:8-20`
- 证据：两个组件使用字面量 Tailwind 颜色类（`bg-amber-500`、`bg-sky-500`、`bg-indigo-500`），而项目其他部分使用 `hsl(var(--xxx))` CSS 自定义属性。暗色模式下这些字面量颜色不调整亮度/饱和度，在深色背景上对比度异常。
- 问题描述：PipelineHealth 和 StateBarChart 的柱状图/进度条在暗色模式下颜色刺眼（设计为浅色背景优化的饱和度）。
- 长期影响：暗色模式用户体验不一致。
- 可能方向：改用 CSS 变量 tokens（如 `bg-primary`、`bg-chart-1`）或在 Tailwind 配置中为这些颜色定义暗色变体。
- 置信度：高

### M-020: Frontend 4 个子组件缺少错误状态处理

- 类型：UI 健壮性
- 位置：
  - `frontend/src/features/batch/components/ProgressTimeline.vue` — useQuery 无 error 处理
  - `frontend/src/features/batch/components/StageTimingStrip.vue` — 同上
  - `frontend/src/features/batch/components/GranuleEvents.vue` — 同上
  - `frontend/src/features/batch/components/BatchTimingCard.vue` — 同上
- 证据：这些组件的 `useQuery` 只在模板中检查 `isLoading` 和空数据，不检查 `isError`。API 调用失败时组件静默渲染空白。
- 问题描述：用户看不到任何错误提示 — 数据区域简单地什么都没有。
- 长期影响：网络故障时用户困惑，不知道是正常空状态还是 API 失败。
- 可能方向：为每个组件添加 `isError` 检查并渲染 `<Alert variant="destructive">`。
- 置信度：高

### M-022: _httpx_auth_and_headers 对不完整凭证静默返回无认证

- 类型：错误处理 / correctness
- 位置：`src/sathop/worker/downloader.py:78-87`
- 证据：
  ```python
  if auth.scheme == "basic" and auth.username and auth.password:
      return httpx.BasicAuth(auth.username, auth.password), {}
  if auth.scheme == "bearer" and auth.token:
      return None, {"Authorization": f"Bearer {auth.token}"}
  return None, {}    # ← 静默丢弃：scheme 匹配但字段缺失
  ```
- 问题描述：如果 Credential 配置不一致（如 scheme=basic 但 password=None，或 scheme=bearer 但 token=None），函数返回 `(None, {})`。下载以无认证方式继续 → 服务器返回 401/403 → 错误信息不提示"凭证未应用"。
- 长期影响：凭证配置错误极难排查；操作员可能花费大量时间怀疑服务器端问题。
- 可能方向：对 scheme 匹配但字段缺失的情况至少 log.warning；或在工作流程早期（batch 创建时 / lease 构建时）验证凭证完整性。
- 置信度：高

### M-023: Worker proc.communicate() 无限制读取子进程 stdout/stderr

- 类型：资源管理 / reliability
- 位置：`src/sathop/worker/processor.py:199`
- 证据：
  ```python
  stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
  ```
  `proc.communicate()` 将全部 stdout/stderr 读入内存。orchestrator API 端在持久化时才截断到 16000 字符（`worker_transitions.py:82-84`），但 worker 已先读取了全部内容。
- 问题描述：失控 bundle（无限循环打印、递归错误转储、二进制数据写入 stdout）可生成 GB 级输出 → worker OOM。虽然 bundle 是操作员提供的，但防御深度原则要求 worker 在读取侧也设置上限。
- 长期影响：worker 节点被单个 granule OOM → 所有正在处理的 granule 丢失 → 需要重新 lease。
- 可能方向：使用流式读取（`proc.stdout.read(n)` 循环）并在达到上限后终止子进程；或使用 `subprocess.PIPE` + 带缓冲上限的 `read()`。
- 置信度：中

### M-024: _ensure_columns 迁移无错误处理 — 崩溃循环风险

- 类型：可靠性 / error-handling
- 位置：`src/sathop/orchestrator/db.py:270-273`
- 证据：
  ```python
  sync_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'))
  ```
  无 try/except。如果 ALTER TABLE 失败（DB 锁定、磁盘满、列类型编译异常），异常直接传播到 `init_db()` → orchestrator 启动失败。容器重启后重试同一迁移 → 崩溃循环。
- 问题描述：错误信息不包含表名/列名上下文，排查困难。无重试或跳过逻辑（如列已存在但不匹配类型）。
- 长期影响：生产环境部署新版本时 orchestrator 无法启动。
- 可能方向：用 try/except 包裹单列迁移，log 包含完整上下文（表名、列名、类型）后 re-raise；对 "column already exists" 错误（SQLite 无此错误，但可防御性编码）静默跳过。
- 置信度：中

### M-021: CLI pull.py 未关闭内部 HTTP client — 连接泄漏

- 类型：资源泄漏
- 位置：`src/sathop/cli/pull.py:75-84`
- 证据：
  ```python
  try:
      await r.run()
  finally:
      await r.client.aclose()       # 仅关闭 OrchestratorClient
      # 缺少: await r.aclose()      # 关闭 Receiver._pull_client
  ```
  对比 `receiver/main.py:15-19` — 正常 receiver 入口同时调用 `r.client.aclose()` 和 `r.aclose()`。
- 问题描述：`Receiver._pull_client`（httpx.AsyncClient, max_connections=300）的连接池在退出时未关闭。虽然正常路径下 `Receiver.run()` 永不返回（直到 `os._exit(0)`），但如果 `run()` 在 watchdog 触发前异常退出，连接泄漏。
- 长期影响：连接池无法正常释放（低概率但易修复）。
- 可能方向：在 finally 块中加 `await r.aclose()`。
- 置信度：中

---

## Low Priority

### L-004: list_stuck 对无效 state 返回空列表而非 400

- 类型：API 设计
- 位置：`src/sathop/orchestrator/api/admin.py:48-51`
- 证据：`if state not in NON_TERMINAL: return []` — 静默返回空列表而非错误。
- 问题描述：前端传错 state 字符串时静默失败，掩盖 bug。
- 长期影响：低 — 前端已构建好正确的 state 集合。
- 可能方向：返回 400 Bad Request。
- 置信度：中

### L-005: 没有根级 .env.example 文件

- 类型：文档
- 位置：项目根目录
- 证据：`deploy/<component>/.env.example` 存在，但根目录没有 `.env.example`。`.dockerignore` 忽略 `.env` 意味着用户会在根目录创建 `.env` 用于本地开发，但缺少模板。
- 问题描述：新开发者需要从 deploy 目录的模板自行推导根级 env。
- 长期影响：新手引导摩擦。
- 可能方向：创建根级 `.env.example` 或 README 指向 deploy 目录的模板。
- 置信度：中

### L-006: receiver/worker .env.example 缺少部分环境变量文档

- 类型：文档
- 位置：`deploy/worker/.env.example`、`deploy/orchestrator/.env.example`
- 证据：worker 模板缺少 `SATHOP_PROCESS_CONCURRENCY`、`SATHOP_UPLOAD_CONCURRENCY`、`SATHOP_TLS_CERT`、`SATHOP_TLS_KEY`。orchestrator 模板缺少 `SATHOP_MAX_INFLIGHT_PER_WORKER`、`SATHOP_BUNDLES`、`SATHOP_SHARED`。
- 问题描述：操作员可能不知道这些配置项存在。
- 长期影响：无法充分利用配置项。
- 可能方向：补全 `.env.example` 文件。
- 置信度：中

### L-007: publish-before-commit vs commit_and_publish 模式不统一 — 大部分已解决

- 类型：代码风格
- 位置：仅剩 3 处有意保留的裸 `s.commit()`：
  - `pubsub.py:61` — `log_event()` 内部的 `publish()`（设计上在 commit 前发布 SSE，见 M-002）
  - `shared.py:205` — shared file delete 的 commit→unlink→publish 顺序（与 M-010 关联）
  - `progress.py:33` — progress relay
  - `receivers.py:126` — receiver ack
- 证据：`c7fa317` 和 `ad74096` 已将几乎所有 API 路由迁移至 `commit_and_publish()`。`admin.py` 不再导入裸 `publish`。剩余裸 `s.commit()` 调用均经 commit 消息确认为有意保留。
- 问题描述：剩余裸 commit 各有理由（background sweepers 无 SSE、shared delete 需先 commit 再 unlink、progress relay 为后台任务）。不再是跨文件的不一致问题。
- 长期影响：低 — 剩余模式已文档化。
- 可能方向：持续监控是否可进一步收敛。
- 置信度：高（已改善）

### L-008: background.py 直接访问 db._session_maker 私有属性

- 类型：封装
- 位置：`src/sathop/orchestrator/background.py:22,73`
- 证据：`assert db._session_maker is not None; async with db._session_maker() as s:` — 跨模块访问私有变量。
- 问题描述：`_session_maker` 名义上是模块私有的（下划线前缀），但 background.py 穿透了这一边界。这是因为没有提供非 FastAPI-DI 的 session 获取方式。
- 长期影响：如果 db.py 的 session 管理方式改变，background.py 也需要修改。
- 可能方向：在 db.py 中暴露 `get_session()` 公共函数。
- 置信度：中

### L-009: Worker agent 有 _get 方法但几乎只在 get_deletable 中使用

- 类型：死代码风险
- 位置：`src/sathop/worker/agent.py:61-65`
- 证据：`_get` 方法定义完整（含 `_check_auth` + `raise_for_status`），但仅 `get_deletable` 一个调用者使用它。
- 问题描述：不是 bug，但 `_post` 被广泛使用而 `_get` 几乎不用，表明设计可能不对称。
- 长期影响：无 — 很低。
- 可能方向：无需操作。
- 置信度：低

### L-010: Receiver runtime 存在死方法 _fetch_one

- 类型：死代码
- 位置：`src/sathop/receiver/runtime.py:265-267`
- 证据：`_fetch_one` (Semaphore 包装) 在生产路径中从未调用。生产路径 `_pull_worker` 直接调用 `_fetch_one_inner`。只有测试文件引用此方法。
- 问题描述：该方法存在是为了测试便利（Semaphore-based 并发控制），但实际生产代码已切换到 queue-based 并发模型。为测试保留的生产代码存在维护风险。
- 长期影响：低 — 方法签名变更时测试不会告警（测试调用旧签名）。
- 可能方向：移除 `_fetch_one`，将测试迁移到直接调用 `_fetch_one_inner`。或保留但加注释说明仅供测试。
- 置信度：中

### L-012: CLI 工具使用不一致的参数名

- 类型：API 设计
- 位置：`src/sathop/cli/reconcile.py:41` 和 `upload_bundle.py:66`、`pull.py:34`
- 证据：reconcile.py 使用 `--orchestrator`；upload_bundle.py 和 pull.py 使用 `--orch-url`。两者功能相同（指定 orchestrator URL），但名称不同。
- 问题描述：用户在不同 CLI 工具间切换时需要记住不同的参数名。
- 长期影响：低 — CLI 工具通常由脚本调用，但用户困惑。
- 可能方向：统一为 `--orch-url`（与其他工具一致），保留 `--orchestrator` 为已弃用的别名。
- 置信度：高

### L-013: validate_bundle 对 python -c/-m entrypoint 产生误报

- 类型：验证逻辑缺陷
- 位置：`src/sathop/cli/validate_bundle.py:86-101`
- 证据：entrypoint `python -c "import sys; ..."` 被解析为 `script = "-c"`，然后检查 `bundle_dir / "-c"` 不存在，报告误报错误。
- 问题描述：合法的 Python 内联脚本或模块调用被标记为"entrypoint script 在 bundle 中不存在"。
- 长期影响：低 — 大多数 bundle 使用 `python script.py` 形式。
- 可能方向：在 entrypoint 解析中识别 `-c`、`-m`、`-` 等特殊参数并跳过文件存在检查。
- 置信度：中

### L-014: _kill_and_wait 访问 CPython 私有 _transport 属性

- 类型：可移植性
- 位置：`src/sathop/worker/processor.py:150-153`
- 证据：
  ```python
  transport = getattr(stream, "_transport", None) if stream else None
  if transport is not None:
      transport.close()
  ```
  `_transport` 是 CPython `asyncio` 内部实现细节。在 PyPy 或未来 CPython 版本中可能不存在或行为不同。由 `getattr(..., None)` 保护，不会崩溃，但 Windows ProactorEventLoop 的 ResourceWarning 会重新出现。
- 问题描述：代码通过显式关闭 transport 来抑制 Windows 上的 ResourceWarning。非 CPython 实现中静默失效。
- 长期影响：低 — CPython 占绝对主导地位，且有 `getattr` 兜底。
- 可能方向：以 `try/except` 包裹 `transport.close()`；或在警告过滤器层面抑制 ResourceWarning。
- 置信度：中

### L-015: Aria2Downloader 轮询循环强制最低 2 秒延迟

- 类型：性能
- 位置：`src/sathop/worker/downloader.py:196`
- 证据：
  ```python
  while True:
      await asyncio.to_thread(dl.update)
      ...
      if dl.is_complete:
          return dl.completed_length
      ...
      await asyncio.sleep(2)    # ← 最低 2s 延迟
  ```
- 问题描述：小文件（<1MB）下载可能在 0.5s 内完成，但至少等待 2s 才检测到。大量小文件 granule 的聚合延迟显著。
- 长期影响：低 — aria2c 通常用于大文件；小文件用 HttpDownloader。但无文档说明此折衷。
- 可能方向：对已知小文件或首次 update 后使用更短的睡眠时间；或使用指数递减（0.25 → 0.5 → 1 → 2s）。
- 置信度：高

---

## Cross-Cutting Problems

### C-001: 混合使用三种 HTTP 客户端库

- 涉及范围：全项目
- 共同模式：httpx（async，worker/receiver API 调用）、urllib.request（sync，worker bundle/shared 文件下载）、fetch（browser，前端）
- 代表性位置：`worker/agent.py`（httpx）、`worker/bundle.py`（urllib）、`worker/shared.py`（urllib）、`frontend/src/apiClient.ts`（fetch）
- 问题描述：
  1. urllib 使用是同步阻塞的，靠 `asyncio.to_thread` 包裹 — 无法取消
  2. urllib 不支持 HTTP/2、连接池、流式进度回调（需自己实现）
  3. 项目已依赖 httpx，不需要额外依赖
  4. urllib 的异常类型与 httpx 不同，错误处理路径需要适配
- 长期影响：维护三套 HTTP 错误处理心智模型；文件下载无法利用 async 生态的取消/超时优势。
- 可能方向：统一到 httpx（async 路径）用于所有 HTTP 操作；`ensure()` 改为 async。
- 置信度：高

### C-002: "临时文件 + SHA256 验证 + 原子重命名" 模式在多处独立实现

- 涉及范围：worker downloader、worker storage、worker bundle venv、worker shared sync、receiver puller
- 共同模式：下载到临时文件 → 验证完整性 → 原子重命名到最终位置 → 失败则清理临时文件
- 代表性位置：
  - `downloader.py:91-139` HttpDownloader.fetch（.part 文件 + 断点续传 + 重命名）
  - `storage.py:47-56` LocalStorage.put（shutil.move）
  - `bundle.py:287-303` _ensure_venv（.building.<tid> tmp dir + rename）
  - `shared.py:127-149` _sync_one（tempfile + sha256 verify + replace）
  - `puller.py:126-168` pull_segmented / pull_single（.part-<hex> + verify + replace）
- 问题描述：每个实现稍有不同 — 块大小、错误处理、清理策略。如果有统一的 "atomic download with verification" 原语，可以减少大量重复代码。
- 长期影响：修改或修复这个模式需要在 5+ 个位置分别进行。
- 可能方向：考虑提取通用的 `atomic_download(url, dest, expected_sha256)` 工具，但不强求 — 各场景的差异可能足够大使得统一代价高于收益。
- 置信度：中

### C-003: Paused / pause_requested 命名在三个层面表达不同语义

- 涉及范围：`protocol.py`、`db.py`、`workers.py`、`runtime.py`、前端
- 共同模式：三个 "pause" 概念共存：
  1. `Worker.paused`（db column）— worker 自报的磁盘背压暂停
  2. `Worker.pause_requested`（db column）— 操作员手动设置的暂停标记
  3. `WorkerHeartbeat.paused`（protocol field）— worker 聚合了以上两者的综合状态
- 代表性位置：`protocol.py:97-102,140`、`db.py:67,83`、`workers.py:280-294`
- 问题描述：名称 `paused` 和 `pause_requested` 不足以区分"谁发起的暂停"和"当前是否暂停"。
- 长期影响：新开发者需要读注释才能理解三个 paused 相关字段的区别。
- 可能方向：`paused` → `backpressure_paused`；`pause_requested` → `operator_paused`。需要同步修改 DB 列、协议字段和前端。
- 置信度：中

### C-004: 用户提供的路径段在 3 处未经 sanitization 直接拼接到基础目录

- 涉及范围：`worker/shared.py`、`worker/runtime.py`、`worker/runtime_helpers.py`
- 共同模式：用户或 bundle 提供的字符串（`shared_files.name`、`InputSpec.filename`、`object_key_template` 渲染结果）直接拼接到 `Path` 基础目录上，不使用 `resolve()` + containment check
- 代表性位置：
  - `shared.py:144` — `dest = shared_root / name`
  - `runtime.py:323` — `dst = input_dir / spec.filename`
  - `runtime_helpers.py:53` — `render_key()` 返回的 key 在 `runtime.py:384` 用作 `storage.put(out, key)`
- 问题描述：三处都可以通过 `../` 逃逸基础目录。第 1 处依赖于恶意 bundle manifest（但 bundle 来自用户上传），第 2 处依赖于 orchestrator 被攻破（低概率），第 3 处依赖于 bundle 控制的模板 + meta 数据。
- 长期影响：路径穿越是 OWASP Top 10 问题。即使当前威胁模型下风险较低（orchestrator 可信），防御性编程仍应在 I/O 边界做 containment check。
- 可能方向：在各拼接点统一使用 `(base / segment).resolve()` 并验证结果以 `base.resolve()` 为前缀。同时在输入验证层（bundle_schema、InputSpec 构建）拒绝含路径分隔符的值。
- 置信度：中

---

## Open Questions

### Q-001: bundle ensure() 从 asyncio.to_thread 内调用共享文件同步 — 是否需要独立化？

- 背景：`bundle.py:125` 在 `ensure()` 内部调用 `shared_sync.sync()`。对于使用相同 bundle 的多个 granule，每个 granule 的 `ensure()` 都会触发一次共享文件的 HTTP metadata 请求（即使 sha256 未变，仍然有网络往返）。
- 不确定点：共享文件通常很少（几个 mask/DEM），这种"额外请求"的开销在实践中是否值得优化？
- 为什么重要：如果共享文件列表增长或 orchestrator 延迟高，可能成为瓶颈。
- 建议后续检查方向：在实际部署中测量 `_sync_one` 的耗时分布。

### Q-002: Credential 的 scheme 字段是否需要扩展？

- 背景：`Credential.scheme` 目前只支持 `Literal["basic", "bearer"]`。未来可能有 API key in header、OAuth2 client credentials、AWS SigV4 等需求。
- 不确定点：当前的两种 scheme 覆盖了已知数据源（NASA Earthdata、LADSWeb），是否需要提前设计扩展点？
- 为什么重要：如果需要新 scheme，当前设计需要修改 Pydantic model（破坏 API 兼容性）和两个 downloader 的 auth translator。
- 建议后续检查方向：survey 未来可能接入的数据源认证方式。

### Q-003: pyrightconfig.json 的 pythonVersion=3.13 是故意的吗？

- 背景：pyrightconfig 指定 3.13，但 CI 和 Docker 镜像使用 3.11。`pyproject.toml` 声明 `>=3.11`。
- 不确定点：可能是开发者的本地 Python 版本（3.13）被写入配置，而非项目目标版本。
- 为什么重要：类型检查结果不可信会导致类型错误流入生产。
- 建议后续检查方向：确认团队的标准 Python 版本后对齐。

### Q-004: 项目是否需要端到端集成测试？

- 背景：所有测试使用 mock HTTP server 和 in-memory SQLite 独立运行。没有测试覆盖完整生命周期：orchestrator + worker + receiver 三组件同时运行、bundle 上传 → batch 创建 → lease → download → process → upload → pull → ack → delete。
- 不确定点：docker-compose 环境能否用于 CI 集成测试？成本和收益如何权衡？
- 为什么重要：组件间协议兼容性目前仅靠代码审查保证。
- 建议后续检查方向：评估在 CI 中运行 docker-compose 测试的可行性和时间成本。

---

## Not Issues

### N-001: secrets.token_urlsafe(6) 批次 ID 生成有碰撞风险吗？

- 检查位置：`src/sathop/orchestrator/api/batches.py:107-114`
- 表面疑点：6 字节随机数在大量批次下可能碰撞。
- 为什么暂时不是问题：6 字节 = 48 位 ≈ 2.8×10¹⁴ 组合。即使在百万级批次规模下，碰撞概率也极低（≈ 10⁻²）。且有 10 次重试作为安全网。对于当前规模足够。

### N-002: Worker 的 `paused` 字段聚合了 backpressure + remote_pause，是否混淆了信号？

- 检查位置：`src/sathop/worker/runtime.py:198`
- 表面疑点：`paused=self._pause_lease or self._remote_pause` 将两个不同的暂停原因合并为一个布尔值。
- 为什么暂时不是问题：heartbeat 的目的是告诉 orchestrator "worker 现在不接受新工作"，原因对调度决策不重要。UI 上可以通过 `pause_requested` 列（来自 orchestrator 的响应）区分操作员的手动暂停。

### N-003: `dict.fromkeys(filter(None, scopes))` 的写法是否不必要地晦涩？

- 检查位置：`src/sathop/orchestrator/pubsub.py:50`
- 表面疑点：`filter(None, ...)` 是 Python 2 时代的写法，不如 `filter(bool, ...)` 或 comprehension 直观。
- 为什么暂时不是问题：功能正确；`filter(None, ...)` 在 Python 3 中仍然有效且被广泛使用。属于风格偏好，不影响正确性。

### N-004: `claim_pending_granules` 中每个 granule 逐一查询 batch 是否为 N+1？

- 检查位置：`src/sathop/orchestrator/api/worker_leases.py:89-95`
- 表面疑点：`for granule in rows: batch = await s.get(Batch, granule.batch_id)` — 对每个 granule 发起一次 batch 查询。
- 为什么暂时不是问题：lease 数量受 `capacity` 限制（通常 ≤20），单次 lease 最多 20 次 batch 查询。SQLAlchemy 的 identity map 会缓存同 batch_id 的查询结果，同批次的多 granule 只查一次。性能影响在目前规模下可忽略。

### N-005: `_ensure_columns` 迁移方案的可靠性

- 检查位置：`src/sathop/orchestrator/db.py:256-273`
- 表面疑点：使用 ALTER TABLE ADD COLUMN 做自动迁移，可能是脆弱的方案。
- 为什么暂时不是问题：该方案只做纯增量（新增 nullable 列），不涉及类型变更、重命名或删除。SQLite 的 ALTER TABLE ADD COLUMN 是成熟的操作。列类型通过 SQLAlchemy dialect 编译，在当前简单类型（Integer、Float、Text、Boolean）下是正确的。对于当前项目的演进速度足够。如有复杂迁移需求（列重命名、类型变更），再引入 Alembic。

### N-006: SSE token 在 URL query string 中传递

- 检查位置：`frontend/src/composables/useLiveStream.ts:38`
- 表面疑点：Bearer token 通过 URL query parameter 传递，可能被浏览器历史、服务器日志、代理日志记录。
- 为什么暂时不是问题：`EventSource` API 不支持自定义 HTTP headers，这是浏览器限制。服务端接受 `?token=` 作为 Bearer token 的替代是已知模式。token 仅存储在浏览器的 localStorage 中，且 orchestrator 通常在 localhost 或内部网络运行。如果网络不可信，operator 应通过反向代理终止 TLS。此限制在 CLAUDE.md 中有文档记录。

### N-007: `is_transient_segment_error` 将所有 RuntimeError 视为可重试

- 检查位置：`src/sathop/receiver/puller.py:81`
- 表面疑点：`if isinstance(e, RuntimeError): return True` 范围过宽，可能掩盖编程错误。
- 为什么暂时不是问题：唯一的用户抛出的 RuntimeError 来自 `stream_range` 中的 "short by" 异常（line 106）。重试循环有上限（SEGMENT_MAX_RETRIES=3）和指数退避。非瞬态错误在第 3 次重试后会正确传播。虽然范围宽但不会导致无限重试。
