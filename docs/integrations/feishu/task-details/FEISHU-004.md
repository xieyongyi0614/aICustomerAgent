# FEISHU-004 — 接入现有 Chat Pipeline

> 上游：[../tasks.md](../tasks.md) FEISHU-004 ｜ 架构：[../architecture.md](../architecture.md) §2.3 / §4.2 / §6.2 #6~#8 / #12 ｜ 依赖：**FEISHU-002、FEISHU-003**
> Priority：**P0** ｜ 层级：Runtime（飞书与角色系统真正连接的 Task）
> **本 Task 的产出形态**：`InboundMessage` → 一次真实的角色对话 → **一个 `TurnOutcome`（含要发给用户的最终文案）**。**不含**出站 HTTP 发送（FEISHU-005）。

---

## 1. Goal

把"飞书消息"变成"角色的一轮对话"，并且**不新增任何对话逻辑**：

```text
InboundMessage（002 产出）
      │
      ▼
① 身份解析（003）        channel_identity_service.resolve(...) → (user_id, session_id)
      │
      ▼
② 并发控制（本 Task）     per-session 串行 + 有界队列（user A 不阻塞 user B）
      │
      ▼
③ LLM 获取（既有）        core.llm_factory.get_llm(FEISHU_LLM_PROFILE or None)
      │
      ▼
④ 调既有管线              agent_service.stream_chat(session_id, user_id, text, llm, trace)
      │
      ├─ turn_meta  → 丢弃（只用于观测）
      ├─ token      → 累积
      ├─ done       → 结束（此时 save_turn 已在管线内完成）
      └─ 异常       → 映射为既有语义的兜底文案
      ▼
⑤ TurnOutcome(generated) → 经通道无关契约（OutboundMessage）交给 FEISHU-005
```

本 Task 交付 4 件事：

1. **`adapter.handle_inbound_message` 的实现体**（002 冻结了签名，本 Task 填内容）。
2. **流消费与回复拼接**：`turn_meta` 过滤、空回复判定、异常映射、流中断处理。
3. **per-session 串行与有界队列**：保证"同一会话 A→B→C 顺序完成"，且"不同会话互不阻塞"。
4. **零新增对话逻辑的证明**：`git diff` 不含 `application/chat_pipeline.py` / `api/v1/chat.py`，且 `channels/**` 无 `chains` / `services.memory*` / `services.world*` 等 import。

## 2. Dependencies

| 依赖 | 提供物 | 使用方式 |
|---|---|---|
| **FEISHU-002** | `adapter.handle_inbound_message(inbound)` 入口 + `spawn_background` 派发 + trace 起点 | 本 Task 填充其处理体 |
| **FEISHU-003** | `channel_identity_service.resolve(...) -> ResolvedIdentity` | **唯一**身份来源（不得自行拼 `feishu:{open_id}`） |
| 既有 | `services/agent_service.py::stream_chat(session_id, user_id, content, llm, trace)` | **唯一**管线入口 |
| 既有 | `core/llm_factory.py::get_llm(profile_id)` | **唯一** LLM 来源（profile 机制 + 内部缓存 + `set_llm` 测试接缝） |
| 既有 | `services/trace_collector` | 002 已 `begin_trace`；本 Task **只透传**，不新建第二个 trace |
| 既有 | `application/post_process.py::_user_write_locks` 范式 | **参考**其"模块级 dict + reset 接缝"形状（但**不复用**其锁，见 §15.2） |

> **反向输出（本 Task 必须供给下游）**：`TurnOutcome.outbound_text` 是 FEISHU-005 的**唯一**输入。005 不得回调管线、不得读 conversation、不得自行判定"该发什么"。

## 3. Scope

**做**：

- 填充 `app/channels/feishu/adapter.py`：
  - `handle_inbound_message` 处理体（身份 → 串行 → LLM → 管线 → 消费流 → 组装 `TurnOutcome`）
  - `TurnOutcome`（frozen dataclass，模块内定义）
  - per-session 串行锁 + 有界队列计数器 + `reset_feishu_adapter()` 接缝
  - 兜底文案表（对齐 `api/v1/chat.py` 的既有三类错误语义）
- 与 FEISHU-005 的交接：把 `TurnOutcome` 返回给 005 的发送函数（005 落地调用点）。

**不做**（见 §14）：出站 HTTP 发送、文本切分、出站重试幂等、消息发送 API、身份映射实现（003）、Webhook 校验（002）、群聊、Streaming 对外分片。

## 4. Files

### New Files

```text
tests/unit/test_feishu_adapter_stream.py        # 流消费/过滤/异常映射（纯逻辑，FakeLLM）
tests/integration/test_feishu_adapter_turn.py   # 真实走管线 + 落库 + 串行 + 隔离（内存 SQLite + FakeLLM）
```

