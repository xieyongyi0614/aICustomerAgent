# 飞书接入任务注册表（Feishu Channel Adapter）

> **状态**：Plan 阶段任务拆分，**仅设计，不含实现**；`task-details/` 按需后续生成。
> **设计依据**：[`architecture.md`](./architecture.md)（本 Task 列表中的章节引用均指向该文档）。
> **全局约束**：飞书是**双向** Channel Adapter（Inbound + Outbound）；出站同时支持 **Reply**（锚定用户消息）与 **Proactive**（主动开口）两形态；不改 Character / World / Inventory / Memory / Relationship 核心；不建第二套 Chat Pipeline；不建第二套 Session / Memory 系统；**不实现 Autonomy / Scheduler / Life Loop / Proactive Policy / 主动消息触发方**；不做大规模重构。
> **依赖方向铁律（architecture.md §2.2 R1~R5，本次修订新增）**：
> - 核心层（`application` / `services` / `repositories` / `character` / `chains` / `models` / `prompts` / `core`）**可以** import `app.channels.base`（**仅契约**），**不得** import `app.channels.<impl>`（如 `app.channels.feishu`）；
> - `app.channels.<impl>` **不得** import 任何 Autonomy / Life Loop / Scheduler / Policy 模块；
> - `app.channels.base` 必须**零第三方依赖、零 `app.*` 依赖**；
> - `api → channels → application` 单向。
> **禁止行为（每个 Task 通用）**：在 `app/channels/<impl>/**` 内 import `character.*` / `services.memory*` / `services.world*` / `services.state*` / `services.relationship*` / `chains.*` / 直连 `repositories.*` / 任何 Autonomy 模块；硬编码任何密钥。
> **既有文件改动白名单**（超出即视为越界）：`core/settings/__init__.py`、`api/v1/router.py`、`.env.example`、`tests/conftest.py`、**`app/core/db.py`**（FEISHU-003 必需：新增 1 个 ORM 行类；理由见 FEISHU-003 §15.1）、**`api/v1/debug.py`**（FEISHU-006 可选只读排障）、**`pyproject.toml` + `uv.lock`**（FEISHU-001 必需：加入 runtime 依赖 `cryptography`，经 `uv add` 生成，**禁止手工编辑 lock**）。
> **Risk #1 已决策（方案 A）**：引入 `cryptography`，**正式支持** Feishu Encrypt Key —— 包括 AES-256-CBC 解密与协议要求的签名校验。所有 Task 的文档统一按此描述，不得再出现"二选一 / 待决策 / 暂不支持加密"的表述。
> **Risk #2 状态：Deferred，不阻塞当前实现**（出站触发方的 Push/Pull、Registry、组合根、adapter 生命周期一律延后到 Autonomy 落地时决策；本阶段只要求 FEISHU-005 提供可复用的 Outbound 能力）。

## Task 列表

### FEISHU-001 Feishu 基础配置与认证（P0）

- **ID**：FEISHU-001
- **Priority**：P0
- **Goal**：打通"配置 → 认证 → 可发请求"的最小基础设施，并**冻结通道无关契约**：新增配置领域模块 `core/settings/feishu.py`（`FeishuSettings` 组合进 `Settings`，含 §5.1 全部配置项与启用即校验）、通道无关契约 `channels/base.py`（**入站基元** `InboundMessage` / `ChannelIdentity` / `ChannelReply` + **出站契约** `RecipientRef` / `OutboundMessage` / `SendResult` / `ChannelErrorKind` / `ChannelAdapter` Protocol；零第三方依赖）、出站客户端 `channels/feishu/client.py` 的**认证子集**（`tenant_access_token` 获取 / 缓存 / 提前刷新）与 HTTP 基础设施（超时、错误分类、退避重试骨架）、错误类型 `channels/feishu/errors.py`。
- **Scope**：
  - 新增：`app/core/settings/feishu.py`、`app/channels/__init__.py`、`app/channels/base.py`（含出站契约）、`app/channels/feishu/__init__.py`、`app/channels/feishu/client.py`、`app/channels/feishu/errors.py`。
  - 接线：`app/core/settings/__init__.py`（组合 `FeishuSettings`）、`.env.example`（`FEISHU_*` 空值占位）。
  - **runtime 依赖（Risk #1 = 方案 A）**：通过项目既有 `uv` 流程加入 `cryptography` → 改动 `pyproject.toml` + `uv.lock`（`uv add cryptography`，禁止手工改 lock）。本 Task **不实现** Webhook 解密业务，只负责保证 **FEISHU-002 所需的 crypto runtime 依赖已存在且可导入**（含生产 `uv sync --frozen --no-dev` 场景）。
  - **不碰**：路由、`application/**`、`services/**`、`repositories/**`、`models/**`、迁移、任何 Autonomy 模块。
  - **只定义契约、不实现出站行为**：`ChannelAdapter` 的 Feishu 实现（`send`）属 FEISHU-005，本 Task 只把**契约**冻结下来。
