# 飞书接入架构设计（Feishu Channel Adapter）

> **阶段**：Plan / Architecture —— 本篇只有设计，不含实现。
> **定位**：V2.0.0（Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced 已落地）之后接入的**第一个外部 Channel**。
> **任务拆分**：见 [`tasks.md`](./tasks.md)。本阶段**不产出** `task-details/`。
>
> **硬约束（贯穿全篇）**：飞书只是 Channel Adapter；不侵入 Character / World / Inventory / Memory 核心；不新建第二套 Chat Pipeline；不新建第二套 Session / Memory 系统；不做大规模重构。

---

## 1. 接入目标

### 1.1 为什么现在接入

V2.0.0 核心能力已经在本地聊天（Web 调试控制台）中稳定运行：Memory、Reflection、Character、World State、Household Inventory、Character Action Sync、World State 持久化。这些能力的完整链路——**上下文构建 → 四链并行 → 行为引擎 → 回答 → 落库 → 后台后处理**——已经是一个与"传输方式无关"的纯后端管线。

此时接入飞书的收益：

1. **验证"Character Runtime 可脱离 Web 控制台独立运行"**：本地聊天是调试面板（单用户 `default-user`、NDJSON 流式），它证明的是"能力正确"；飞书证明的是"**能力可被真实用户以真实渠道使用**"。
2. **把"多用户"从设计假设变成运行事实**：现有代码的用户维度已经完全由 `user_id` 派生（`worlds.world_id = f"home:{user_id}"`、`memories.user_id`、`conversations.user_id`），但 Web 控制台只跑一个 `default-user`。飞书是第一个会天然产生**多个真实用户**的渠道，能顺带把"用户隔离"这条隐性契约逼到台面上验证。
3. **形成 Channel Adapter 范式**：把"入站事件 → 身份映射 → 管线 → 出站消息"抽象成可复用结构，后续（微信 / Discord / Slack 等）只需新增一个 Adapter，而**不动核心域一行**。

### 1.2 飞书在整个系统中的定位

飞书在架构上是**最外层的一个 I/O 适配器**，不是"另一个入口的后端"：

| 飞书**是** | 飞书**不是** |
|---|---|
| 一个入站事件源（Webhook 接收文本消息） | 一个会写业务状态的域 |
| 一个出站消息投递器（Message API） | 一个能绕过管线直达 Memory / World 的通道 |
| 一个外部身份提供方（open_id） | 一个用户系统 / 会话系统 |
| 一个可替换的 Channel 实现 | 核心 Character / World / Memory 的一部分 |

**一句话**：飞书负责"把别人的话变成 `(user_id, session_id, text)`"和"把回复文本发回去"；中间发生什么，它一无所知。

---

## 2. 系统架构

### 2.1 分层视图

```text
                        ┌── Web 调试控制台（既有，本阶段零改动）
                        │
User Message ───────────┼── Feishu（本阶段新增）
                        │
                        └── Future Channels（预留位，同一 Adapter 协议）
                                │
                    ┌───────────▼──────────────────────────────┐
                    │  Channel Adapter（本阶段新增的唯一概念）      │
                    │  · api/v1/feishu.py   传输：验签/解密/快速 ack │
                    │  · channels/feishu/   适配：身份映射/编排/出站 │
                    │  · channels/base.py   Adapter 协议（通道无关）  │
                    └───────────┬──────────────────────────────┘
                                │  (session_id, user_id, content, llm)
                    ┌───────────▼──────────────────────────────┐
                    │  Chat Pipeline（既有，零修改）              │
                    │  agent_service.stream_chat →              │
                    │  application/chat_pipeline.run_chat_pipeline│
                    └───────────┬──────────────────────────────┘
                                │
        ┌───────────────────────┼─────────────────────────┐
        ▼                       ▼                          ▼
  Memory（user_id）     Character / World / Inventory     Action
        └───────────────────────┴─────────────────────────┘
                                │  reply 文本
                    ┌───────────▼──────────────────────────────┐
                    │  Channel Adapter 出站                     │
                    │  tenant_access_token → im/v1/messages/    │
                    │  {message_id}/reply（text）               │
                    └───────────┬──────────────────────────────┘
                                ▼
                            飞书用户
```

