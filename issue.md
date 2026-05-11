# Issues

本文件由只读审查模型维护，用于记录项目中发现的问题。  
这里不做最终决策，也不直接修改代码。后续模型会根据这些问题进行排序、决策和修复。

## Summary

- 审查时间：2026-05-11（第三轮增量 — 扫描 CLI 工具、worker 辅助模块、frontend router/composables、orchestrator background/pubsub、shared config）
- 审查范围：全项目 — src/sathop/{shared,orchestrator,worker,receiver,cli}/、frontend/src/、tests/、deploy/、pyproject.toml、Dockerfiles、compose files
- 总问题数：2（累计修复 50 项 — 9 high + 23 medium + 14 low + 3 cross；L-007/L-009/C-002 关闭）
- 高优先级问题数：1（H-001/H-002/H-003/H-004/H-006/H-007/H-008/H-009/H-010 已修；H-005 部分覆盖 — 5/9 模块已测）
- 中优先级问题数：0（M-001/M-002/M-003/M-004/M-005/M-006/M-007/M-008/M-009/M-010/M-011/M-012/M-013/M-014/M-015/M-016/M-017/M-018/M-019/M-020/M-021/M-022/M-023/M-024 已修）
- 低优先级问题数：0（L-001/L-002/L-003/L-004/L-005/L-006/L-008/L-010/L-011/L-012/L-013/L-014/L-015/L-016 已修；L-007/L-009 关闭）
- 交叉问题数：1（C-001/C-004 已修；C-002 关闭）
- 已修复（按轮次倒序）：
  - 第 15 轮：
    - **H-005**（续）覆盖两个 CLI 入口：`cli/reconcile.py`（14 tests，`_fmt_age` s/m/h/d 边界 + naive ISO 兼容；`main()` clean / 空状态 / stuck granule / 心跳过期 / 批次错误聚合 / require_token=False 匿名 / 缺 orch-url 异常 / Bearer header 透传与无 token 时省略），`cli/upload_bundle.py`（15 tests，`_should_include` 五种黑名单情形 + `.env.example` 保留；`_build_zip` 缺 manifest / YAML 错 / 字段不全 / 排除项均生效；`main()` happy path + 409 提示 bump version + 4xx 透传 + `--description` 传 query + Bearer header + 目录不存在）。两份测试都用 `httpx.Client` monkeypatch 套 MockTransport 路由，零网络依赖，~0.2s 跑完。548 测试通过（519 + 29），lint clean
  - 第 14 轮：
    - **H-006** `tests/conftest.py` 新增 `patch_settings` fixture：snapshot-then-restore 语义，首次 patch 某字段时记一份原值，fixture teardown 时按记录回滚 — 即使测试 `assert`/异常崩在中途，状态也不会泄漏到下一个测试。这是项目里唯一保留 `object.__setattr__(settings, …)` 的地方。27 个测试文件全部迁移到 `patch_settings(field=value, …)` 调用，函数签名加 `patch_settings` fixture 参数；测试主体里的 try/finally 包装（仅为还原 settings 而设）一并删除（fixture 自动还原）。同时清理 20 个文件里没再用到 `settings` 的 `from sathop.orchestrator.config import settings` 死导入。`ruff check` clean，全部 519 测试通过 — H-006 在不改 Settings 类本身的前提下消除 4 条隐患（frozen 绕过集中、xdist-safe 单写点、Settings 重构成本从 27 文件降为 1 文件、状态泄漏消除）
  - 第 13 轮：
    - **M-019** `PipelineHealth.vue` STAGE 表 + `chips` 数组 + `StateBarChart.vue` TONE 表里所有字面 Tailwind 色阶都成对带上 `dark:` 变体，规律一致：`bg-X-500` → `dark:bg-X-400`、`bg-X-600` → `dark:bg-X-500`、`text-X-600`/`text-X-700` → `dark:text-X-400`（dark slate 上字色 600/700 看不清；bar 500 太刺眼）。status tokens（success/danger）走 CSS 变量已自动切换，无需变动。`npm run build` 通过
    - **M-020** 四个 useQuery 子组件补错误分支：`ProgressTimeline.vue`、`StageTimingStrip.vue`、`GranuleEvents.vue` 用单行内联 `text-2xs text-danger` 与现有 "加载中…" 样式对齐（紧贴上下文，不打断卡片版面）；`BatchTimingCard.vue` 卡片主体大，错误用 `Alert variant="destructive"` 与 Batches/Bundles/Events 页面顶层 useQuery 错误一致。错误文案统一为"加载XX失败：{message}"
  - 第 12 轮：
    - **H-007** 三个 Docker 镜像加非 root 用户 `sathop`（UID/GID 10001，超出系统范围 0-999 和典型 host 范围 1000+）：所有 `uv sync` 仍以 root 跑（cache mount 在 `/root/.cache/uv`），完成后 `chown -R sathop:sathop /app`（receiver 还 `/data`）+ `USER sathop`。三个 compose 加 `user: "${SATHOP_UID:-10001}:${SATHOP_GID:-10001}"` 作 escape hatch — 操作员若 host bind mount 目录 owner 不是 10001，可以 `chown 10001:10001 ./data` 一次，或在 `.env` 设 `SATHOP_UID=$(id -u)` 让容器跑成自己的 UID。三份 `.env.example` 都加注释说明默认值与覆盖方式。健康检查 / 端口绑定 / 入口脚本均无需 root（监听端口 ≥ 1024）；519 测试不变（Docker 不被测试覆盖，纯部署层改动）
  - 第 11 轮：
    - **H-005**（部分）覆盖 3 个最易测的纯函数模块：`shared/config.py`（32 tests，覆盖 `parse_sathop_url` 的 scheme dispatch / token 双 slot / URL 编码 / 缺 token 缺 host / 子路径 / hostname 大小写等所有分支，`resolve_orch` 的 SATHOP_URL 优先 / split form / 缺 env / 空白 url，`cli_resolve_orch` 的 4 个分支 + require_token=False）；`shared/http.py`（10 tests，bearer_headers 形态 + async/sync client base_url/auth/timeout + MockTransport 端到端发送 Bearer header）；`worker/runtime_helpers.py`（26 tests，6 个纯函数 + 常量不变式：`auth_for` 三态 + 警告路径；`processing_failure_message`/`tail_or_none`/`traceback_tail` 截断；`download_progress_detail` total=0/None/数值；`render_key` 内置字段 / meta 覆盖 / KeyError 回退；`PROCESS_OUTPUT_TAIL_CHARS ≥ 4×PROCESSING_FAILURE_TAIL_CHARS` 不变式锁住 M-023 契约）。新增 68 个测试，全部通过；累计 519 测试。剩余 6 个模块（drain.py 信号/CLI 工具/HealthServer/入口点）暴露面更大、需要 subprocess/signal 编排，留待后续轮次
    - **L-007** 已在第 5 轮关闭，归档到 Not Issues（不再占 Open list）
  - 第 10 轮：
    - **H-008** 在 CI 加 `typecheck` job 跑 `uv tool run pyright src`；先把 `pyrightconfig.json` 加 `"include": ["src"]` 收紧扫描范围，并清掉 13 处真实类型问题：`worker/storage.py::serve_static` 抛弃 `**dict[str, object]` 改为显式 kwargs；`admin_readmodels` / `batch_readmodels` / `metrics.py` 共 6 处 `dict((await s.execute(...)).all())` 改成 typed dict-comp；`batches._batch_granule_ids` 用 `list(...)` 包 `Sequence[str]`；`receivers.ack` 把 `obj.failed_pulls` 重赋值前抽出局部变量让 pyright 能 narrow None。`pyright src` 现在 0 error
    - **L-005** 项目根加 `.env.example`，列出三个组件本地 dev 需要的最小变量集，明确指向 `deploy/<component>/.env.example` 作为容器部署的权威模板
    - **L-006** orchestrator `.env.example` 补 `SATHOP_MAX_INFLIGHT_PER_WORKER` 注释；worker `.env.example` 补 `SATHOP_PROCESS_CONCURRENCY` / `SATHOP_UPLOAD_CONCURRENCY` / `SATHOP_TLS_CERT` / `SATHOP_TLS_KEY`（默认注释掉，描述默认值与什么时候打开）
  - 第 9 轮：
    - **M-006** C-001 已用 httpx 替换 urllib，配 30 s/120 s/600 s 显式超时，issue 原描述（线程池被永久占用、urllib 不一致）已不成立；保留同步调用是 ensure() 路径有意为之（一次性，无需取消语义），关闭
    - **M-011** `deploy/worker/docker-compose.yml` 把 `minio:latest` / `aria2-pro:latest` 改为 `${SATHOP_MINIO_TAG:-RELEASE.2024-12-18T13-15-44Z}` / `${SATHOP_ARIA2_TAG:-2024.10.20}`；`.env.example` 加可选覆盖说明 — 默认锁定到已知稳定版，操作员验证过新版后可单点覆盖
    - **M-014** `test_worker_resilience.test_heartbeat_404_triggers_re_register` 把 `sleep(2.5)` 换成 `wait_for` 条件轮询（两条 reply 消费且 register≥1）→ 不再依赖时钟；`test_receiver_pipeline` 流水线阈值从 1.0 s 放宽到 1.4 s（仍能识别 ≥2.4 s 的串行回归），CI slack 从 0.4 s 升到 0.8 s
    - **M-023** `run_bundle` 引入 `_drain_to_cap` / `_communicate_bounded`，每路 stdout/stderr 在 worker 端硬限 64 KB（orch 持久 16 KB 的 4× headroom），超额继续读但丢弃以免子进程在 pipe 上阻塞，结尾追加 `[... truncated]` 标识 — 失控 bundle 不会再 OOM worker
    - **C-002** atomic-download + sha256 verify 模式跨 5 处实现确实存在，但每处差异（断点续传 vs replace、part-tmp 命名、tmp 清理）已超过统一抽象能消除的代码量，issue 本身建议"不强求"。审查清单关闭，未来若三处以上需要同步修改某行为再考虑提取
  - 第 8 轮：
    - **L-010** `receiver.runtime._fetch_one` 死方法删除；13 处测试调用点全部迁移到直接调用 `_fetch_one_inner`（Semaphore(1) 包装本就是 no-op）。`test_receiver_segmented.py` / `test_receiver_heartbeat_stats.py` 顺手清掉只为此方法保留的 `import asyncio`
    - **M-009** `processor._ENV_WHITELIST` 收紧：剔除 `HOME` / `USERPROFILE` / `APPDATA` / `LOCALAPPDATA` / `PROGRAMDATA` / `USER` / `LOGNAME` / `SHELL` — 这些目录是 `~/.aws`、`~/.ssh`、`~/.config/gcloud`、Earthdata cookie jar 的常见位置，bundle 不应默认继承。需要 per-user 配置的 bundle 改走 `manifest.execution.env` 或 batch credentials 显式声明
    - **L-009** `worker.agent._get` 与 `_post` 设计对称性问题原结论即"无需操作"；归档到 Not Issues，Open 列表反映真实工作量
  - 第 7 轮：
    - **M-005** `workers.deletable` 用 `GROUP BY granule_id HAVING count(*) = count(acked_at)` 子查询过滤，单次 SQL 取代 N+1，worker 持有 100 个 granule 时从 101 次查询降为 1 次
    - **M-016** `Storage` Protocol + `LocalStorage` / `MinioStorage` 全部改为 async；`MinioStorage.put/delete` 用 `asyncio.to_thread` 包 minio-py 调用，MinIO over-WAN 上传不再阻塞 event loop。runtime 的两个调用点加 `await`，`test_storage.py` 切到 async 测试
    - **M-024** `db._ensure_columns` 每条 `ALTER TABLE` 加 try/except，失败时 log 完整 `(table, column, type)` 上下文后包装为 `RuntimeError` 重抛 — 迁移失败时操作员能直接定位脏列，而非看一行裸 SQL 错误进入崩溃循环
    - **L-014** `_kill_and_wait` 在 `transport.close()` 周围补 try/except — 非 CPython 运行时 / 未来 API 变更不再 bubble up
    - **L-015** `Aria2Downloader.fetch` 轮询从固定 2 秒改为 0.25 → 0.5 → 1 → 2 秒指数 ramp，小文件下载延迟从 ≥2s 降到 ≤0.25s 首检
  - 第 6 轮：
    - **M-003** SSE generator 在 `q.get()` / `json.dumps` 周围加显式 try/except，`CancelledError` 透传给 starlette，其他异常 log 后写 `: error\n\n` 注释行让连接存活；不可序列化 event 只丢弃单条不掉线
    - **M-012** orchestrator 上传 blob 路径改用 `os.replace`，临时文件加入 PID + 随机 token 后缀，并发上传同 sha 的 bundle 不再在 Windows 上偶发 `FileExistsError`
    - **M-017** `MinioStorage.__init__` 捕获 `BucketAlreadyOwnedByYou` / `BucketAlreadyExists`，多 worker 共享 MinIO 时的 bucket-create 竞态不再使第二个 worker 启动失败
    - **M-021** `cli/pull.py` finally 块补 `await r.aclose()`，与 `receiver/main.py` 对齐，关闭 `Receiver._pull_client` httpx 连接池
    - **L-012** `sathop-reconcile` 的 `--orchestrator` 重命名为 `--orch-url`，与 `sathop-upload-bundle` / `sathop-pull` 统一
    - **L-013** `validate_bundle` 识别 `python -c "..."` / `python -m pkg` / `-` 等以 `-` 开头的 entrypoint 参数并跳过文件存在检查，不再误报 "script does not exist"
  - 第 5 轮：
    - **M-004 / L-008** 暴露 `db.get_session_maker()` 公共 helper：替代 `background.py` 与 `db.session()` 中的 `assert _session_maker is not None`，`-O` 模式下仍报 `RuntimeError("init_db() not called")`；同时移除 background.py 跨模块访问私有属性的封装泄漏
    - **M-002** `log_event` 改为标记 `session.info[_LOG_EVENT_PENDING]`，由 `commit_and_publish` / 新增 `publish_scopes(s, *scopes)` 在 commit 后排空；SSE 客户端不再收到尚未持久化的 event nudge。`background.sweep_expired_leases` / `receivers.ack` 失败分支 / `shared.delete` 三处裸 commit 同步迁移
    - **M-010** `admin.gc_bundles` 改为先 commit_and_publish 再 unlink 孤儿 blob — commit 失败时不再留下"DB 行存在但 blob 已删"的不一致状态。`shared.delete` 的 commit→unlink→publish 顺序本就正确，未改
    - **M-013** Orchestrator Dockerfile HEALTHCHECK 用 `os.environ.get('SATHOP_PORT','8000')` 替代硬编码 8000，自定义端口部署不再被错判 unhealthy
    - **M-015** `pyrightconfig.json` `pythonVersion` 3.13 → 3.11，与 CI/Dockerfile/pyproject 对齐
    - **L-004** `admin.list_stuck` 对无效 state 改为 `HTTPException(400)` 并附允许列表，不再静默返回 `[]` 掩盖前端 bug
  - 第 4 轮：
    - **C-001** urllib → httpx 统一：`shared.http.make_sync_orch_client` 替代 `urllib.request`，`worker/bundle.py::_fetch_from_orch` + `worker/shared.py::_sync_one/prune_orphans` 全部迁移。错误处理/超时/auth 与 async 路径一致。测试切到 `httpx.MockTransport`
    - **M-022** downloader 凭证 scheme 匹配但字段缺失时 `log.warning`（httpx + aria2 两份 auth translator 都加），不再静默无认证下载
    - **M-001** `worker_leases.json_dict_or_empty` / `credential_map` 改为带 context 的 `log.warning`，从静默 `{}` 升级为可追溯的告警（含 granule_id），不影响 lease 流程
  - 第 3 轮：
    - **H-004** add_granules 加 schema 验证；抽出 `_validate_granules_for_bundle` helper，create / add_granules 共用，duplicate / 错误以 422 拒绝
    - **H-009 / H-010 / C-004** 路径穿越统一防护：新建 `sathop.shared.safe_path`（`is_safe_name` 输入边界 + `safe_join` I/O 边界），Pydantic 校验 `InputSpec.filename`，`parse_shared_files` 拒绝含分隔符 / `..` 的名称；worker `runtime.py` 输入下载、`shared.py` 共享写入、`storage.py` LocalStorage put/delete 全用 `safe_join`；附 21 个回归测试
  - 第 2 轮：
    - **H-001 / H-003** 抽取 `sathop.shared.orch_client.OrchClient` 作为基类；401 抛 `AuthTokenInvalid`（BaseException 子类，避免被 `except Exception` 吞），runtime 顶层 `except* AuthTokenInvalid` 转 `SystemExit(1)`，aclose 正常运行
    - **H-002** worker drain + receiver drain 的 `os._exit` 改为 `raise SystemExit(0)`；runtime `except* SystemExit` 让 aclose finally 完成后退出
    - **M-018** 前端死代码清理：移除 Pinia、`useMutationToast`、`v-permission` 指令 + `usePermissions` 系统 + RouteMeta.permission 类型、`font-display` 类（Tailwind 未定义，9 个 template 中无副作用），删除对应 ts/test 文件，从 package.json 移除 pinia
  - 第 1 轮：
    - **M-007** SHA256 统一到 `sathop.shared.hashing.sha256_file`
    - **M-008** 抽取 `sathop.shared.locks.NamedLockRegistry`
    - **L-001** 提取 `BUNDLE_REF_PREFIX` + `format_bundle_ref/parse_bundle_ref`
    - **L-002** 抽取 `detect_wrapper_dir` 到 `sathop.shared.bundle_archive`
    - **L-003** 移除 `SATHOP_VENV_PYTHON` 兼容别名
    - **L-011** 前端 `stripBatchPrefix` 收敛到 `lib/utils.ts`
    - **L-016** `resolve_orch` 缺 env 抛 `RuntimeError` + 描述信息