- **Dependency**：无。
- **Acceptance Criteria**：
  1. `FEISHU_ENABLED=false` 时不构造任何 HTTP 客户端、不发起任何网络请求（调用计数 = 0 断言）。
  2. `FEISHU_ENABLED=true` 且 `APP_ID` / `APP_SECRET` / `VERIFICATION_TOKEN` 缺失时，启动阶段抛 `SettingsError`（沿用既有校验惯例）。
  3. 所有配置项均可被环境变量覆盖，默认值与 §5.1 表格逐条一致。
  4. `tenant_access_token`：缓存命中不重复请求；到达 `FEISHU_TOKEN_REFRESH_RATIO` 阈值时提前刷新；并发获取只触发一次真实请求（假传输层请求次数断言）。
  5. 源码中零明文密钥；日志 / 异常信息中不出现 `APP_SECRET` / `ENCRYPT_KEY` / `tenant_access_token`（断言日志输出）。
  6. 出站错误分类可区分"可重试（429/5xx/超时）"与"不可重试（4xx）"。
  7. **出站契约冻结（本次修订新增）**：`channels/base.py` 提供 `OutboundMessage`（含 `recipient` / `text` / `reply_ref` / `idempotency_key`）与 `ChannelAdapter` Protocol；`ChannelErrorKind` 为通道无关闭集；`base.py` **零第三方依赖、零 `app.*` 依赖**（静态断言守门）；出站类型中不出现任何飞书特有字段名（`open_id` / `message_id` / `tenant_access_token` 等）。
  8. **crypto runtime 依赖就位（Risk #1 = 方案 A）**：`cryptography` 已进入 `[project].dependencies`（非 dev 组）且 `uv.lock` 已同步；`uv run python -c "from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes"` 可导入；**`channels/base.py` 仍保持零第三方依赖**（crypto 只在 `channels/feishu/` 内使用）。

### FEISHU-002 Webhook 与事件接收（P0）

- **ID**：FEISHU-002
- **Priority**：P0
- **Goal**：建立入站链路：`POST /api/v1/feishu/events` 路由（读原始 body → **验证** → 解密（如加密）→ 解析 → 去重 → 快速 ack）、校验与解析纯函数（`url_verification` challenge、`im.message.receive_v1` 文本事件）、`event_id` 去重（幂等）、群聊/非文本事件安全忽略、ack 与处理解耦（后台任务投递）。
  - **完整 Webhook 验证（Risk #1 = 方案 A 下的正式能力）**：`verification token`（身份归属）+ `X-Lark-Request-Timestamp` 时间戳窗口（防重放）+ **`X-Lark-Signature` 签名校验**（完整性与来源）+ **`Encrypt Key` 场景的 `AES-256-CBC` 解密**（机密性）。**二者职责不同、不可互相替代**（architecture §6.4）：**不得把 verification token 当作签名校验的替代品**。
  - **两种来件都必须支持**：`Encrypt Key` 非空 → 支持**加密事件**；为空 → 接受**未加密事件**（此时按官方协议可执行的校验要素为准，启动时记安全性降级 warning）。
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
  9. **加密路径为正式能力（Risk #1 = 方案 A）**：真实 `cryptography` 实现，确定性单测覆盖"正确密钥解密成功 / 错误密钥失败 / 密文损坏失败 / 解密后能解析真实结构 / 未加密事件同样正常"；**禁用 monkeypatch 假解密**（走真实 crypto path）。
  10. **验证机制不混同**：`verification token`（401）与 `X-Lark-Signature`（403）各自独立断言；时间戳超窗（403）断言；加密事件的**签名校验基于原始 body**（不基于解密后明文）。协议细节以飞书官方文档为最终依据。

### FEISHU-003 Feishu User / Session 映射（P0）

- **ID**：FEISHU-003
- **Priority**：P0
- **Goal**：落地"**双向**身份解析"：新增 `channel_identities` 表（迁移 `0036`）、`repositories/channel_identity_repository.py`（单表 CRUD + upsert 幂等 + 反查）、`services/channel_identity_service.py`（**正向** `resolve` / **反向** `resolve_recipient` 两个业务入口，派生规则在此冻结）、`channels/feishu/identity.py`（`InboundMessage → ChannelIdentity` 纯适配，**不含派生逻辑**），并提供多用户隔离的可验证保证。
- **Scope**：
  - 新增：`migrations/versions/0036_channel_identities.py`、`app/repositories/channel_identity_repository.py`、`app/services/channel_identity_service.py`、`app/channels/feishu/identity.py`。
  - **反向解析（本次修订新增）**：`resolve_recipient(internal_user_id, channel) -> RecipientRef | None`（主动消息的收件人来源，architecture §3.4）；未命中返回 `None`，**不得**从 `session_id` 反推。
  - **派生规则归属**：`f"{channel}:{external_id}"` 放 **services**（通道无关）；`channels/feishu/identity.py` 只组装 `ChannelIdentity`——因为 `services` 不得 import `app.channels.*`（R1/R2）。
  - **接线**：`tests/conftest.py::_REPO_MODULES` 追加新仓储（**必需**，否则测试连真实 PG 挂起）；`app/core/db.py` 新增 1 个 ORM 行类。
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
  7. **反向解析（本次修订新增）**：`resolve_recipient("feishu:ou_A", "feishu")` 返回 `RecipientRef(channel="feishu", external_id="ou_A")`；未知 `internal_user_id` 返回 `None`（不猜、不兜底）；多行时按 `created_at` 最早取（确定性）；**不以** `session_id` 字符串反推。

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

### FEISHU-005 Feishu Outbound Messaging（P0）