### 2.2 唯一新增概念：Channel Adapter 层

现有分层为 `api → application → services → repositories → core`。本设计**不推翻**它，只在 `api` 与 `application` 之间新增一个 **Channel Adapter 层**，方向为 `api → channels → application → services → repositories → core`。

| 层 | 位置 | 内容 | 允许依赖 | 禁止依赖 |
|---|---|---|---|---|
| api | `app/api/v1/feishu.py` | 路由、原始 body 读取、验签/解密、**快速 ack**、把处理投递到后台 | `channels`、`core` | 业务域服务、repositories、langchain |
| **channels（新增）** | `app/channels/base.py`、`app/channels/feishu/` | 通道协议、事件解析、身份映射、管线调用、出站发送 | `application`（管线入口）、`services.channel_identity_service`、`services.trace_collector`、`core` | `character.*`、`services.memory*`、`services.world*`、`services.state*`、`services.relationship*`、`repositories.*`（直连）、`chains.*` |
| application | `app/application/chat_pipeline.py` | 既有编排（**零修改**） | 既有不变 | — |
| services / repositories / core | 既有 | **零修改**（仅新增 `channel_identity_*`） | 既有不变 | — |

**反向引用禁令**：`application` / `services` / `repositories` / `character` / `chains` **任何文件都不得 import `app.channels.*`**。这条是"飞书不侵入核心"的可验证形式，由 FEISHU-006 的静态边界断言守门。

### 2.3 飞书为什么不得直连 Memory / Character / World / Inventory

飞书**明确禁止**直接调用：

- `services.memory*` / `repositories.memory_repository`
- `services.state_service` / `character.*`
- `application.world_engine` / `services.world.*` / `repositories.world_repository`
- 库存相关（`world_repository.list_objects` / `services.grounding.inventory_guard`）

原因：这四项的状态都是**由一轮对话的语义结果推导出来的**，而不是由"收到了哪条消息"决定的。绕过管线直连会立刻产生三类不可修复的破坏：

1. **状态撕裂**：World 的写回由 `post_process` 第 8/9 步在流式回答结束后统一执行（`outbox` + 幂等重放）。外部直写会让"账本"与"消息历史"不再同源，崩溃重放无法收敛。
2. **双份真相**：Memory 的准入由 `memory_policy`（R1~R8）校验、去重、supersede 生命周期管理。直连写入等于绕开准入，产生重复与冲突记忆。
3. **能力绕过**：角色的言语层（Behavior / Mode / Intention）依赖 `context_builder` 装配的完整上下文。直连等于用"没有上下文的消息"驱动核心状态。

**统一入口**：所有渠道的消息一律进入 `agent_service.stream_chat(session_id, user_id, content, llm, trace)`。飞书与 Web 在管线内部**完全无法区分**——这是本设计的核心不变式。

### 2.4 复用清单与改动清单

**复用（零修改）**

| 复用对象 | 位置 | 复用方式 |
|---|---|---|
| Chat 管线入口 | `app/services/agent_service.py::stream_chat` | 进程内直调（不经 HTTP / 不经 SSE） |
| 管线本体 | `app/application/chat_pipeline.py` | 完全不感知渠道 |
| 会话持久化 | `repositories/conversation_repository.py`（`conversations` / `messages`） | 复用 `session_id` / `user_id` 语义 |
| 用户隔离语义 | `worlds.user_id`、`memories.user_id`、`conversations.user_id` | 靠"不同 `user_id`"天然隔离 |
| LLM 获取 | `core/llm_factory.get_llm(profile)` | profile 机制，禁止新建 `ChatOpenAI` |
| 配置系统 | `core/settings/`（pydantic-settings，平铺字段名） | 新增 `feishu` 领域模块并组合进 `Settings` |
| 可观测性 | `services.trace_collector` | 每轮建 trace，复用既有观测 |
| 幂等范式 | `application/outbox_consumer.py`（幂等键 + 退避 + 死信） | 事件去重沿用同一范式 |
| 测试基建 | `core/llm_factory.set_llm(FakeLLM)`、内存 SQLite、marker 自动打标 | 全测试零真实网络 / 零真实 LLM |