- 已验证干净的模块：tls.py、stages.py、cleanup.py、_paths.py、progress.py、pubsub.py（已覆盖）、background.py（sweeper 设计良好含竞态防护）、router.ts、useAuthGate.ts、reconcile.py、upload_bundle.py、validate_bundle.py、pull.py（已覆盖）
- 主要风险领域：路径穿越、event loop 阻塞、重复代码/概念、测试覆盖缺口、配置安全、暗色模式、静默错误吞没

---

## High Priority

### H-005: 4 个源模块仍无测试覆盖（原 9 个，第 11/15 轮已覆盖 5 个）

- 类型：测试缺口
- 已覆盖：
  - 第 11 轮：`shared/config.py`（32 tests）、`shared/http.py`（10 tests）、`worker/runtime_helpers.py`（26 tests）
  - 第 15 轮：`cli/reconcile.py`（14 tests）、`cli/upload_bundle.py`（15 tests）
- 仍未覆盖：
  - `src/sathop/worker/drain.py` — 信号处理、优雅关闭（含 `raise SystemExit(0)`）
  - `src/sathop/worker/main.py` — 入口点
  - `src/sathop/receiver/main.py` — 入口点
  - `src/sathop/receiver/health.py` — HealthServer 类
- 问题描述：剩余 4 个模块都涉及进程级编排（signal handler、HTTP server、入口点 argv 解析）；需要 subprocess fixture 或 signal harness。CLI 已闭环覆盖（MockTransport），方法可复用到 worker/receiver main.py（asyncio.run 顶层封装）。
- 长期影响：信号 / 入口点路径若被改坏不会被测试发现。
- 可能方向：drain.py 用 `os.kill(self_pid, SIGTERM)` + asyncio task 验证 SystemExit 传播；health.py 起本地 socket 自检；worker/receiver main.py monkeypatch `Runtime.run` + sys.argv。
- 置信度：高