- **ID**：FEISHU-005
- **Priority**：P0
- **Goal**：建立**统一的 Feishu Outbound Messaging 能力**，同时支持**用户消息 Reply** 与**未来 Character 主动消息（Proactive）**：实现 `ChannelAdapter.send(OutboundMessage) -> SendResult`（Feishu 侧）、`client.py` 的 Reply / Send 两个飞书 API、文本规范化与超长切分、可重试失败的退避、**两套幂等键**（Reply 用源 `message_id`；Proactive 用调用方提供的 `idempotency_key`）、以及"投递失败与会话状态解耦"。**本 Task 不实现 Autonomy**（只交付出口能力）。
- **Scope**：
  - 填充：`app/channels/feishu/client.py`（Reply / Send 两个 API）、`app/channels/feishu/delivery.py`（出站编排：两形态 + 幂等 + 逐段 + 收口）、`app/channels/feishu/outbound.py`（规范化 + 切分纯函数）、`app/channels/feishu/adapter.py`（接线）、`app/channels/feishu/errors.py`（Feishu 错误 → `ChannelErrorKind` 映射 + 业务码可重试性）。
  - **两条出站路径**：
    - **Reply**：`reply_ref` 存在 → `POST im/v1/messages/{message_id}/reply`（无需收件人解析）
    - **Proactive**：`reply_ref` 为空 → `internal_user_id → channel_identity_service.resolve_recipient → open_id` → `POST im/v1/messages?receive_id_type=open_id`
  - **不实现**：Autonomy / Scheduler / Life Loop / Proactive Policy / 主动消息触发方 / 主动消息推送循环（触发与循环属未来任务）。
  - **不实现**：卡片 / 富文本 / 流式 / 图片 / 文件 / 语音。
- **Dependency**：FEISHU-001（契约 + 认证 + transport）、FEISHU-002（adapter 接线点）、**FEISHU-003（`resolve_recipient` 反向解析）**、FEISHU-004（Reply 形态的文本来源）。
- **Acceptance Criteria**：
  1. **Reply 路径**：`POST {FEISHU_API_BASE}/open-apis/im/v1/messages/{message_id}/reply`，`content` 为 `{"text": "..."}`；`reply_ref` 缺失时**不**降级为"对别的消息 reply"，而是走 Proactive 路径。
  2. **Proactive 路径**：给定 `internal_user_id`，经 `resolve_recipient` 解析到 `open_id` 后经 `POST im/v1/messages?receive_id_type=open_id` 发送；**收件人解析失败（`None`）→ 不发、不猜、记 warning**。
  3. **无锚点且无幂等键 → 拒绝发送**（调用方契约违规，记 error）。
  4. 空/纯空白文本**不发送**空消息（固定为兜底文案策略，静默已否决）。
  5. 超长回复按 `FEISHU_MAX_REPLY_CHARS` 切分为多条**顺序**发送，内容无丢失、无重复（`"".join(parts) == 规范化文本` 断言）；单条仍超限则截断并记录。
  6. `429` / `5xx` / 超时按指数退避重试（有上限）；`4xx` **不重试**；终败记录错误日志且**不抛至上层**（`send` 返回 `ok=False`，不抛异常）。
  7. **两套幂等键**：Reply 用源 `message_id` + 段序号；Proactive 用 `(channel, recipient, idempotency_key)` + 段序号。重复投递同一逻辑消息 → 请求次数不翻倍。
  8. 发送失败时，已落库的 `conversation` / `messages` / `memory` / `world` / `character` / `relationship` 全部保持不变（逐项断言）。
  9. 日志与异常中不泄漏 `APP_SECRET` / `ENCRYPT_KEY` / `tenant_access_token`。
  10. **不 import 任何 Autonomy / Life Loop / Scheduler / Policy 模块**（静态断言）。

### FEISHU-006 错误处理与测试（P1）

- **ID**：FEISHU-006
- **Priority**：P1
- **Goal**：收口错误处理与测试体系：固化 §6.2 全部 **15** 类错误（含新增的收件人解析失败、无锚点无幂等键）的处理路径、补齐单元 / 集成 / e2e 测试（零真实飞书网络、零真实 LLM）、加入**依赖边界静态断言**（R1~R5：核心可依赖 `channels.base` 契约、不得依赖 `channels.<impl>`；`channels.<impl>` 不得依赖 Autonomy；`base.py` 零第三方依赖）与"未启用即零路径"断言、**验证 Proactive 出口能力**（给定 `internal_user_id` 能解析到 `external_id` 并发送）、产出人工回调冒烟回归清单与排障可见性。
- **Scope**：
  - 新增 / 收口：`app/channels/feishu/errors.py`；`tests/unit/test_feishu_*.py`、`tests/integration/test_feishu_*.py`、`tests/e2e/test_feishu_webhook.py`；`docs/integrations/feishu/regression-checklist.md`（可选，仅文档）；排障端点可选（如 `api/v1/debug.py` 增只读查询，或复用既有 observability trace）。
  - 测试基建：假飞书传输层（注入 `FEISHU_API_BASE`）+ `core/llm_factory.set_llm(FakeLLM)` + 内存 SQLite。
  - **不引入**：真实飞书调用、真实 LLM 调用。