**允许的最小接线改动（逐条列明，除此之外不改既有文件）**

| 文件 | 改动 | 性质 |
|---|---|---|
| `app/core/settings/__init__.py` | 组合 `FeishuSettings`（加法，1 处 import + 1 个基类） | 接线 |
| `app/api/v1/router.py` | 注册 `feishu_router`（1 行） | 接线 |
| `.env.example` | 新增 `FEISHU_*` 占位键 | 文档 |
| `tests/conftest.py` | 如需迁移夹具 / 假传输夹具 | 测试 |

**明确不改**：`api/v1/chat.py`、`api/v1/schemas.py`、`application/chat_pipeline.py`、`application/post_process.py`、`character/**`、`services/**`（域服务）、`repositories/**`（既有）、`prompts/**`、`models/**`（既有）。
> 其中"不改 `api/v1/chat.py`"是本设计的一个刻意的决策：Web 调试路径 **0 改动**，`git diff` 可证。飞书不经 HTTP 回环，因此不需要给 `ChatRequest` 增加 `user_id`。

---

## 3. User / Session 映射

### 3.1 映射链

```text
Feishu User
  │  （事件 sender.sender_id）
  ▼
External Identity                  channel = "feishu"，external_id = open_id
  │                                （open_id 对同一应用稳定，作为主键）
  ▼
Identity Resolver                  查/建 channel_identities → 内部身份
  │
  ▼
Internal User / Session            internal_user_id = "feishu:{open_id}"
                                   session_id       = "feishu:{open_id}"
```

**两个决定要明确说清**：

- **`internal_user_id` 采用确定性派生** `feishu:{open_id}`，而不是自增 / 随机 ID。理由：`worlds.world_id` 已经是 `f"home:{user_id}"` 的确定性派生，Memory / Relationship 全部按 `user_id` 索引；确定性派生让映射无需查表即可推导，且天然满足"不同用户不同 ID"。
- **`session_id` 采用一条长驻会话** `feishu:{open_id}`。理由：`conversations.id` 即会话主键，确定性 ID 免去"每次事件查上次会话"的额外跳转，重启后仍连续；且 `feishu:` 前缀与 Web 的 `uuid4` 会话**不可能冲突**。

> 确定性派生是**默认值**，`channel_identities` 表才是**权威记录**。这样未来要把某个飞书身份"绑定到已有内部用户"（例如与 Web 账号合并）时，只需改表里一行，映射规则与管线都不用动。

### 3.2 存储设计（唯一新增表）

```text
channel_identities
├── channel             String  PK₁   -- "feishu"
├── external_id         String  PK₂   -- 飞书 open_id
├── internal_user_id    String  NOT NULL
├── session_id          String  NOT NULL
├── external_union_id   String  NULL      -- 预留：跨应用身份合并
├── external_tenant_key String  NULL      -- 预留：多租户
├── display_name        String  NULL      -- 可观测性（日志可读）
├── status              String  NOT NULL DEFAULT 'active'
├── created_at / updated_at
└── UNIQUE(channel, external_id)
```

- **不新增用户表、不新增会话表**：用户与会话的"实体"仍由既有 `conversations` / 业务表的 `user_id` 承载。`channel_identities` 只解决"外部身份 → 内部身份"的一次映射，**不是第二套 Session / Memory 系统**。
- **并发幂等**：由 `UNIQUE(channel, external_id)` + upsert（捕获唯一冲突后重查）保证"同一飞书用户首轮并发事件只落一行"。这是飞书事件重试（3s 未响应会重推）下的硬要求。

### 3.3 隔离保证（本设计的重点）

隔离完全由 `user_id` 承载，因此**只要 `internal_user_id` 不串**，下游全部自动隔离：

| 资源 | 隔离键 | 隔离机制 |
|---|---|---|
| Conversation | `conversations.id = session_id`，且 `conversations.user_id` 校验 | 不同 open_id → 不同 session_id |
| Messages | `messages.conversation_id` | 随会话隔离 |
| Memory | `memories.user_id` | 不同 user_id |
| World / Inventory | `worlds.world_id = f"home:{user_id}"`（`world_repository.world_id_for`） | 不同 user_id → 不同世界与库存 |
| Relationship / Character State | 按 `user_id` 读写（与 `context_builder` 同源） | 不同 user_id |

