# 飞书接入任务注册表（Feishu Channel Adapter）

> **状态**：Plan 阶段任务拆分，**仅设计，不含实现**；`task-details/` 按需后续生成。
> **设计依据**：[`architecture.md`](./architecture.md)（本 Task 列表中的章节引用均指向该文档）。
> **全局约束**：飞书只是 Channel Adapter；不改 Character / World / Inventory / Memory 核心；不建第二套 Chat Pipeline；不建第二套 Session / Memory 系统；不做大规模重构。
> **禁止行为（每个 Task 通用）**：在 `app/channels/**` 内 import `character.*` / `services.memory*` / `services.world*` / `services.state*` / `services.relationship*` / `chains.*` / 直连 `repositories.*`；在 `application` / `services` / `repositories` 内 import `app.channels.*`；硬编码任何密钥。
> **既有文件改动白名单**（超出即视为越界）：`core/settings/__init__.py`、`api/v1/router.py`、`.env.example`、`tests/conftest.py`。

## Task 列表

### FEISHU-001 Feishu 基础配置与认证（P0）

- **ID**：FEISHU-001
- **Priority**：P0
- **Goal**：打通"配置 → 认证 → 可发请求"的最小基础设施：新增配置领域模块 `core/settings/feishu.py`（`FeishuSettings` 组合进 `Settings`，含 §5.1 全部配置项与启用即校验）、通道无关协议骨架 `channels/base.py`、出站客户端 `channels/feishu/client.py` 的**认证子集**（`tenant_access_token` 获取 / 缓存 / 提前刷新）与 HTTP 基础设施（超时、错误分类、退避重试骨架）、错误类型 `channels/feishu/errors.py`。
- **Scope**：
  - 新增：`app/core/settings/feishu.py`、`app/channels/__init__.py`、`app/channels/base.py`、`app/channels/feishu/__init__.py`、`app/channels/feishu/client.py`、`app/channels/feishu/errors.py`。
  - 接线：`app/core/settings/__init__.py`（组合 `FeishuSettings`）、`.env.example`（`FEISHU_*` 空值占位）。
  - **不碰**：路由、`application/**`、`services/**`、`repositories/**`、`models/**`、迁移。
- **Dependency**：无。
- **Acceptance Criteria**：
  1. `FEISHU_ENABLED=false` 时不构造任何 HTTP 客户端、不发起任何网络请求（调用计数 = 0 断言）。
  2. `FEISHU_ENABLED=true` 且 `APP_ID` / `APP_SECRET` / `VERIFICATION_TOKEN` 缺失时，启动阶段抛 `SettingsError`（沿用既有校验惯例）。
  3. 所有配置项均可被环境变量覆盖，默认值与 §5.1 表格逐条一致。
  4. `tenant_access_token`：缓存命中不重复请求；到达 `FEISHU_TOKEN_REFRESH_RATIO` 阈值时提前刷新；并发获取只触发一次真实请求（假传输层请求次数断言）。
  5. 源码中零明文密钥；日志 / 异常信息中不出现 `APP_SECRET` / `ENCRYPT_KEY` / `tenant_access_token`（断言日志输出）。
  6. 出站错误分类可区分"可重试（429/5xx/超时）"与"不可重试（4xx）"。

### FEISHU-002 Webhook 与事件接收（P0）

- **ID**：FEISHU-002
- **Priority**：P0
- **Goal**：建立入站链路：`POST /api/v1/feishu/events` 路由（读原始 body → 解密 → 验签 → 快速 ack）、校验与解析纯函数（`url_verification` challenge、`im.message.receive_v1` 文本事件）、`event_id` 去重（幂等）、群聊/非文本事件安全忽略、ack 与处理解耦（后台任务投递）。
- **Scope**：
  - 新增：`app/api/v1/feishu.py`、`app/channels/feishu/events.py`、`app/channels/feishu/adapter.py`（本 Task 只落地"接收 → 去重 → 投递"骨架与处理入口签名，具体处理体在 003/004 填充）。
  - 接线：`app/api/v1/router.py`（注册 `feishu_router`，1 行）；`tests/conftest.py`（假传输夹具，如需要）。
  - **不碰**：`application/chat_pipeline.py`、`api/v1/chat.py`、`api/v1/schemas.py`、`core/settings/**` 既有模块之外的文件。
  - **不实现**：身份映射、管线调用、回复发送。