- **Dependency**：FEISHU-002、FEISHU-003、FEISHU-004、FEISHU-005。
- **Acceptance Criteria**：
  1. §6.2 **十五**类错误逐条断言：触发条件 / HTTP 返回 / 是否调管线 / 用户可见结果 / 是否重试。
  2. 场景矩阵全绿：正常文本 / 空文本 / 超长 / 重复 `event_id` / 群聊 / 非 text / 加密 / 未加密 / 验签失败 / 解密失败。
  3. 多用户隔离回归：两个 `open_id` 并发对话互不串（会话、记忆、世界逐项断言）。
  4. **依赖边界静态断言常驻（本次修订更新为 R1~R5）**：`app.channels.<impl>`（如 `feishu`）禁止 import `character.*` / `services.memory*|world*|state*|relationship*` / `chains.*` / `repositories.*` / **任何 Autonomy / Life Loop / Scheduler / Policy 模块**；核心层（`application` / `services` / `repositories` / `character` / `chains` / `models` / `prompts` / `core`）**禁止 import `app.channels.<impl>`，但允许 import `app.channels.base`**（仅契约，fail-closed：`app.channels.` 前缀命中且不在 `base` 白名单内即失败）；`channels/base.py` **零第三方依赖、零 `app.*` 依赖**（专项依赖面断言）。
  5. `FEISHU_ENABLED=false` 全链路零路径（网络 / token / 管线 / DB 写 四类计数均为 0）。
  6. 全部测试确定性、可 `pytest -m "not slow"` 快速通过；测试文件命名全局唯一（xdist 兼容）。
  7. `docs/integrations/feishu/regression-checklist.md`：人工步骤可执行（配置回调 URL → 发文本 → 收到回复 → 二次对话验证记忆延续 → 群聊不响应 → 关闭开关后端到端静默），含真模型抽查项。
  8. **Proactive 出口能力验证（本次修订新增）**：不实现 Autonomy，但验证"已知 `internal_user_id` → `resolve_recipient` → 正确 `external_id` → 假传输收到一次 `send`（`receive_id_type=open_id`）"；未知 `internal_user_id` → 零发送；无 `idempotency_key` 的 Proactive → 拒绝发送。

### FEISHU-007 并发与去重硬化（P0，**部分实现**）

- **ID**：FEISHU-007
- **Priority**：P0
- **来源**：[`review-v1.1.md`](./review-v1.1.md)（审核发现 F-01~F-16）
- **状态**：**入站安全修复 + 连发合并已实现**（2026-09-19）；**多实例去重/锁未实现**，为开多 worker 的硬前置。
- **Goal**：收口入站链路的真实缺陷（重放窗口、body 上限、限流/去重顺序、事件循环阻塞、同会话保序、内存表无界、后台任务可观测），并落地「同一用户连发合并」；同时为多实例部署预留去重与串行的外置方案。
- **已实现 Scope**：
  - `channels/feishu/events.py`：`verify_timestamp_freshness` / `verify_event_freshness` / `verify_encrypted_freshness`；`_seen_events` 与 `delivery._delivered` 改 `OrderedDict` 头部批量摘除；`_rate_windows` 摊还 sweep。
  - `channels/feishu/inbox.py`（新增）：`SessionInbox` —— 固定窗口合并 + per-session FIFO 批次链 + 队列背压。
  - `channels/feishu/adapter.py`：`ingest_inbound_message` 入口；`_resolve_identity` 线程下放；锁在首个 `await` 前取得；`_serialized` 引用计数回收；`_get_turn_gate` 全局并发闸门（激活 `feishu_max_concurrent_turns`）；移除 `_session_load` 三件套。
  - `api/v1/feishu.py`：`_read_body` 限长；加密无签名分支的新鲜度校验；去重前置；`spawn_background` 返回值检查；派发入口切换。
  - `application/observability.py`：后台任务异常 done-callback。
  - `core/settings/feishu.py` + `.env.example`：`feishu_max_body_bytes` / `feishu_merge_window_ms` / `feishu_merge_max_messages` / `feishu_merge_max_chars`。
- **未实现 Scope（多实例硬前置，必须在开多 worker 前完成）**：
  1. `feishu_dedupe_ledger` 表（`event_id` 唯一约束）+ 迁移 `0044`，`accept_event` 改 DB 去重。
  2. PG advisory lock 或会话行 `SELECT ... FOR UPDATE`，做跨进程会话串行。
  3. 出站幂等（`delivery._delivered`）落库。
  - ⚠️ 新增仓储必须注册进 `tests/conftest.py::_REPO_MODULES`（含顶部 import），否则测试连真实 PG 挂起。
- **Acceptance Criteria**：
  1. 加密体无签名头且 `create_time` 过期 → 403 且零派发；`create_time` 新鲜 → 200 且正常派发；URL 校验来件（无时间戳、无 `create_time`）→ 放行并记 warning。
  2. 请求体超过 `FEISHU_MAX_BODY_BYTES` → 413 且零派发（`Content-Length` 与实际分块两条路径都受限）。
  3. 重复 `event_id` 不消耗限流配额（阈值 3 时连发 3 条有效事件全部 200）。
  4. 同一 `open_id` 连发在窗口内合并为一轮，文本按到达顺序拼接、锚点取最后一条；窗口内新消息不重置计时；`window=0` 时逐条处理且仍严格按序。
  5. 队列超过 `FEISHU_SESSION_QUEUE_LIMIT` → 回 `overloaded` 兜底文案且不调管线；队列释放后恢复受理。
  6. `FEISHU_MAX_CONCURRENT_TURNS` 被实际消费；超过 DB 连接池容量时启动期记 warning。
  7. 后台任务异常与「无可调度 loop」均有 error 日志。
  8. 去重表/限流表/幂等表规模有界，不随历史事件数线性增长。
  9. 通道边界 AST fail-closed 扫描保持通过（`inbox.py` 只依赖 `app.core` / `app.channels`）。