**额外的隔离决策**：

- **仅处理单聊（`chat_type == "p2p"`）**。群聊中多个飞书用户共享同一个 `chat_id`，若按会话聚合就会把多个人的消息塞进同一条 conversation，直接破坏上述隔离。**第一阶段群聊事件一律忽略**（记日志 + 返回 200，不回复）。
- **身份键只用 `open_id`**，不使用 `chat_id` 或 `union_id` 作为主键（`union_id` 仅记录备用）。
- `channel_identities` 的读写在 `services.channel_identity_service` 内完成，channels 层不直连仓储。

---

## 4. 消息流程

### 4.1 端到端时序

```text
Feishu Event（im.message.receive_v1）
   │  POST /api/v1/feishu/events        body 可能为 {"encrypt": "<base64>"}
   ▼
[1] 传输层：读原始 body → 加密则 AES 解密 → 取 timestamp / nonce / signature
   ▼
[2] Event Validation
     ├─ header.token            == verification token （否则 401）
     ├─ X-Lark-Signature        == sha256(ts+nonce+encrypt_key+body) （否则 403）
     ├─ 时间戳窗口检查（防重放）
     └─ type == "url_verification" → 原样返回 challenge（仅配置期命中）
   ▼
[3] Event 解析（纯函数）
     ├─ event_type == im.message.receive_v1
     ├─ chat_type  == p2p
     ├─ message_type == text     → content 为 JSON 字符串 {"text": "..."} → 解析出 text
     └─ 任一不满足 / event_id 已见过 → 记日志，返回 200（忽略）
   ▼
[4] 快速 ack：立即 200（飞书要求 ~3s 内响应，否则重推）
     └─ 处理体投递为后台 asyncio task（ack 与处理解耦）
   ▼
[5] User / Session Mapping
     channel_identities upsert（feishu, open_id）→ (user_id, session_id)
   ▼
[6] Chat Pipeline（既有，进程内直调）
     agent_service.stream_chat(session_id, user_id, text, llm, trace)
       ├─ 消费异步事件流：积攒 token；turn_meta 只用于观测，不进回复
       └─ done 事件 → 拿到完整回复文本（此时 save_turn 已在管线内完成）
   ▼
[7] AI Response（出站）
     tenant_access_token（缓存）→ POST im/v1/messages/{message_id}/reply
       content = {"text": "<reply>"}   receive_id_type 无关（reply 走 message_id）
   ▼
[8] Feishu Message API → 飞书用户
     （下一轮：同 session_id → messages 续写 → Memory / World / Relationship 延续）
```

### 4.2 关键设计点

- **ack 与回复解耦**：这是整条链路能否成立的前提。飞书的 3 秒超时约束只作用于**事件回调响应**，不作用于"机器人何时发出消息"。因此本设计：**Webhook 只做校验 + ack，回复异步完成**。若把 LLM 调用放在 ack 之前，必然超时并触发飞书重推。
- **消费内部流但不对外流式**：管线是 `AsyncIterator[dict]`（`turn_meta` / `token` / `done`），Adapter 逐块消费并拼接，**不向飞书做分片推送**。第一阶段的输出是"一条完整文本消息"。
- **回复用 reply 而非 send**：`POST im/v1/messages/{message_id}/reply` 天然锚定上下文（同一条消息的回复），比按 `chat_id` 群发更不容易错位。
- **落库时机不变**：`save_turn` 发生在管线内部（流式回答结束后）。Adapter **不重复落库**，也**不参与** `post_process`（scene / state / summary / memory / action 六步后台照旧）。飞书发送失败只影响"用户看不看得到"，不影响已落库的会话事实。
- **同会话串行**：同一 `user_id` 的多条消息按到达顺序串行处理（进程内 per-user 锁，与既有"单用户写串行化"方向一致），避免同一会话的 `messages` 交错、上下文窗口读到半成品。
- **观测**：每轮由 Adapter 建 trace（复用 `trace_collector`），并把 `feishu.message_id` / `event_id` / `open_id` 记入日志用于排障。