- **Dependency**：FEISHU-001。
- **Acceptance Criteria**：
  1. `type=url_verification` 时**原样返回** `challenge`。
  2. `header.token` 不匹配 → `401`；签名不匹配 → `403`；`X-Lark-Signature` 时间戳超出 `FEISHU_SIGNATURE_WINDOW_SECONDS` → `403`；三者在验证通过前**均不触发**任何业务代码（断言处理入口未被调用）。
  3. 加密 body（`{"encrypt": "..."}`）能正确解密；解密失败 → `400` 且不进入解析。
  4. `FEISHU_ENABLED=false` 时该路由返回 `404`（端点不暴露）。
  5. 重复 `event_id` 只处理一次（第二次直接忽略，返回 `200`）。
  6. 群聊（`chat_type != "p2p"`）与非 `text` 消息被忽略，返回 `200`，且不投递处理。
  7. **ack 先行**：处理入口被人为阻塞时，HTTP 响应仍在 3s 内返回 `200`（时序断言），处理在后台完成。
  8. 空/畸形 body、缺少 `header`、`content` 非合法 JSON 等异常输入均不抛 5xx（返回 `400` 或 `200` 并记录）。

### FEISHU-003 Feishu User / Session 映射（P0）

- **ID**：FEISHU-003
- **Priority**：P0
- **Goal**：落地"外部身份 → 内部 User / Session"映射：新增 `channel_identities` 表（迁移 `0036`）、`repositories/channel_identity_repository.py`（单表 CRUD + upsert 幂等）、`services/channel_identity_service.py`（`get_or_create` / 解析业务入口）、`channels/feishu/identity.py`（`open_id → feishu:{open_id}` 派生规则），并提供多用户隔离的可验证保证。
- **Scope**：
  - 新增：`migrations/versions/0036_channel_identities.py`、`app/repositories/channel_identity_repository.py`、`app/services/channel_identity_service.py`、`app/channels/feishu/identity.py`。
  - **不新增**：用户表、会话表、第二套 Memory / Session 系统。
  - **不修改**：`conversations` / `messages` / `memories` / `worlds` 等既有表结构。
- **Dependency**：FEISHU-001。
- **Acceptance Criteria**：
  1. 首次接触（新 `open_id`）自动生成 `internal_user_id = "feishu:{open_id}"` 与 `session_id = "feishu:{open_id}"`，并在 `channel_identities` 落一行。
  2. 重复接触幂等：同一 `(channel, external_id)` 多次调用返回同一 `user_id` / `session_id`，表中仍只有一行；**并发**同一 `external_id`（唯一约束冲突路径）只落一行。
  3. `session_id` 前缀 `feishu:`，与 Web 的 `uuid4` 会话不冲突，且不进 `default_user`。
  4. **隔离断言**：用户 A 与 B 各自 `conversation` / `messages` / `memories` / `worlds`（`home:{user_id}`）/ `relationship` 互不可见——A 写入后以 B 的身份读取为空。
  5. `alembic upgrade head` → `downgrade` 往返成功；ORM 与迁移一致（`tests/integration/test_db_migration.py` 口径）。
  6. `channel_identity_service` 是唯一读写入口；`channels/feishu/identity.py` 不直连 `repositories`（静态断言）。

### FEISHU-004 接入现有 Chat Pipeline（P0）

- **ID**：FEISHU-004
- **Priority**：P0
- **Goal**：把映射后的 `(session_id, user_id, text)` 交给**既有**管线入口 `agent_service.stream_chat`，消费异步事件流并拼接出完整回复文本；保证同会话多轮有序（per-user 串行）与"零新增管线逻辑"。
- **Scope**：
  - 新增 / 填充：`app/channels/feishu/adapter.py`（编排：去重 → 身份 → 并发控制 → 调管线 → 产出回复文本），必要时新增 `app/services/turn_lock.py`（进程内 per-user 串行；若既有可实现则复用）。
  - **不改**：`app/application/chat_pipeline.py`、`app/services/agent_service.py`、`app/api/v1/chat.py`、`app/api/v1/schemas.py`。
  - **不复制**：管线的上下文构建 / 链调用 / 落库 / post_process 任何逻辑。
  - 本 Task 产出"回复文本"，实际出站发送在 005。