### Modified Files

```text
app/channels/feishu/adapter.py    # 由 002 的骨架 → 本 Task 填充处理体（同文件、同签名）
tests/conftest.py                 # 仅当前台任务需要被 teardown 等待时（默认复用 observability 集合则不动）
```

### Forbidden Files

```text
application/chat_pipeline.py        # ★ 零修改（AC-7 硬闸）
application/post_process.py         # ★ 零修改
services/agent_service.py           # ★ 零修改（只调用）
core/llm_factory.py                 # ★ 零修改（只调用）
api/v1/chat.py  api/v1/schemas.py   # ★ 零修改（Web 路径 0 改动）
chains/**  prompts/**  characters/**  models/**
services/memory*  services/world*  services/state*  services/relationship*   # channels 禁 import
repositories/**                     # channels 禁 import（身份读写经 003 的 service）
任何 Autonomy / Life Loop / Scheduler / Policy 模块   # ★ 本次修订新增（R3）
```

**本次修订新增的硬约束**

1. **Chat Pipeline 不知道飞书**：`application/chat_pipeline.py` 只产出 token；004 不向其注入任何飞书概念（不新增参数、不改签名）。飞书的存在只体现在 `channels/feishu/` 内。
2. **出站经契约、不硬编码 API 形态**：004 交给 005 的是 `OutboundMessage`（`channels/base.py` 契约），**不**在 `adapter.py` 里拼飞书请求体、**不**选飞书 API、**不**做文本切分。
3. **不实现主动消息**：004 只走 Reply 形态（有 `source_message_ref`）。Proactive 的能力在 005，触发方在未来 Autonomy；`adapter.py` **不得**引入任何"何时主动开口"的逻辑或调用。

## 5. Architecture / Data Flow

### 5.1 一次飞书轮次（完整时序）

```text
FEISHU-002（已 ack，后台任务中）
        │  handle_inbound_message(inbound)
        ▼
[1] resolved = channel_identity_service.resolve(
        "feishu", inbound.external_user_id,
        union_id=metadata.get("union_id"),
        tenant_key=metadata.get("tenant_key"))
    └─ 失败 → TurnOutcome(error_kind="identity_error", outbound_text=兜底文案) → 交给 005
        │   （架构 §6.2 #6：**不调管线**）
        ▼
[2] 入队/串行（key = resolved.session_id）
    ├─ in-flight+waiting > FEISHU_SESSION_QUEUE_LIMIT → 拒绝本消息
    │     → TurnOutcome(error_kind="overloaded", outbound_text="消息有点多…") → 交给 005
    └─ 否则 await session_lock
        │
        ▼
[3] llm = get_llm(settings.feishu_llm_profile or None)
        │
        ▼
[4] 消费既有管线（**不落库、不后处理——管线自己做**）
    full_reply = []
    async for event in agent_service.stream_chat(
            resolved.session_id, resolved.internal_user_id,
            inbound.text, llm=llm, trace=trace_from_002):
        kind = event["kind"]
        ├─ "turn_meta" → 忽略（**不得**进入 full_reply）
        ├─ "token"     → full_reply.append(event["text"])
        └─ "done"      → turn_id = event["turn_id"]（仅用于日志/幂等键）
        │
        ├─ EmptyLLMResponseError → outbound = 空响应文案，error_kind="empty_response"
        ├─ openai.APIStatusError → outbound = LLM 失败文案，error_kind="llm_error"
        └─ 其他 Exception        → outbound = 通用失败文案，error_kind="pipeline_error"
        （**不写半成品**：full_reply 未落库，管线内部也未走到 save_turn）
        │
        ▼
[5] reply = "".join(full_reply).strip()
    ├─ reply 非空 → TurnOutcome(outbound_text=reply, turn_id=…, error_kind=None)
    └─ reply 为空 → TurnOutcome(outbound_text=空回复兜底文案, error_kind="empty_response")
        │   （架构 §6.2 #8：**不发空消息**）
        ▼
[6] 释放 session_lock；计数器 -1
        │
        ▼
[7] return outcome → FEISHU-005 发送
```

### 5.2 关键不变式

| 不变式 | 含义 |
|---|---|
| **管线是唯一对话逻辑** | Adapter 只做"取身份 / 排队 / 取 LLM / 转发 / 拼字符串"，**没有任何**上下文构建、链调用、状态计算 |
| **不重复落库** | `save_turn` / `mode` 写回 / `post_process` 全部由管线执行；Adapter **零 DB 写** |
| **不新建第二套 trace** | trace 在 002 建、管线内 `attach`；Adapter 只透传 |
| **turn_meta 绝不外发** | 它是内部观测事件（含 mode/analysis/scene/goal/behavior），**禁止**进入 `outbound_text` |
| **失败不产生半成品** | 出错时既不发空消息、也不留下未完成的消息行 |
| **每会话一个串行队列** | 同一 `session_id` 严格 FIFO；不同 `session_id` 完全并行 |