---

## 5. 配置

### 5.1 配置项

新增一个设置领域模块 `app/core/settings/feishu.py`（`FeishuSettings`，平铺字段名，组合进 `Settings`），落点与既有 16 个领域模块一致。环境变量名沿用大写下划线惯例。

| 环境变量 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `FEISHU_ENABLED` | bool | `false` | 总开关。**默认关闭**，与项目"新能力默认关"惯例一致 |
| `FEISHU_APP_ID` | str | `""` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | str | `""` | 飞书应用 App Secret（**敏感**） |
| `FEISHU_VERIFICATION_TOKEN` | str | `""` | 事件订阅 Verification Token（**敏感**） |
| `FEISHU_ENCRYPT_KEY` | str | `""` | 事件 Encrypt Key；留空表示不加密（**敏感**） |
| `FEISHU_API_BASE` | str | `https://open.feishu.cn` | API 基址（便于测试指向假服务） |
| `FEISHU_LLM_PROFILE` | str | `""` | 指定本轮使用的 LLM profile；空则走 `DEFAULT_LLM_PROFILE` |
| `FEISHU_TIMEOUT_SECONDS` | float | `10.0` | 出站 HTTP 超时 |
| `FEISHU_TOKEN_REFRESH_RATIO` | float | `0.8` | `tenant_access_token` 提前刷新比例（TTL 7200s） |
| `FEISHU_MAX_REPLY_CHARS` | int | `4000` | 单条回复字符上限，超出按段切分 |
| `FEISHU_DEDUPE_TTL_SECONDS` | int | `600` | `event_id` 去重窗口 |
| `FEISHU_SIGNATURE_WINDOW_SECONDS` | int | `300` | 时间戳允许偏差（防重放） |
| `FEISHU_MAX_CONCURRENT_TURNS` | int | `4` | 全局并发处理上限 |
| `FEISHU_SESSION_QUEUE_LIMIT` | int | `5` | 单用户待处理消息队列上限（超出丢弃并提示） |

### 5.2 配置原则

- **敏感配置只从环境变量 / `.env` 读取**，源码零硬编码（项目全局约定）。日志、trace、异常信息中**不得出现** `APP_SECRET` / `ENCRYPT_KEY` / `tenant_access_token` 明文。
- **启用即校验**：`FEISHU_ENABLED=true` 时 `APP_ID` / `APP_SECRET` / `VERIFICATION_TOKEN` 缺失应在启动阶段抛 `SettingsError`（沿用既有校验惯例），而不是等到第一个用户消息才失败。
- **未启用即隐身**：`FEISHU_ENABLED=false` 时 Webhook 路由返回 404（不暴露端点）、不创建任何 HTTP 客户端、不获取 token，全链路零副作用（可用调用计数断言）。
- **回调地址**：`https://<公网域名>/api/v1/feishu/events`，在飞书开放平台"事件订阅"中配置；本地联调需公网可达（内网穿透或测试环境），属部署事项，不引入代码分支。
- **飞书侧权限**：需申请 `im:message`（接收）、`im:message:send_as_bot`（发送），并订阅 `im.message.receive_v1`。Webhook 与长连接二选一，本阶段选 **Webhook**。
- **`.env` 不提交**（项目约定），`.env.example` 只放空值占位。

---

## 6. 错误处理

### 6.1 全局原则

1. **失败只降级，不扩散**：任何飞书侧异常都不得影响已落库的会话事实，也不得让核心域产生半成品状态。
2. **安全默认拒绝**：校验类失败（验签 / token / 解密）一律拒绝处理，且**在验证通过前不触碰任何业务代码**。
3. **可重试要有界，不可重试要留痕**：可重试（429 / 5xx / 超时）走指数退避 + 上限；不可重试（4xx）直接终止并记录。
4. **ack 优先于排障**：解析失败也应尽量返回 200，避免飞书无限重推造成放大。

### 6.2 错误矩阵