- **Dependency**：FEISHU-002、FEISHU-004、FEISHU-005。

### FEISHU-009 去重 / 时钟 / 限流正确性硬化（P0+P1，**已实现**）

- **ID**：FEISHU-009
- **Priority**：P0（N-01 / N-02）+ P1（N-03 / N-04）
- **来源**：[`review-v1.2.md`](./review-v1.2.md)（审核发现 N-01~N-10）
- **状态**：**N-01 / N-02 / N-03 / N-04 + 时钟分离已实现**（2026-09-20）；N-05~N-10 与多实例前置未动。
- **Goal**：收口 v1.1 两处修复的遗漏（F-01 的明文路径缺口、F-03 与 F-09 叠加出的消息丢失），并把「时长判断」从 wall clock 解耦到单调钟。
- **已实现 Scope**：
  - `api/v1/feishu.py`：新鲜度闸门由「仅加密分支」提升为**全路径统一**（判据 `freshness_covered_by_signature = bool(encrypt_key and signature)`）；限流由 `429` 改为 `200` + 派发 `adapter.reject_inbound_message`；token 校验统一覆盖所有来件（含加密体解密后的载荷），并区分配置缺失（`FeishuConfigError` + error 日志）与鉴权失败（`FeishuAuthError` + warning 日志）；私聊非文本 / 空白消息经 `_reply_unsupported` 回兜底文案（共用去重与限流闸门）。
  - `channels/feishu/events.py`：拆出 `_mono = time.monotonic` 承担去重 TTL 与限流滑窗；`_assert_within_window` 记录 `skew`；`_timestamp_value` 加 `TIMESTAMP_MAX_ABS` 上界；淘汰改 `popitem(last=False)`；新增 `rate_limit_per_minute()`（`feishu_rate_limit_per_minute` 为 0 时沿用共用键）；抽出共享信封校验 `_envelope` 并新增 `UnhandledMessage` / `parse_unhandled_message`（N-08）。
  - `channels/feishu/delivery.py`：`_claim_delivery` / `_release_delivery` 原子占位（删 `_already_delivered` / `_mark_delivered`）；**发送抛异常时也回滚占位**；幂等窗口改走单调钟 `_mono`；新增 `_idempotency_ttl_seconds()`（`feishu_outbound_idempotency_ttl_seconds` 为 0 时沿用入站去重 TTL）。
  - `channels/feishu/adapter.py`：新增 `reject_inbound_message` + 共享 `_reply_overloaded`；新增 `reply_unsupported_message`（N-08）；`FALLBACK_TEXTS` 增 `unsupported`；并发容量校验按 `feishu_max_concurrent_turns × feishu_instance_count` 折算。
  - `core/settings/feishu.py` + `.env.example`：新增 `feishu_rate_limit_per_minute` / `feishu_outbound_idempotency_ttl_seconds` / `feishu_instance_count`（前两者允许 0 = 沿用共用键；后者须 ≥ 1）。
- **Acceptance Criteria**：
  1. 限流命中 → `200` + `overloaded` 兜底文案；**飞书重投同一 `event_id` 后用户仍收到该文案**，消息不丢（N-01）。
  2. 明文 / 空 `Encrypt Key` / 缺签名头三种组合下，陈旧 `create_time` 或陈旧时间戳头 → `403` 且零派发；新鲜事件 → `200` 且正常派发（N-02）。
  3. wall clock 回拨时，去重表仍按 TTL 淘汰、限流窗口仍正常排空、出站幂等条目仍会过期（单调钟）。
  4. 并发调用同一出站幂等键只投递一次；**发送返回失败与发送抛异常两条路径都能回滚占位并可重试**（N-03）。
  5. 超长时间戳头（含负数、超 20 位）→ `403`，不产生未捕获 `OverflowError` / 500（N-04）。
  6. 新鲜度拒绝时日志含 `skew`，可与 NTP 漂移建立联系。
  7. 加密体解密后缺 `token` → `401` 且零派发；token 未配置 → error 级日志（与鉴权失败的 warning 可区分）（N-06 / N-07）。
  8. `feishu_max_concurrent_turns × feishu_instance_count` 超过 DB 连接池容量 → 首次建闸门时记 warning（N-05）。
  9. 三个新配置键：0 值语义（沿用共用键）与 ≥ 1 校验均有断言；`FEISHU_RATE_LIMIT_PER_MINUTE` 非 0 时不受 Web 侧阈值影响（N-09 / N-10）。
  10. 私聊非文本 / 空白消息 → `200` + 一句「我目前只能读文字哦～」，**零派发**；同一 `event_id` 重投只回一次；限流命中时不回；群聊与非消息事件完全不回；缺回复锚点不回（N-08）。