## 6. Detailed Implementation

### 6.1 LLM 获取

```text
llm = get_llm(get_settings().feishu_llm_profile or None)
```

- **唯一来源**是 `core/llm_factory.get_llm`（项目硬约束：禁止各处新建 `ChatOpenAI`）。
- `FEISHU_LLM_PROFILE` 为空 → `get_llm(None)` → 内部解析为 `DEFAULT_LLM_PROFILE`（既有行为）。
- **禁止**：自建 `ChatOpenAI`、自配 `base_url` / `api_key`、自造 client、自造 prompt、直接调 chain。
- **调用时机**：在轮次内（不是 import 期）。`get_llm` 自带进程级缓存，无需 Adapter 再缓存。
- **测试接缝**：沿用既有 `llm_factory.set_llm(FakeLLM)`（conftest `_reset_llm` autouse 已自动清理）。

### 6.2 流消费

管线产出的事件类型（`application/chat_pipeline.py` 既有契约）：

| `kind` | 载荷 | Adapter 行为 |
|---|---|---|
| `turn_meta` | `role_mode` / `analysis` / `scene_intent` / `scene_state` / `intention` / `current_goal` / `behavior` / `mode` / `action_intent` | **丢弃**（仅可用于调试日志的字段计数，**不得**入 `outbound_text`） |
| `token` | `text` | `full_reply.append(text)` |
| `done` | `session_id` / `turn_id` / `request_id` | 记录 `turn_id`（日志 + 005 幂等键参考）；结束循环 |

**实现要求**：

- 用 `async for event in stream_chat(...)`，**不做** `asyncio.to_thread`（它本身是 async generator）。
- `event["kind"]` 用 `.get("kind")` 读取并对未知类型**静默忽略**（向前兼容：管线未来新增事件类型不得让飞书链路崩）。
- 累积用 `list[str]` + 末尾 `"".join()`（与 `chat_pipeline` 内部同款，避免 O(n²) 字符串拼接）。
- **不做流式外发**：第一阶段的输出是"一条完整文本"，分片推送属架构 §7.2 明确不做项。

### 6.3 `turn_meta` 过滤（**易错点**）

- `turn_meta` 是**管线的第一个** yield，且体积大（含 scene/goal/behavior 快照）。若误把它 join 进回复，用户会收到一坨 JSON。
- 防线：只在 `kind == "token"` 时 append；其余 `kind` 一律不走 append 分支。
- **测试必须逐字段反证**：断言最终文本中**不含** `role_mode` / `scene_state` / `behavior` / `action_intent` 等键名。

### 6.4 空回复 / 异常 / 流不完整

| 情形 | 判定 | Adapter 行为 | `error_kind` |
|---|---|---|---|
| 正常 | 累积非空 | 直接作为 `outbound_text` | `None` |
| **AI 返回为空** | 累积为空（含全空白） | **不发空消息** → 发固定兜底文案 | `empty_response` |
| 管线抛 `EmptyLLMResponseError` | 异常类型 | 同上 | `empty_response` |
| 管线抛 `openai.APIStatusError` | 异常类型 | LLM 失败兜底文案 | `llm_error` |
| 管线抛其他 `Exception` | 兜底 | 通用失败兜底文案 | `pipeline_error` |
| **流不完整**（生成器提前结束且无 `done`、部分 token） | 有 token 但无 `done` | **仍然发送已累积内容**（用户的期望是"收到回复"），并记 error 日志 + trace error；**不回滚**（管线是否落库以管线自身为准） | `incomplete` |
| 流不完整且无 token | 无 token 无 done | 视为空回复 → 兜底文案 | `empty_response` |

- **"不写半成品回复"的含义**：Adapter **不**把已累积但未完成的文本落库（它本来就零 DB 写）；管线的 `save_turn` 只在**流正常结束后**执行，因此异常路径不会产生"半条消息"。这是管线既有契约（架构 §6.3），Adapter **无需也不得**补偿。
- 兜底文案是**固定常量表**（不调 LLM 生成），保证异常路径零额外成本、可断言。

### 6.5 落库边界（**严禁重复保存**）