| # | 场景 | 检测点 | 处理 | 返回给飞书 | 用户可见结果 |
|---|---|---|---|---|---|
| 1 | **Webhook 验证失败**（token / 签名 / 时间戳） | 传输层（步骤 [2]） | 记录告警日志，不解析事件、不调管线 | `401` / `403` | 无回复（安全拒绝） |
| 2 | **解密失败**（Encrypt Key 不匹配 / 密文损坏） | 传输层（步骤 [1]） | 记录告警，标记配置类错误 | `400` | 无回复 |
| 3 | **Event 解析失败**（结构非预期 / `content` 非法 JSON） | 解析纯函数（步骤 [3]） | 记录 + trace，跳过该事件 | `200`（避免重推） | 无回复 |
| 4 | **事件不适用**（群聊 / 非 text / 非 `im.message.receive_v1`） | 解析纯函数 | 记录后忽略 | `200` | 无回复 |
| 5 | **重复事件**（`event_id` 命中去重窗口） | 去重检查 | 直接忽略（幂等） | `200` | 不重复回复 |
| 6 | **Session 创建失败**（`channel_identities` 写入失败 / DB 不可用） | 身份映射（步骤 [5]） | **不调管线**；记录异常 | `200` | 尝试发一条兜底文案（"我这边出了点小问题，稍后再试"）；发不出则静默 |
| 7 | **Chat Pipeline 异常** | 消费事件流（步骤 [6]） | 沿用 `api/v1/chat.py` 既有语义对齐：`EmptyLLMResponseError` → 友好提示；`APIStatusError` → LLM 失败提示；其他异常 → 通用失败提示。**不写入半成品回复** | `200`（已 ack） | 收到失败提示文案 |
| 8 | **AI 返回为空** | 累积结果为空串 | 不发空消息；按固定策略二选一（兜底文案 / 静默），实现期冻结 | `200` | 兜底文案或静默 |
| 9 | **Feishu API 调用失败** | 出站（步骤 [7]） | `429/5xx/超时` → 指数退避重试（有上限）；`4xx` → 不重试；终败记录错误日志，**不改会话状态** | 不适用 | 本轮回复丢失（下一轮仍正常） |
| 10 | **回复超长** | 出站前 | 按 `FEISHU_MAX_REPLY_CHARS` 切分为多条顺序发送；单条仍超限则截断并标记 | 不适用 | 消息分段到达 |
| 11 | **发送重复** | 出站 | 以 `message_id` 为幂等键防重复投递（重试场景） | 不适用 | 同一条只收到一次 |
| 12 | **用户消息过载** | 排队 | 单用户队列超 `FEISHU_SESSION_QUEUE_LIMIT` → 丢弃最旧并提示 | `200` | 收到"消息有点多"提示 |
| 13 | **限流** | 传输层 | 注意：既有 `chat_rate_limit_middleware` **只保护 `POST /api/v1/chat/message`**（按客户端 IP），Webhook 路径不在其内 → 飞书侧需**独立**的按 `open_id` 窗口限流 | `429` | 收到限流提示 |

### 6.3 与既有错误语义的对齐

- `api/v1/chat.py` 已定义了三条对外错误语义：LLM 调用失败、`EmptyLLMResponseError`（空响应）、通用异常。飞书 Adapter **复用同一套语义**（同样的用户可见文案），但**不复制管线逻辑**——它只是把这三种异常映射成"发一条什么文案"。
- `post_process` 的既有契约（后处理失败不影响已产出的回答）在飞书链路中**原样继承**，无需新增处理。

---

## 7. 边界

### 7.1 第一阶段支持范围

```text
飞书发消息（单聊，纯文本）
        ↓
角色正常回复（一条完整文本消息）
```
以及：
```text
飞书多轮对话 → Memory / World / Session 正常保持
```

### 7.2 明确不做（第一阶段）