- **Dependency**：FEISHU-002、FEISHU-003。
- **Acceptance Criteria**：
  1. 飞书文本事件 → 调 `stream_chat(session_id, user_id, text, llm)` → 累积得到**非空**回复文本；`turn_meta` 事件内容**不进入**回复文本。
  2. 使用 `core/llm_factory.get_llm` 获取实例（`FEISHU_LLM_PROFILE` 为空则走默认 profile），无任何直接构造 LLM 的代码。
  3. **多轮连续**：第二轮对话的上下文包含第一轮（`conversations` / `messages` 续写），且同 `user_id` 的 Memory / World / Relationship 状态延续（集成断言）。
  4. `save_turn` 与 `mode` 写回照常在管线内发生；Adapter **不重复落库**。
  5. 同一 `user_id` 并发消息**串行**处理（顺序断言）；队列超 `FEISHU_SESSION_QUEUE_LIMIT` 时按 §6.2 #12 处理。
  6. 管线异常映射对齐 `api/v1/chat.py` 既有语义（`EmptyLLMResponseError` / `APIStatusError` / 通用异常 → 对应提示文案），且**不写入半成品回复**。
  7. `git diff` 不含 `api/v1/chat.py`、`api/v1/schemas.py`、`application/chat_pipeline.py`（**Web 路径 0 改动**）。
  8. `channels/**` 无对 `character.*` / `services.memory*` / `services.world*` / `services.state*` / `services.relationship*` / `chains.*` / 直连 `repositories.*` 的 import（静态断言）。

### FEISHU-005 发送 AI 回复到飞书（P0）

- **ID**：FEISHU-005
- **Priority**：P0
- **Goal**：完成出站投递：`client.py` 的 `reply`（优先，锚定 `message_id`）/ `send`（降级）实现、文本清洗与规范化、超长切分、可重试失败的退避与幂等防重、发送失败与会话状态解耦。
- **Scope**：
  - 填充：`app/channels/feishu/client.py`（出站发消息）、`app/channels/feishu/adapter.py`（接线出站）、`app/channels/feishu/errors.py`（补充投递类错误）。
  - **不实现**：卡片 / 富文本 / 流式 / 图片 / 主动消息。
- **Dependency**：FEISHU-001、FEISHU-002、FEISHU-004。
- **Acceptance Criteria**：
  1. 回复通过 `POST {FEISHU_API_BASE}/open-apis/im/v1/messages/{message_id}/reply` 发送，`content` 为 `{"text": "..."}`；reply 不可用时按固定策略降级为 `send`（策略二选一，实现期冻结并断言）。
  2. 空回复**不发送**空消息（按 §6.2 #8 固定策略：兜底文案或静默，二选一）。
  3. 超长回复按 `FEISHU_MAX_REPLY_CHARS` 切分为多条**顺序**发送，内容无丢失、无重复（拼接还原断言）；单条仍超限时截断并记录。
  4. `429` / `5xx` / 超时按指数退避重试（有上限）；`4xx` **不重试**；终败记录错误日志且**不抛至上层**。
  5. 以 `message_id` 为幂等键防重复投递（重试场景下同一回复只发出一次，请求次数断言）。
  6. 发送失败时，已落库的 `conversation` / `messages` 保持不变（状态断言）。
  7. 日志与异常中不泄漏 `APP_SECRET` / `ENCRYPT_KEY` / `tenant_access_token`。

### FEISHU-006 错误处理与测试（P1）

- **ID**：FEISHU-006
- **Priority**：P1
- **Goal**：收口错误处理与测试体系：固化 §6.2 全部 13 类错误的处理路径、补齐单元 / 集成 / e2e 测试（零真实飞书网络、零真实 LLM）、加入 `channels/` 依赖边界静态断言与"未启用即零路径"断言、产出人工回调冒烟回归清单与排障可见性。
- **Scope**：
  - 新增 / 收口：`app/channels/feishu/errors.py`；`tests/unit/test_feishu_*.py`、`tests/integration/test_feishu_*.py`、`tests/e2e/test_feishu_webhook.py`；`docs/integrations/feishu/regression-checklist.md`（可选，仅文档）；排障端点可选（如 `api/v1/debug.py` 增只读查询，或复用既有 observability trace）。
  - 测试基建：假飞书传输层（注入 `FEISHU_API_BASE`）+ `core/llm_factory.set_llm(FakeLLM)` + 内存 SQLite。
  - **不引入**：真实飞书调用、真实 LLM 调用。