| 动作 | 归属 | Adapter |
|---|---|---|
| `conversation_service.save_turn`（human + ai 两条消息） | 管线（`chat_pipeline` 内） | ❌ 禁止调用 |
| `conversation.mode` 写回 | 管线 | ❌ 禁止 |
| `schedule_post_process`（scene/state/summary/memory/action） | 管线 | ❌ 禁止 |
| `reset_proactive_on_user_message` | 管线 | ❌ 禁止 |
| `observability.on_turn_finished` / `record_turn_decisions` | 管线 | ❌ 禁止 |
| `channel_identities` 读写 | FEISHU-003 的 service | 经 service 调用（不直连仓储） |

**验证方式**：集成测试断言"一轮飞书对话后 `messages` 表恰好 +2 行"（human=1, ai=1）。若是 +4，说明重复落库。

### 6.6 Per-user / Per-session 串行

| 项 | 决定 | 理由 |
|---|---|---|
| **锁 key** | `resolved.session_id` | 顺序性是**会话**属性；未来支持"一用户多会话"时不同会话可并行，无需改设计 |
| **锁类型** | `asyncio.Lock` | 与既有 `post_process` 同款；无外部依赖 |
| **锁的存储** | 模块级 `dict[str, asyncio.Lock]`，首次使用懒创建 | 对齐既有 `_user_write_locks` 范式 |
| **锁生命周期** | 进程内单例，存活至 `reset_feishu_adapter()` | 与 001 的 `reset_feishu_client()` 并列；**每个测试文件用 autouse fixture 重置**（`asyncio.Lock` 跨事件循环绑定陷阱，同 001 §约束 3） |
| **临界区范围** | 从 `await lock` 之后到"组装完 `TurnOutcome`" | **含** `stream_chat` 全流程（这是顺序保证的来源）；**不含**出站发送（发送在 005，锁已释放） |
| **是否阻塞他人** | 否。不同 `session_id` 取不同锁 | §12 有 "A 阻塞期间 B 正常完成" 断言 |
| **队列上限** | `FEISHU_SESSION_QUEUE_LIMIT`（含"执行中 + 等待中"） | 架构 §6.2 #12 |
| **超限处理** | **拒绝新到消息** + 发提示文案（`error_kind="overloaded"`），不派发管线 | 见 §15.3 的偏差说明 |

```text
_session_locks: dict[str, asyncio.Lock] = {}
_session_load:  dict[str, int] = {}          # 执行中 + 等待中 的轮次数
_reset: reset_feishu_adapter() → 清空两者
```

**计数语义**：进入时 `+1`，`finally` 中 `-1`（异常路径也必须减，否则该会话会被永久锁死——**这是本 Task 最容易埋的坑**，测试须覆盖"管线抛错后同一会话仍能继续对话"）。

### 6.7 错误语义映射（对齐既有 Web Chat）

不得创造新的一套业务错误体系。既有的三类语义（`api/v1/chat.py`）→ 飞书侧**面向用户**的固定文案：

| 既有语义 | Web 侧表现（`api/v1/chat.py`） | 飞书 `outbound_text` | `error_kind` |
|---|---|---|---|
| LLM 调用失败 | `{"detail": "LLM 调用失败", "error": {...}}` | "我这会儿有点走神，等下再说好不好？" | `llm_error` |
| LLM 返回空响应 | `{"detail": "LLM 返回空响应，请检查模型服务商状态或额度"}` | "我一下子不知道说什么好…你再说一次？" | `empty_response` |
| 通用异常 | `{"detail": "LLM 调用失败"}` | "我这边出了点小问题，稍后再试。" | `pipeline_error` |
| 身份映射失败 | （无对应） | "我这边出了点小问题，稍后再试。" | `identity_error` |
| 队列过载 | （无对应） | "你发得太快了，我一条条慢慢回你～" | `overloaded` |

- 文案为**常量表**（模块级 `dict[str, str]`），**不是** settings（它们是话术而非阈值；且 001 已冻结配置集，§15.4）。
- **语义一致性要求**：`error_kind` 的取值必须能映射回既有三类（`llm_error`→LLM 失败、`empty_response`→空响应、`pipeline_error`→通用异常），后两类渠道特有（`identity_error` / `overloaded`）为**渠道边界情况**，不进入核心错误体系。
- **异常对象不得泄漏到用户**：`outbound_text` 永远是人话，不含堆栈/状态码/异常类名。技术细节只进日志与 trace。

### 6.8 与 FEISHU-005 的交接面（经通道无关契约）

**方向（本次修订明确）**：

```text
Chat Pipeline（application/chat_pipeline.py，零修改，不知道飞书）
      ↓  只产出回复 token
Feishu Adapter（channels/feishu/adapter.py，本 Task）
      ↓  组装通道无关的 OutboundMessage（channels/base.py 契约）
Delivery（channels/feishu/delivery.py，FEISHU-005）
      ↓
Feishu Reply API / Feishu Send API
```

