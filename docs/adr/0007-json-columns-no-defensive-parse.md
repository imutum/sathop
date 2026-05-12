# JSON 列用 SQLAlchemy `JSON` 类型，不写自写自防的解析层

Orchestrator 在 `Batch.execution_env` / `Batch.credentials` / `Granule.inputs` / `Granule.meta` / `Bundle.manifest` 这五列上存的都是结构化数据，不是任意文本。它们一律由 Orchestrator 自己写入（Pydantic 模型 `model_dump()` 之后落库），从无外部代码触达。

历史上这些列是 `Text` 类型，写入端 `json.dumps()`、读取端 `json.loads()`；其中 `execution_env_json` 与 `credentials_json` 又额外裹了一层 `json_dict_or_empty` / `credential_map`：失败回退到 `{}` 并 `log.warning`。两个 helper 配着两个专门测试（`test_lease_handles_malformed_*_json`）守着"我们能容忍自己造成的损坏"——但损坏只可能源自 SatHop 自身代码 bug。

现在改为 SQLAlchemy `JSON` 列类型；SQLite 后端底层仍是 TEXT 存储，但 SQLAlchemy 在写入端自动 `json.dumps`、读取端自动 `json.loads`。Python 侧拿到的是 `dict` / `list`，**不可能把非 JSON 值写入这些列**——defensive helper 失去存在依据。

列名保留 `*_json` 后缀以避免 `ALTER TABLE RENAME COLUMN`（`_ensure_columns` 仅支持 additive），Python 属性名去掉后缀（值不是字符串）。形态与 `Worker.operator_paused` ←→ `pause_requested` 这条已有先例对齐。

要锁的原则：**Orchestrator 不应给自己写入的数据做防御性解析**。将来若有人新增一个 `Text` 列存 JSON 并配 `safe_parse_xxx` helper——按本 ADR 拒绝；要么直接用 `JSON` 列，要么承认这列接收外部输入（那是另一个故事，需要在 handler 入口做 Pydantic 校验，不在 DB 层兜底）。

损坏数据的新行为：直接抛 500。这是**正确的**——`Credential.model_validate` 在写入时已通过校验，读出来再失败意味着非平凡损坏，应该响亮失败而不是吞掉让 worker 拿空凭据再去 401。