- **Dependency**：FEISHU-002、FEISHU-003、FEISHU-004、FEISHU-005。
- **Acceptance Criteria**：
  1. §6.2 十三类错误逐条断言：触发条件、HTTP 返回、是否调管线、用户可见结果、是否重试。
  2. 场景矩阵全绿：正常文本 / 空文本 / 超长 / 重复 `event_id` / 群聊 / 非 text / 加密 / 未加密 / 验签失败 / 解密失败。
  3. 多用户隔离回归：两个 `open_id` 并发对话互不串（会话、记忆、世界逐项断言）。
  4. `channels/**` 依赖边界静态断言常驻（禁止 import 列表命中即失败）；反向依赖断言（`application` / `services` / `repositories` 不 import `app.channels`）。
  5. `FEISHU_ENABLED=false` 全链路零路径（网络调用 / token 获取 / 管线调用计数均为 0）。
  6. 全部测试确定性、可 `pytest -m "not slow"` 快速通过；测试文件命名全局唯一（xdist 兼容）。
  7. `docs/integrations/feishu/regression-checklist.md`：人工步骤可执行（配置回调 URL → 发文本 → 收到回复 → 二次对话验证记忆延续 → 群聊不响应 → 关闭开关后端到端静默），含真模型抽查项。

## 依赖图

```text
FEISHU-001 配置 + 认证 + 通道协议
     │
     ├──────────────────────────┐
     ▼                          ▼
FEISHU-002 Webhook / 事件接收   FEISHU-003 User / Session 映射（+迁移 0036）
     │                          │
     └────────┬─────────────────┘
              ▼
FEISHU-004 接入现有 Chat Pipeline（Web 路径 0 改动）
              │
              ▼
FEISHU-005 发送 AI 回复到飞书
              │
              ▼
FEISHU-006 错误处理 + 测试收口（P1，全链收口）
```

- **关键路径（P0 最小闭环）**：`001 → 002 → 003 → 004 → 005`。完成后即具备"飞书发消息 → 角色正常回复 → 多轮状态保持"的完整能力。
- **002 与 003 可并行**（互不依赖，仅共同依赖 001）。
- **006 是收口任务**，必须在 002~005 全部完成后执行；其"§6.2 矩阵"与"边界断言"是 P0 的验收证据来源。

## 提交节奏

- 每 Task 独立 commit（仅在用户明确要求时提交 / 推送），格式 `feat: FEISHU-XXX <中文描述>`。
- 测试按项目约定分级：Focused Test → Module Test → 必要时 Fast Test；不做无差别全量 `pytest`。涉及 `core/settings` 改动时走 Fast Test。
- 每个 Task 收口前检查 `git status`，确认无临时产物入库。
- P0 链（001→005）收口时做一次回归：既有 Web 路径测试零失败（因为该路径零改动，此项应恒为绿）。

## 后续建议生成 Task Detail 的任务

按"接口复杂 / 决策密度高 / 易返工"三条标准排序：

| 优先 | Task | 建议原因 |
|---|---|---|
| 1 | **FEISHU-003** | 唯一涉及 DB schema（迁移 0036）+ 并发幂等 + 隔离不变式；映射规则一旦定错，后续多 Channel 与账号绑定都要返工 |
| 2 | **FEISHU-004** | 管线接入点、并发串行策略、异常语义对齐三处最易踩坑；需要明确"零新增管线逻辑"的落地细节与断言方式 |
| 3 | **FEISHU-005** | 超长切分、幂等防重、失败降级三类边界行为需要逐条冻结（策略二选一的地方必须写明选哪个） |
| 4 | **FEISHU-002** | 验签/解密/去重细节多，但都是可单测的纯函数，接口相对稳定；可延后 |
| — | FEISHU-001 / FEISHU-006 | 结构清晰（配置 + 测试收口），无需单独 Detail |