| 不做 | 原因 / 未来位置 |
|---|---|
| **Streaming（流式分片/打字机）** | 飞书无原生流式；需要"占位消息 + 反复 update"，属卡片/交互能力，后置 |
| **图片** | 需要下载 → 多模态 → 入管线；涉及新的输入类型与存储，后置 |
| **语音** | 需要 ASR 前置；独立的输入转换链路，后置 |
| **文件** | 同上 + 安全（不可信内容），后置 |
| **Interactive Card** | 需要卡片模板 + 回调交互状态机；与"文本最小闭环"无关，后置 |
| **主动消息** | 现有主动能力是 **pull 模型**（`application/outbox_consumer` + `/proactive/pending` 轮询 + `ack`）。飞书需要 **push 投递适配器**。这是未来 Channel 出站接口的自然扩展点，**本阶段不做** |
| **群聊复杂能力** | 群聊的会话聚合会破坏用户隔离（见 §3.3）；仅"忽略群聊事件" |
| **多机器人 / 多应用** | `channel_identities` 已预留 `tenant_key` / `union_id`，但本阶段单应用 |
| **飞书工作流 / 审批 / 日历等** | 与 Character Runtime 无关，不做 |
| **账号绑定（Web ↔ 飞书）** | 表结构已支持改 `internal_user_id`，但流程与 UI 不在本阶段 |

### 7.3 未来扩展点（仅登记位置，不实现）

- **多 Channel**：`app/channels/base.py` 定义通道无关协议（入站消息 / 身份 / 出站回复），新渠道 = 新子包。
- **出站投递抽象**：主动消息落地时，把"发送"抽为 `ChannelSender`，`proactive` 侧从"轮询"扩展为"轮询 + 推送到已绑定渠道"。
- **回复后处理**：若角色的回复含舞台指示/动作描述，未来可在 Adapter 出站前做"表现层转换"（属于 Channel 的表现问题，不属于角色核心）。

---

## 附录 A：目录落点

```text
app/
├── api/v1/
│   ├── feishu.py                      # ★ 传输层：路由 / 验签 / 解密 / 快速 ack
│   └── router.py                      #   +1 行注册（既有文件的最小接线）
├── channels/                          # ★ 新增：Channel Adapter 层
│   ├── base.py                        #   通道无关协议（InboundMessage / ChannelIdentity / ChannelReply）
│   └── feishu/
│       ├── adapter.py                 #   编排：事件 → 身份 → 管线 → 出站
│       ├── events.py                  #   校验 + 解析（纯函数，可直接单测）
│       ├── identity.py                #   open_id → internal_user_id / session_id
│       ├── client.py                  #   出站：token 缓存 + 发消息（唯一持有密钥的模块之一）
│       └── errors.py                  #   错误分类
├── services/channel_identity_service.py     # ★ 映射读写（业务入口）
├── repositories/channel_identity_repository.py  # ★ 单表 CRUD
└── core/settings/feishu.py             # ★ 配置领域模块
migrations/versions/0036_channel_identities.py    # ★ 唯一 schema 变更（当前链尾 0035）
docs/integrations/feishu/{architecture.md,tasks.md}
```

## 附录 B：与硬约束的对应关系

| 约束 | 设计保证 |
|---|---|
| 1. 不修改 Character 核心架构 | `character/**` 零改动；channels 禁止 import `character.*`（静态断言守门） |
| 2. 不修改 World / Inventory 核心架构 | `world_engine` / `services.world.*` / `world_repository` 零改动、且禁止被 channels 引用 |
| 3. 不创建第二套 Chat Pipeline | 唯一入口 `agent_service.stream_chat`；渠道差异全部收敛在 Adapter |
| 4. 不创建第二套 Session / Memory 系统 | 复用 `conversations` / `memories`；新增表只做"外部身份 → 内部身份"映射 |
| 5. 飞书只作为 Channel Adapter | 权限边界由依赖方向 + 静态 import 断言双重约束 |
| 6. 优先复用既有配置/User/Session/Router/Service | 见 §2.4 复用清单；改动仅 4 处接线 |
| 7. 不为飞书大规模重构 | 不新增层级家族、不改 schema（除 1 张新表）、不改既有域文件；`api/v1/chat.py` 0 改动 |
| 8. 保证"发消息 → 正常回复"与"多轮 → 状态保持" | 多轮连续性由确定性 `session_id` + `user_id` 承载，Memory / World / Relationship 自动延续 |