- **行为变更登记**：入站限流 `429 → 200 + 兜底文案`（用户可见）；明文来件开始受新鲜度窗口约束（窗口 = `FEISHU_SIGNATURE_WINDOW_SECONDS`，默认 300s）；**加密体缺内层 token 由「放行」改为 `401`**（此前 `解密成功但明文结构非法 → 200` 的契约收窄为「token 合法但结构非法 → 200」）；**私聊非文本 / 空白消息由「静默忽略」改为「回一句兜底文案」**（N-08，用户可见）。
- **未实现 Scope**：无（N-01~N-10 全部处置完毕；多实例全套外置仍按 v1.1 §5.1 作为独立前置）。
- **Dependency**：FEISHU-002、FEISHU-007。

### FEISHU-010 入站去重落库（多实例硬前置之一，**已实现，默认关闭**）

- **ID**：FEISHU-010
- **Priority**：P1（多实例前置；单实例下无行为变化）
- **来源**：`review-v1.1.md` §5.1 第 1 项、`review-v1.2.md` §2.1
- **状态**：**已实现**（2026-09-20），由 `FEISHU_DEDUPE_PERSISTENT_ENABLED` 控制，**默认关闭**。
- **Goal**：把 `event_id` 去重从进程内表落到有 WAL 持久化的存储，使判定在多 worker / 多实例间共享，消除「同一 `event_id` 被每个实例各受理一次」。
- **已实现 Scope**：
  - `migrations/versions/0050_feishu_dedupe_ledger.py` + `app/core/db.py::FeishuEventRow`：`feishu_dedupe_ledger(event_id PK, received_at)` + `received_at` 索引（链尾 `0049 → 0050`）。
  - `app/repositories/feishu_dedupe_ledger_repository.py`：`claim`（先摘除同 id 的过期行再插入，`IntegrityError` 判定）/ `purge_before` / `exists`。
  - `app/services/feishu_dedupe_service.py`：TTL 折算、**fail-open**、每 `PURGE_EVERY=256` 次成功占位做摊还清理。
  - `app/api/v1/feishu.py`：`_claim_event()` 按配置分派内存表 / DB 路径（DB 经 `asyncio.to_thread`）。
  - `app/core/settings/feishu.py` + `.env.example`：`feishu_dedupe_persistent_enabled`（默认 `false`）。
  - `tests/conftest.py`：`feishu_dedupe_ledger_repository` 注册进 `_REPO_MODULES`。
- **Acceptance Criteria**：
  1. 关闭时行为与升级前完全一致（仍走进程内表，`events._seen_events` 有记录）。
  2. 开启时清空进程内表后重投同一 `event_id` 仍被判重（跨进程判定）；且 `events._seen_events` 保持为空。
  3. **对照组**：关闭时清空进程内表后同一 `event_id` 会被再次受理（证明缺口真实存在、且用例非空过）。
  4. 存储故障时**放行**并记 `fail-open` warning（不得丢消息）。
  5. 过 TTL 后同一 `event_id` 可再次受理（与进程内表语义一致）。
  6. 摊还清理：仅每 256 次成功占位触发一次 `purge_before`；重复事件不触发；清理失败不影响本次判定。
  7. 通道边界 AST fail-closed 扫描保持通过（`app/channels/**` 不得 import `app.repositories`）。
- **未实现 Scope（多实例前置的剩余两项）**：跨进程会话串行、出站幂等落库（见 architecture §7.3 第 2/3 项）。
- **Dependency**：FEISHU-002、FEISHU-007。

### FEISHU-011 跨进程会话串行（多实例硬前置之一，**方案 C2 已实现**）

- **ID**：FEISHU-011
- **Priority**：P1（多实例前置；单实例下无影响）
- **来源**：`review-v1.1.md` §5.1 第 2 项、`review-v1.2.md` §2.1 / §7.10
- **状态**：**已实现**（2026-09-20）。方案 C，形态选定 **C2 轻量 router**（`POST /api/v1/feishu/ingress/events`）；运维侧仅剩「把飞书回调地址改指向 router + 配置实例 URL 列表」。五方案对比见 [`multi-instance-options.md`](./multi-instance-options.md)，三形态对比与 C1 排除理由见 [`ingress-routing-options.md`](./ingress-routing-options.md)。
- **Goal**：让「同一 `session_id` 的轮次在任意实例间串行」，消除多实例下同会话消息交错与状态竞态写。方案 C 的做法是**不做分布式锁**，而是让入口把同会话事件恒定送到同一实例，于是进程内 `asyncio.Lock` 就够用。
- **已实现 Scope（应用侧契约）**：
  - `channels/feishu/shards.py`：分片算法 `crc32(open_id) % FEISHU_INSTANCE_COUNT`（标准库 `zlib.crc32`，跨语言可实现）、`owns()`、错分片抽样留痕（每 100 次一条 error，含期望分片与实例下标）。
  - `core/settings/feishu.py`：`feishu_instance_index`（须 `< count`）；**多实例就绪契约** —— `enabled=true` 且 `count>1` 时必须同时声明 `feishu_ingress_sharded_routing_enabled` 与 `feishu_dedupe_persistent_enabled`，缺一即 `SettingsError`。
  - `api/v1/feishu.py`：`_owns_shard()` 归属校验，**在去重之前**判定；非本分片 → **503**（可重试）并抽样记 error。非文本兜底路径同样受检；challenge 无 `open_id` 不检。
  - `tests/unit/test_feishu_shards.py`：**golden 值锁定算法**（算法一改即红，提醒同步改 ingress）、分布均匀性、跨调用稳定、抽样留痕。
  - `api/v1/feishu_ingress.py`：**C2 router 端点**——限长读体 → 解密（复用 `events.decrypt`）→ 取 `open_id` → `shards.shard_of` → 转发**原始 body 与原始签名头** → 原样回传下游响应。**不做鉴权决策**（校验全在下游）、**失败不自行改投**（503 让飞书重投）、取不到 `open_id` 时固定 shard 0。
  - `api/v1/feishu_http.py`：与 webhook 共用的 `read_body_limited()` / `reject()`。
  - `core/settings/feishu.py`：`feishu_router_enabled` / `feishu_router_instance_urls`（个数须等于 `FEISHU_INSTANCE_COUNT`，顺序即分片下标）/ `feishu_router_timeout_seconds`。
  - `tests/unit/test_feishu_ingress_router.py`：14 用例（分片选择、原始 body/签名头转发、不鉴权、无 open_id → shard 0、无密钥/解密失败 → shard 0、加密体按解密后 open_id 分流、超限 413、下游响应原样回传、传输失败 503 且零改投）。