---

## Cross-Cutting Problems

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

### Q-004: 项目是否需要端到端集成测试？

- 背景：所有测试使用 mock HTTP server 和 in-memory SQLite 独立运行。没有测试覆盖完整生命周期：orchestrator + worker + receiver 三组件同时运行、bundle 上传 → batch 创建 → lease → download → process → upload → pull → ack → delete。
- 不确定点：docker-compose 环境能否用于 CI 集成测试？成本和收益如何权衡？
- 为什么重要：组件间协议兼容性目前仅靠代码审查保证。
- 建议后续检查方向：评估在 CI 中运行 docker-compose 测试的可行性和时间成本。

---

## Not Issues

### N-010: publish-before-commit vs commit_and_publish 模式不统一（原 L-007）

- 检查位置：`src/sathop/orchestrator/pubsub.py`、`background.py`、`api/receivers.py`、`api/shared.py`、`api/progress.py`
- 表面疑点：状态变更 + SSE 推送在不同 endpoint 用了两种模式。
- 为什么不是问题：第 5 轮已收敛 — `log_event` 改为 `session.info` 标记 + commit-time 排空；`background.sweep_expired_leases`、`receivers.ack` 失败分支已迁移到 `commit_and_publish`；`shared.delete` 用 `publish_scopes(s, ...)` 在 commit→unlink→publish 间显式排空 pending events。`progress.py::ingress` 的 bare commit 自带 `publish({"scope": "progress", ...})` 且无 `log_event` 调用，与统一模型不冲突。