**004 的职责边界**：004 产出"要发的文本 + 发送上下文"，并把它交给**通道出站契约**。004 **不**拼 Feishu 请求、**不**选飞书 API、**不**做文本切分（切分与 API 选择都在 005）。

```text
TurnOutcome(frozen dataclass)          # 004 的产出（内部结构，位于 channels/feishu）
  session_id: str
  user_id: str                         # = internal_user_id（005 据此反向解析收件人）
  outbound_text: str | None            # 最终要发给用户的内容（含兜底文案）
  turn_id: str | None                  # done 事件的 turn_id；异常路径可能为 None
  error_kind: str | None               # None | empty_response | llm_error |
                                       # pipeline_error | identity_error | incomplete | overloaded
  source_message_ref: str | None       # = inbound.reply_ref（= 飞书 message_id）
                                       #   → 组装 OutboundMessage.reply_ref（有锚点 = Reply 形态）
  thread_ref: str | None               # = inbound.external_thread_id（= 飞书 chat_id）
                                       #   → 仅用于日志/排障；**不作为**出站目标
```

**到 `OutboundMessage` 的映射（004 → 005 的实际交接物）**：

| `OutboundMessage` 字段 | 取值来源 |
|---|---|
| `channel` | `FEISHU_CHANNEL` |
| `recipient` | `RecipientRef(channel="feishu", external_id=resolve_recipient(user_id) 的结果)` —— **Reply 形态下也带上**（出站抽象不假设"有锚点"） |
| `text` | `TurnOutcome.outbound_text` |
| `reply_ref` | `TurnOutcome.source_message_ref`（**有 → Reply 形态；无 → Proactive 形态**） |
| `idempotency_key` | Reply 形态可省（由 `reply_ref` 充当）；**Proactive 形态必填**（本 Task 不产生 Proactive，故当前恒省） |
| `metadata` | `turn_id` / `error_kind`（供日志与排障，有界） |

**交接契约（修订）**：

- 004 → 005 的交接物是 **`OutboundMessage`（通道无关）**，不是"飞书 reply 参数"。
- 004 **不**判断投递细节（切分 / API 选择 / 重试）——那些属 005。
- 005 **不**判断业务错误（`error_kind` 已由 004 判定完毕），**不**读 conversation，**不**调管线。
- 005 **不**回传失败（架构 §6.2 #9）。004 是"单向产出"。
- **本 Task 只走 Reply 形态**（有 `source_message_ref`）。Proactive 形态的**能力**由 005 交付、**调用方**留给未来 Autonomy（架构 §2.5.6）；004 **不得**实现任何主动消息逻辑。

## 7. Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 处理一条入站消息 | `InboundMessage` | `TurnOutcome` | 002 冻结签名的实现体；**不抛异常**（全兜底） |
| 消费管线流 | async generator | `(reply_text, turn_id, error_kind)` | 内部函数；`turn_meta` 过滤点 |
| 取每会话锁 | `session_id` | `asyncio.Lock` | 懒创建 |
| 判定队列上限 | `session_id` | `bool` | 进入前检查 |
| 重置适配器状态 | — | `None` | 测试接缝：清锁与计数 |

**`handle_inbound_message` 的异常契约**：即便是 003 的 DB 异常、005 的调用异常，也**必须**在函数内被捕获并转成 `TurnOutcome`（后台任务无人接收异常；未捕获会导致 `spawn_background` 的 task 异常静默丢失并使测试偶发失败）。

## 8. Data Model

**无数据库、无迁移、无新表。** 只有进程内状态：

```text
_session_locks: dict[str, asyncio.Lock]   # 每会话串行
_session_load:  dict[str, int]            # 执行中 + 等待中 计数
_FALLBACK_TEXT: dict[str, str]            # error_kind → 固定文案（常量）
```

**为何不持久化**：锁与计数是"进程内调度状态"，重启后重新建立即可；持久化会引入一致性负担且无收益（对齐 001/002 的克制判断）。多 worker 下"同一用户被两个 worker 同时处理"是**接受的**范围限制（架构 §6.2 #12 的队列语义本身是进程内概念）。

## 9. Error Handling

| 情形 | 处理 | `outbound_text` |
|---|---|---|
| 身份映射失败（DB 异常 / open_id 非法） | 记 exception 日志 + trace error；**不调管线** | 通用兜底文案 |
| 队列过载 | 记 warning（含 session_id 与当前 load） | 过载提示 |
| `get_llm` 抛 `SettingsError`（profile 非法） | 记 error；不调管线 | 通用兜底文案 |
| `EmptyLLMResponseError` | 记 warning | 空回复文案 |
| `openai.APIStatusError` | 记 exception（含 status/code，**不含 prompt 内容**） | LLM 失败文案 |
| 其他 `Exception` | 记 exception + trace error | 通用兜底文案 |
| 流无 `done` 但有 token | 记 error（区分"流不完整"），仍发送累积内容 | 累积内容 |
| 锁内超时 | 不设超时（管线自身有 LLM 超时；加外层超时会与 `pytest-timeout` 语义重叠） | — |