- **Acceptance Criteria（应用侧）**：
  1. 单实例（`count=1`）时归属校验恒为真，行为与升级前完全一致。
  2. `count>1` 且 `index` 为错误分片 → **503** 且零派发、零出站。
  3. 归属校验在去重**之前**：错误分片的拒绝不落去重账，故重投到正确实例时仍能被处理（不被去重表吞掉）。
  4. `count>1` 且未声明 ingress 分流 / 未开跨进程去重 → 启动期 `SettingsError`（信息点名缺哪一项，且不含凭据明文）。
  5. `feishu_instance_index >= feishu_instance_count` → `SettingsError`。
  6. challenge（无 `open_id`）不受归属校验影响，任何实例都能应答。
  7. 通道边界 AST fail-closed 扫描保持通过（`shards.py` 只依赖标准库）。
- **未实现 Scope（运维侧）**：① 飞书回调地址改指向 `/api/v1/feishu/ingress/events`；② `FEISHU_ROUTER_INSTANCE_URLS` 按实例下标顺序配置；③ router 与所有实例的 `FEISHU_ENCRYPT_KEY` 保持一致；④ **翻开关前验证分流真的生效**（否则事件大量落错分片 → 503 → 飞书重投 → 重试风暴）。
- **相关**：出站幂等落库见 **FEISHU-012**（已实现）。
- **Dependency**：FEISHU-010（去重落库，已完成）、FEISHU-007。

### FEISHU-012 出站投递幂等落库（多实例硬前置之一，**已实现，无开关**）

- **ID**：FEISHU-012
- **Priority**：P1（多实例前置；单实例下无行为变化）
- **来源**：`review-v1.1.md` §5.1 第 3 项、`review-v1.2.md` §7.10
- **状态**：**已实现**（2026-09-20），**无开关**——跨进程幂等是必需能力，由组合根在飞书启用时无条件安装。
- **Goal**：把出站投递的幂等占位从进程内表落到持久化存储，使判定在多 worker / 多实例间共享，消除「同一逻辑消息被每个实例各投一次（重复回复用户）」。
- **已实现 Scope**：
  - `migrations/versions/0051_feishu_deliveries.py` + `core/db.py::FeishuDeliveryRow`：`feishu_deliveries(idempotency_key PK, delivered_at)` + `delivered_at` 索引（链尾 `0050 → 0051`）。
  - `repositories/feishu_delivery_ledger_repository.py`：`claim`（先摘除该键的过期行再插入，`IntegrityError` 判定）/ `release` / `purge_before` / `exists`。
  - `services/feishu_delivery_ledger_service.py`：TTL 折算、**fail-open**、每 `PURGE_EVERY=256` 次成功占位做摊还清理；对外是 **async API**（DB 调用经 `asyncio.to_thread` 下放，不阻塞事件循环）。
  - `channels/feishu/delivery.py`：新增可注入 seam `set_persistent_idempotency()` / `clear_persistent_idempotency()`；`_claim_delivery` / `_release_delivery` 改为 async 并**只走注入的持久化实现**（原进程内表 `_delivered` / `_evict_delivered` / `reset_delivery_state` 已删除——保留它等于给持久化路径留一个可被静默绕过的隐式开关）。
  - `app/main.py`：组合根在 `feishu_enabled` 分支内**无条件**安装 hook（通道层不得 import `app.repositories`）。**无开关**。
  - `tests/conftest.py`：`feishu_delivery_ledger_repository` 注册进 `_REPO_MODULES`；新增 autouse 夹具 `_persistent_outbound_idempotency` 与生产一致地安装 hook。
  - ⚠️ **并发用例必须用独立连接**：conftest 的内存 SQLite 用 `StaticPool` 共享单连接，复现不出「两个实例各占一次」的竞态。相关用例改用文件库 + `NullPool`（见 `review-v1.2.md` §7.15）。