### N-008: Worker agent `_get` 与 `_post` 设计对称性（原 L-009）

- 检查位置：`src/sathop/worker/agent.py:61-65`
- 表面疑点：`_get` 仅 `get_deletable` 一个调用者，`_post` 被广泛使用，看起来设计不对称。
- 为什么不是问题：API 当前只暴露一个 GET 端点（deletable），其余路径都用 POST。`_get` 的 `_check_auth` + `raise_for_status` 与 `_post` 对称，新增 GET 端点零成本；不是死代码，是与 `_post` 配对的对称基础设施。

### N-009: atomic-download + sha256 verify 模式跨 5 处独立实现（原 C-002）

- 检查位置：`downloader.py` / `storage.py` / `bundle.py` / `shared.py` / `puller.py`
- 表面疑点：相同思路（tmp + verify + rename）在 5 个文件各写一份。
- 为什么不是问题：每处差异是必要的：HttpDownloader 要 HTTP Range 续传 + 信用 ProgressCb；Receiver puller 是多段并发 + 失败重组；bundle venv 是目录 rename 不是文件；shared.sync 是 tempfile + replace；LocalStorage.put 只 move（无 sha256，由 hash 库统一）。强行抽出 `atomic_download(url, dest, sha)` 会丢失续传/并发段/进度回调等差异化能力，留下的"统一"反而比五份具体代码更难读。审查清单关闭；将来若三处以上需要同步修改某行为再考虑提取。

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