**契约**：本 Task 的失败**一律表现为一条发给用户的人话文案**，或（仅 `incomplete`）已生成的部分内容。**没有**"用户什么都没收到"的静默路径（`outbound_text=None` 除外，见 §15.5）。

## 10. Concurrency / Idempotency

### 10.1 顺序保证

```text
同一 session_id：A ─► 完成 ─► B ─► 完成 ─► C ─► 完成        （严格 FIFO）
不同 session_id：A ∥ B ∥ C                                  （完全并行）
```

- 顺序由"`await lock` 之后才动管线"保证；因为锁覆盖了 `stream_chat` 全流程，所以**不会**出现"两条消息的 human 行交错、上下文窗口读到半成品"。
- **不做**跨进程串行（多 worker 各自持锁）；第一阶段单实例。

### 10.2 幂等

| 层 | 幂等键 | 提供者 |
|---|---|---|
| 事件级（防飞书重推） | `event_id` | FEISHU-002 去重 |
| 身份级 | `(channel, external_id)` | FEISHU-003 复合主键 |
| **轮次级** | **无**（本 Task 不做事后重放） | — |
| 出站级 | `source_message_ref`（+ `turn_id`） | FEISHU-005 |

**为什么轮次级不设幂等键**：本 Task 的触发源是"已通过 002 去重的事件"，重放不会发生；若未来引入"失败重试整轮"，应在 002 的事件表上做，而不是在 Adapter 内加隐藏状态。

### 10.3 计数减一的必然性（**必须覆盖**）

```text
try:
    await lock
    ... 一切处理（含异常路径）
finally:
    _session_load[session_id] -= 1        ← 必须在 finally
    （必要时清理归零项，避免 dict 无界增长）
```

**失败模式**：若 `-1` 放在正常路径上，一次管线异常就会让该会话的计数永久 +1，累积到 `FEISHU_SESSION_QUEUE_LIMIT` 后该用户**再也收不到回复**。§12 有专项用例。

## 11. Security

| 项 | 要求 |
|---|---|
| **零新凭据面** | 本 Task 不接触 `app_secret` / `tenant_access_token`（LLM 凭据由 `llm_factory` 内部处理） |
| **日志脱敏** | 复用 001 的 `_scrub`；**不记录**完整用户消息与完整 AI 回复；需要留证时用 `core.logutils.content_preview`（受 `log_content_preview_chars` 控制，默认 0 = 不预览） |
| **trace 不落敏感内容** | `turn_meta` 只进 trace（既有行为），但**禁止**把 `outbound_text` 全文写进日志 |
| **异常不回显** | `APIStatusError` 的 status/code 只进日志，不进 `outbound_text` |
| **身份不可伪造** | `internal_user_id` 只来自 003 的 `resolve`（输入是 002 已验签事件里的 `open_id`）；Adapter **不得**接受外部传入的 `user_id` |
| **注入面** | `inbound.text` 只作为 content 传给既有权线（既有 `content` 处理/模板通道不变，无新增拼接） |

## 12. Testing

零真实网络、零真实 LLM（`llm_factory.set_llm(FakeLLM)`）；集成用例用内存 SQLite。

### 12.1 `tests/unit/test_feishu_adapter_stream.py`

```text
[ ] 累积：FakeLLM 返回 ["你","好","呀"] → outbound_text == "你好呀"
[ ] turn_meta 过滤（核心）：构造含 turn_meta 的事件序列 → 断言 outbound_text 不含
    "role_mode" / "scene_state" / "behavior" / "action_intent" 等键名，且长度等于 token 之和
[ ] 未知 kind 被忽略（向前兼容）
[ ] 空累积 → error_kind == "empty_response" 且 outbound_text == 空回复兜底文案（非空、非空白）
[ ] 全空白累积（" " / "\n"）→ 同上（strip 后判空）
[ ] FakeLLM raise EmptyLLMResponseError → error_kind == "empty_response"
[ ] FakeLLM raise openai.APIStatusError → error_kind == "llm_error"，文案不含 status/异常类名
[ ] FakeLLM raise ValueError("boom") → error_kind == "pipeline_error"
[ ] 有 token 无 done → error_kind == "incomplete" 且仍返回累积内容
[ ] 兜底文案表：每个 error_kind 都有非空文案；文案不含 "{", "}", "Traceback", 异常类名
[ ] outbound_text 永不包含 "turn_meta"
```