- **Acceptance Criteria**：
  1. 占位判定**始终**落在 `feishu_deliveries`（无开关、无双路径）。
  2. 卸载 hook 再安装（等价于实例重启、进程内状态清零）后，同一键仍判重。
  3. **跨连接并发**：两个线程各用独立连接占位同一键，**恰一个**成功（唯一约束裁决）。
  4. 存储故障时**放行投递**并记 `fail-open` warning（不得让用户收不到回复）。
  5. `release` 回滚后同一键可再次占位（发送失败重试不被自己的幂等表挡死）。
  6. 过 TTL 后同一键可再次投递（长时间后的重试不应被永久挡住）。
  7. 摊还清理：仅每 256 次成功占位触发一次 `purge_before`；重复占位不触发；清理失败不影响本次判定。
  8. **hook 未安装属配置缺陷**：记一次 `error` 后放行发送，且该告警只记一次（不刷日志）。
- **Dependency**：FEISHU-005、FEISHU-011。

## 依赖图

```text
FEISHU-001 配置 + 认证 + 通道契约（入站基元 + 出站契约）
     │
     ├──────────────────────────┐
     ▼                          ▼
FEISHU-002 Webhook / 事件接收   FEISHU-003 双向身份解析（+迁移 0036）
     │                          │        · resolve（正向）
     │                          │        · resolve_recipient（反向，供主动消息）
     └────────┬─────────────────┘
              ▼
FEISHU-004 接入现有 Chat Pipeline（Web 路径 0 改动；产出回复文本）
              │
              ▼
FEISHU-005 Feishu Outbound Messaging
              ├── Reply 路径（← 004 的文本，带 reply_ref）
              └── Proactive 路径（← 未来 Autonomy，带 recipient + idempotency_key）
                  （两条路径都依赖 003 的反向解析；本 Task 不实现触发方）
              │
              ▼
FEISHU-006 错误处理 + 测试收口（P1，全链收口，含 Proactive 出口能力验证）
```

- **关键路径（P0 最小闭环）**：`001 → 002 → 003 → 004 → 005`。完成后即具备"飞书发消息 → 角色正常回复 → 多轮状态保持"的完整能力，**且出站已同时具备 Reply 与 Proactive 两种出口形态**（后者的触发方留给未来）。
- **002 与 003 可并行**（互不依赖，仅共同依赖 001）。
- **005 对 003 的依赖是本次修订新增的**：Reply 不需要反向解析，但 Proactive 必须有；因两条路径共用同一个 `send`，故 005 必须等 003。
- **006 是收口任务**，必须在 002~005 全部完成后执行；其"§6.2 矩阵"与"依赖边界断言"是 P0 的验收证据来源。
- **未列入本次的依赖**：`Autonomy → 通道契约`。该依赖**存在但触发方不实现**（architecture §2.5.6 登记两条候选路径），故不进入本依赖图。

## 提交节奏

- 每 Task 独立 commit（仅在用户明确要求时提交 / 推送），格式 `feat: FEISHU-XXX <中文描述>`。
- 测试按项目约定分级：Focused Test → Module Test → 必要时 Fast Test；不做无差别全量 `pytest`。涉及 `core/settings` 改动时走 Fast Test。
- 每个 Task 收口前检查 `git status`，确认无临时产物入库。
- P0 链（001→005）收口时做一次回归：既有 Web 路径测试零失败（因为该路径零改动，此项应恒为绿）。

## Task Detail 状态

`task-details/` 已全部生成（FEISHU-001~006）。本次修订（支持主动消息）影响：

| 文件 | 本次修订 |
|---|---|
| `FEISHU-001.md` | 出站契约（`OutboundMessage` / `ChannelAdapter` / `ChannelErrorKind`）+ `base.py` 零依赖约束；原"不定义 ChannelAdapter 协议"的约束已撤销 |
| `FEISHU-002.md` | 无实质改动（入站链路不受影响） |
| `FEISHU-003.md` | 新增反向解析 `resolve_recipient` |
| `FEISHU-004.md` | 出站交接改为通道无关契约（不硬编码 Feishu Reply） |
| `FEISHU-005.md` | **重写为 Outbound Messaging**（Reply + Proactive 双形态） |
| `FEISHU-006.md` | 错误矩阵扩到 15 类 + 边界断言按 R1~R5 重构 + Proactive 出口能力验证 |

## 未来任务（**Risk #2 · Deferred，不阻塞当前实现**）

> 出站触发方的装配问题（Push vs Pull / Registry / 组合根 / adapter 生命周期）**本阶段一律不决策**。此处仅登记，供 Autonomy / Proactive Messaging 真正落地时立项。

| 候选 | 内容 | 前置条件 |
|---|---|---|
| **FEISHU-008（未来）出站触发方接入** | 让未来 Autonomy 产出的主动消息真正送达飞书。两条候选（**均未决**）：① 渠道侧消费者拉取既有 `proactive_actions` 的待推送行 → `resolve_recipient` → `send` → 回写推送态；② 调用方经 Channel 抽象直调（需先解决"谁能 import 具体实现"的装配问题） | 需要一次 schema 变更（`proactive_actions` 无"外部推送态"载体）；需要 Autonomy 立项（architecture §2.5.6） |
| 账号绑定（Web ↔ 飞书） | 改 `channel_identities.internal_user_id`，把飞书身份并入既有内部用户 | 架构 §7.2 明确不在本阶段 |