### 12.2 `tests/integration/test_feishu_adapter_turn.py`

```text
基本轮次
[ ] FakeLLM 有输出 → outbound_text 非空；messages 表恰好 +2 行（human=1, ai=1）★ 不重复落库
[ ] 管线被调用且参数正确：monkeypatch agent_service.stream_chat 捕获
    (session_id == "feishu:ou_A", user_id == "feishu:ou_A", content == inbound.text) ★ 身份透传
[ ] trace 透传：002 建的 trace 被传入（不新建第二个）
[ ] `default_user` 未被使用（断言 user_id != settings.default_user）

多轮连续
[ ] 第二轮同 session → 上下文包含第一轮（断言 FakeLLM.seen_messages 含首轮内容）
[ ] conversations 行数仍为 1（同 session 复用会话，不新建）

串行与隔离
[ ] 同一 session 并发三条 → 完成顺序 == 提交顺序（用带延迟的 FakeLLM + 时间戳断言）
[ ] user A 的轮次阻塞期间（FakeLLM 延迟 0.5s），user B 的轮次 < 0.2s 完成 ★ 不互相阻塞
[ ] A 与 B 的 user_id / session_id / world_id 互不相同

队列上限
[ ] 并发 N+1 条（N = FEISHU_SESSION_QUEUE_LIMIT）→ 恰好 N 条被处理、
    1 条 error_kind == "overloaded"，且过载者未调管线
[ ] 过载后继续发消息（等前批完成）→ 恢复正常处理

计数健壮性（核心）
[ ] 管线抛异常后，同一 session 仍能正常完成下一轮 ★ 计数必减
[ ] 连续多次异常 → load 归零（断言内部计数为 0）

错误映射
[ ] 身份映射失败（monkeypatch service 抛异常）→ error_kind == "identity_error"，未调管线
[ ] LLM 异常 → error_kind == "llm_error"，messages 表**不增加**（无半成品）

零管线改动（回归）
[ ] 既有 Web 路径测试零失败（api + unit 全绿）
```

### 12.3 测试基建

| 需要 | 做法 |
|---|---|
| LLM 注入 | `llm_factory.set_llm(FakeLLM(...))`（conftest 已 autouse 清理） |
| 后台任务收尾 | 复用 002 的 `spawn_background` → conftest 既有等待覆盖 |
| 适配器状态隔离 | 测试文件 autouse fixture 调 `reset_feishu_adapter()`（清锁与计数） |
| 顺序断言 | 用 `FakeLLM` 的可编程延迟 + `time.perf_counter()`；等待用 `conftest.wait_until`，禁止裸 `sleep` |

**执行级别**：Focused（2 个新文件）→ Module → **Integration**（走 DB 与多模块）→ Fast。

## 13. Acceptance Mapping

> 对齐 [../tasks.md](../tasks.md) FEISHU-004 的 8 条 AC。

```text
[ ] 飞书文本事件 → stream_chat → 非空回复；turn_meta 内容不进入回复文本                  (AC-1)
[ ] 使用 core.llm_factory.get_llm 获取实例（FEISHU_LLM_PROFILE 空走默认）；无直接构造 LLM (AC-2)
[ ] 多轮连续：第二轮上下文含第一轮；同 user_id 的 Memory / World / Relationship 延续      (AC-3)
[ ] save_turn 与 mode 写回照常在管线内发生；Adapter 不重复落库（messages 恰好 +2）        (AC-4)
[ ] 同一 user_id 并发消息串行（顺序断言）；超 FEISHU_SESSION_QUEUE_LIMIT 按过载处理        (AC-5)
[ ] 管线异常映射对齐既有语义；不写入半成品回复                                          (AC-6)
[ ] git diff 不含 api/v1/chat.py / api/v1/schemas.py / application/chat_pipeline.py      (AC-7)
[ ] channels/** 无 character.* / services.memory*|world*|state*|relationship* / chains.* /
    直连 repositories.* 的 import（静态断言，FEISHU-006 常驻）                            (AC-8)
[ ] user A 不阻塞 user B（独立用例）
[ ] 单会话异常后仍可继续对话（计数必减）
```

## 14. Out of Scope

| 不做 | 归属 / 理由 |
|---|---|
| 出站 `im/v1/messages/.../reply`、文本规范化、超长切分、出站重试与幂等 | FEISHU-005 |
| 身份映射实现与 `channel_identities` | FEISHU-003 |
| Webhook / 验签 / 解密 / 事件去重 | FEISHU-002 |
| 错误矩阵全量收口 / 边界静态断言 / 冒烟清单 | FEISHU-006 |
| 对飞书做流式分片推送 | 架构 §7.2 明确不做 |
| 主动消息（Proactive） | **触发方不做**（架构 §7.2 / §2.5.6）；**出口能力**属 FEISHU-005。本 Task 只走 Reply 形态 |
| 修改管线 / 新增 post_process 步骤 / 新增链条 | **永久不做**（AC-7 是硬闸） |
| 跨进程串行 / 分布式锁 / MQ | 不做（§10.1；TESTING.md §2 项目无 Redis/MQ） |
| 轮次级幂等重放 | 不做（§10.2） |

## 15. Implementation Notes

### 15.1 这是"零侵入"的验收点

本 Task 是判断"飞书是否真的只是 Channel Adapter"的**唯一判据**。实现完成后必须能回答：

```text
[ ] application/chat_pipeline.py 一行未改？
[ ] api/v1/chat.py 与 schemas.py 一行未改？
[ ] services/ 既有域服务一行未改？
[ ] 所有对话逻辑都在既有管线里？（Adapter 内没有"构建上下文/调链/算状态"）
[ ] channels/** 里没有 memory/world/character 的 import？
```

任一为否 → 说明职责已经从"接入"变成"侵入"，必须回头收敛。

### 15.2 为何不复用 `post_process.get_user_write_lock`（**决策 + 被否决方案**）

| 方案 | 结论 |
|---|---|
| **自有锁（采用）** | `channels/feishu/adapter.py` 内模块级 `dict[str, asyncio.Lock]` | 
| 复用 `application.post_process.get_user_write_lock` | **否决** |

否决理由：① 语义不同——那把锁的职责是"per-user 状态写互斥"，若用它做"整轮串行"，其含义被悄悄拓宽（从一个写临界区变成跨 LLM 的长临界区），未来维护者极易误判；② 耦合——Adapter 需 import `application.post_process` 仅为一个锁，把渠道调度绑到后处理模块；③ 死锁/顺序面变复杂——`post_process` 的任务也在同一把锁上排队，两者互相等待的路径需要额外论证。

**若未来出现第二个渠道**：把该锁提取为 `app/channels/locks.py`（渠道层通用），而不是上移到 core。

### 15.3 与架构 §6.2 #12 的对齐：**拒绝最新**（**已回填架构**）

架构 §6.2 #12 **已回填**为："单会话队列超 `FEISHU_SESSION_QUEUE_LIMIT` → **拒绝新到消息**并提示"，与本 Detail 的冻结方案一致，不再构成偏差。

**"丢弃最旧"被否决的理由**（架构引用本节为出处）：① 用 `asyncio.Lock` 无法优雅取消"已排队协程"，要实现真"丢最旧"必须引入显式任务簿记 + 取消语义（约数十行状态机），与"第一阶段最小闭环"不成比例；② "拒绝最新"能严格保持已接受消息的 FIFO 与上下文顺序，而"丢最旧"会让用户看到后一条的回复却等不到前一条（更难解释）；③ 用户可理解（"你发得太快了"）。

### 15.4 文案与配置的边界

- 兜底文案**不是阈值**，因此**不进** `core/settings/`（001 已冻结配置集，§15 与 001「不新增配置键」原则一致）。
- 它们放在 `adapter.py` 的模块级常量表中，便于单测逐条断言"非空、不含技术细节"。
- 文案内容属**话术**，未来若需要角色化/多语言，属独立事项（不属本 Task）。

### 15.5 `outbound_text=None`（静默策略）的取舍

架构 §6.2 #8 允许"兜底文案 / 静默"二选一。本 Detail **冻结为"发兜底文案"**（不发静默）：
- 理由：飞书链路上"用户发消息后什么都没收到"是最差的体验，且用户会重发 → 放大负载。
- 因此 `TurnOutcome.outbound_text` 在**所有**错误路径上都非空；`None` 仅作为**类型上保留**的出口（未来若明确要求静默，不必改数据结构）。
- 005 仍应把 `None` 当作"不发送"处理（防御性），但本 Task 不会产出 `None`。

### 15.6 Implementation Order

```text
1. adapter.py：TurnOutcome + 兜底文案常量 + 锁/计数 + reset 接缝
2. 流消费内部函数（turn_meta 过滤 / 累积 / error_kind 判定）→ 单测（红→绿）
3. handle_inbound_message 主体（resolve → 排队 → get_llm → stream_chat → outcome）
4. 集成测试（+2 行落库 / 身份透传 / 串行 / 不互相阻塞 / 计数必减）
5. 与 005 的交接点（先留调用 005 占位，005 落地后接上）
6. Focused → Module → Integration → Fast
7. 收口：git diff 证明 AC-7（Web 路径与管线零改动）
```
