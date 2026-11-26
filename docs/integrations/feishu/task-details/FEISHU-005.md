# FEISHU-005 — Feishu Outbound Messaging

> 上游：[../tasks.md](../tasks.md) FEISHU-005 ｜ 架构：[../architecture.md](../architecture.md) §2.5（双向模型）/ §3.4（反向解析）/ §6.2 #9~#11 #14~#15 ｜ 依赖：**FEISHU-001、FEISHU-002、FEISHU-003、FEISHU-004**
> Priority：**P0** ｜ 层级：Outbound（P0 链的最后一环）
> **本 Task 的产出形态**：一个**统一出站能力** —— 既能回复用户刚发的那条消息（**Reply**），也能给任意已知内部用户发一条消息（**Proactive**）。
> **本 Task 不实现 Autonomy**：只交付"飞书能成为主动消息出口"这一能力；"何时开口"不在本 Task（架构 §2.5.6）。

---

## 1. Goal

把"一段已经决定要发的文本"投递到飞书，并**同时覆盖两种出站形态**：

```text
                      ┌─────────────────────────────────────────┐
                      │  channels/base.py（通道无关契约）          │
                      │  OutboundMessage / RecipientRef /        │
                      │  SendResult / ChannelErrorKind           │
                      └───────────────────▲─────────────────────┘
                                          │  ChannelAdapter.send(msg)
                      ┌───────────────────┴─────────────────────┐
                      │                                         │
              ① Reply 形态                               ② Proactive 形态
         reply_ref 非空                              reply_ref 为空
         （用户刚说过话）                              （角色主动开口）
                      │                                         │
         recipient 已知 + 锚点已知                    recipient = internal_user_id
         → 无需解析收件人                             → ★ 必须反向解析
                      │                                         │
         POST im/v1/messages/{message_id}/reply      resolve_recipient(user_id)
                      │                                         ↓
                      │                                 external_id = open_id
                      │                                         ↓
                      │                                 POST im/v1/messages
                      │                                      ?receive_id_type=open_id
                      └───────────────────┬─────────────────────┘
                                          ▼
                                    飞书用户
```

本 Task 交付 5 件事：

1. **统一出站模型**：`OutboundMessage`（`channels/base.py`，FEISHU-001 已冻结契约）+ Feishu 侧 `ChannelAdapter.send` 实现。
2. **两条发送路径**：Reply（锚定 `message_id`）/ Proactive（`internal_user_id → open_id`）。
3. **收件人解析**（Proactive 独有）：调用 FEISHU-003 的 `resolve_recipient`；未命中**不发、不猜**。
4. **可靠性**：两套幂等键 + 退避重试 + 超长切分 + 逐段失败收口。
5. **失败隔离**：投递失败**不回滚**任何已落库事实；本 Task **零 DB 访问**。

## 2. Dependencies

| 依赖 | 提供物 | 使用方式 |
|---|---|---|
| **FEISHU-001** | `channels/base.py` 出站契约（`OutboundMessage` / `RecipientRef` / `SendResult` / `ChannelErrorKind` / `ChannelAdapter`）；`client.py` 的 `Transport` / `tenant_access_token()` / `RetryPolicy` / `errors.classify` | **直接复用**，不新建 HTTP 层、不新建错误体系 |
| **FEISHU-002** | `adapter.handle_inbound_message` 的收尾位置 | 在此接线 Reply 出站调用 |
| **FEISHU-003** | **`channel_identity_service.resolve_recipient(internal_user_id, channel)`** | **Proactive 的唯一收件人来源**（本 Task 的核心新依赖） |
| **FEISHU-004** | `TurnOutcome`（`outbound_text` / `source_message_ref` / `user_id` / `turn_id` / `error_kind`） | Reply 形态的文本与锚点来源 |
| 既有 | `json`（标准库） | `content` 字段的 JSON 字符串编码 |

> **反向契约**：本 Task **不判断**业务错误（`error_kind` 已由 004 判定）；**不读** conversation；**不调**管线；**不决定**何时发送。它只回答一个问题："这段文本怎么安全地送到这个飞书用户。"

## 3. Scope

**做**：

- `app/channels/feishu/client.py`：新增 `reply_message(message_ref, text)` / `send_message(recipient_external_id, text)` —— 两个飞书 API，复用 001 的 token / transport / 重试 / 错误分类。
- `app/channels/feishu/outbound.py`（新增，纯函数）：`normalize_text` / `split_text`。
- `app/channels/feishu/delivery.py`（新增）：`FeishuChannelAdapter`（实现 `ChannelAdapter` 协议）+ `deliver_reply` / `send_proactive` 编排（形态判定 → 收件人解析 → 切分 → 逐段发送 → 幂等 → 收口）。
- `app/channels/feishu/errors.py`：新增 "Feishu 错误 → `ChannelErrorKind`" 映射 + 业务码可重试性判定（仍是唯一判定点，不新增错误子类）。
- `app/channels/feishu/adapter.py`：Reply 形态接线（由 004 产出 `TurnOutcome` 之后调用）。

**不做**（见 §14）：**Autonomy / Scheduler / Life Loop / Proactive Policy / 主动消息触发方 / 主动消息推送循环**、卡片 / 富文本 / 流式 / 图片 / 文件 / 语音 / 撤回 / 编辑。

## 4. Files

### New Files

```text
app/channels/feishu/outbound.py              # 纯函数：normalize_text / split_text（两形态共用）
app/channels/feishu/delivery.py              # ★ FeishuChannelAdapter + 出站编排（Reply / Proactive）
tests/unit/test_feishu_outbound.py           # 规范化 / 切分（不丢字不重复 / 边界 / emoji）
tests/unit/test_feishu_delivery.py           # 形态判定 / 幂等 / 逐段顺序 / 重试 / 收口（假传输）
tests/unit/test_feishu_adapter_protocol.py   # FeishuChannelAdapter satisfies ChannelAdapter（契约一致性）
tests/integration/test_feishu_reply_flow.py      # 对话→回复→出站 全链
tests/integration/test_feishu_proactive_flow.py  # ★ internal_user_id → 解析 → send 全链
```

### Modified Files

```text
app/channels/feishu/client.py     # +reply_message / +send_message（复用既有 transport/token/retry）
app/channels/feishu/adapter.py    # Reply 形态接线
app/channels/feishu/errors.py     # Feishu 错误 → ChannelErrorKind 映射 + 业务码可重试性
```

### Forbidden Files

```text
application/**  services/**（既有域服务）  repositories/**  models/**  character/**  chains/**  prompts/**
api/**（含 router.py —— 002 已注册完毕）
core/settings/feishu.py                    # 配置已冻结（001）
migrations/**                              # 无表
repositories/conversation_repository.py    # ★ 落库归管线；005 零 DB
任何 Autonomy / Life Loop / Scheduler / Policy 模块   # ★ R3（本次修订新增）
```

## 5. Architecture / Data Flow

### 5.1 Reply 形态（用户刚说过话）

```text
FEISHU-004 产出 TurnOutcome(
    user_id="feishu:ou_A", outbound_text="……",
    source_message_ref="om_xxx", turn_id="123")
        │
        ▼
adapter（004 的收尾）→ delivery.deliver_reply(outcome)
        │
        ├─ text = outbound.normalize_text(outbound_text)   → 空则不发
        ├─ parts = outbound.split_text(text, FEISHU_MAX_REPLY_CHARS)
        ├─ recipient = RecipientRef(channel, external_id=resolve_recipient(user_id))
        │     └─ 解析失败 → 记 warning，但 **Reply 形态仍可发**（有锚点，定位靠 reply_ref）
        ├─ 逐段：幂等键 = (reply_ref, index) → client.reply_message(reply_ref, part)
        └─ 收口：不抛异常
```

### 5.2 Proactive 形态（角色主动开口，**本次只交付能力**）

```text
【未来 Autonomy】（本次不实现）
        │  产出一段文本 + internal_user_id + 自己的 idempotency_key
        ▼
delivery.send_proactive(
        internal_user_id="feishu:ou_A",
        text="……",
        idempotency_key="<调用方生成，必填>")
        │
        ├─ 0. 契约校验：无 idempotency_key → **拒绝发送**（记 error，架构 §6.2 #15）
        ├─ 1. recipient_ref = channel_identity_service.resolve_recipient(user_id, "feishu")
        │        └─ None → **不发、不猜、不兜底**，记 warning（架构 §6.2 #14）
        ├─ 2. text = outbound.normalize_text(text)      → 空则不发
        ├─ 3. parts = outbound.split_text(text, FEISHU_MAX_REPLY_CHARS)
        ├─ 4. 逐段：幂等键 = (channel, recipient, idempotency_key, index)
        │        → client.send_message(recipient_ref.external_id, part)
        └─ 5. 收口：不抛异常（未来调用方据 SendResult 决定是否重试/记账）
```

### 5.3 关键不变式

| 不变式 | 含义 |
|---|---|
| **两条路径共用一套实现** | 规范化 / 切分 / 幂等 / 重试 / 收口只有一份；差异仅在"用哪个 API" |
| **投递与落库解耦** | 发送发生在管线 `save_turn` **之后**；失败**不回滚**任何已落库事实 |
| **零 DB 访问** | 005 不 import 任何 repository，不读不写 conversation |
| **不产生第二份回复** | 文本来源**只有**调用方给的 `text`；禁止从 conversation 反查"刚才说了什么" |
| **失败不冒泡** | 终败只记日志；`send` 返回 `SendResult(ok=False)` 而非抛异常 |
| **收件人只能来自身份表** | Proactive 的 `external_id` **只能**来自 `resolve_recipient`；不得拼接、不得从 `session_id` 反推（架构 §3.4） |
| **不重复投递** | 同一逻辑消息在进程内只成功发送一次 |

## 6. Detailed Implementation

### 6.1 出站消息模型：**统一，不拆两个 model**（决策）

用户建议"区分 `ReplyMessage` / `ProactiveMessage`，或用统一 outbound request + optional reply context，**不要过度设计**"。本 Task **选择统一模型**（契约已在 FEISHU-001 §3 冻结）：

| 形态 | `reply_ref` | `idempotency_key` | 底层 API |
|---|---|---|---|
| **Reply** | 非空 | 可省（`reply_ref` 充当） | `POST im/v1/messages/{message_id}/reply` |
| **Proactive** | 空 | **必填** | `POST im/v1/messages?receive_id_type=open_id` |

**为什么不拆两个 model**：

1. 两者差异**只有两个字段**（锚点 vs 幂等键），其余（`text` / `recipient` / `channel` / `metadata`）完全相同；拆开会产生两份几乎一样的类型与两条几乎一样的实现路径。
2. 形态判定是**一行 if**（`reply_ref is None`），比"调用方必须先选类型"更少出错 —— 后者等于把飞书的 API 形态泄漏给调用方（核心不该知道飞书有几种发送接口）。
3. 统一的 `send` 让**未来的多通道**（Telegram / Discord）各实现同一个协议，而不必各自发明两套模型。

**不做**：不为两个形态各写一套编排（只在最外层做形态判定，内部完全共用）。

### 6.2 Reply 路径

```text
client.reply_message(message_ref: str, text: str) -> SendResult
```

| 项 | 值 |
|---|---|
| Method | `POST` |
| URL | `{feishu_api_base}/open-apis/im/v1/messages/{quote(message_ref)}/reply` |
| Headers | `Authorization: Bearer <tenant_access_token>`、`Content-Type: application/json; charset=utf-8` |
| Body | `{"msg_type": "text", "content": "<json.dumps({\"text\": text}, ensure_ascii=False)>"}` |
| Timeout | `feishu_timeout_seconds` |

- `content` 是**JSON 字符串**（不是对象）：先 `json.dumps(..., ensure_ascii=False)` 再作为 `content` 的**值**；`ensure_ascii=False` 让中文不被转义为 `\uXXXX`。
- `message_ref` 必须 `quote` 后再拼进 path（防注入 / 异常字符）。
- **不因 Reply 运行时错误而降级到 Send**：Reply 失败（权限 / 撤回 / 窗口）若改走 Send，会让"发到哪"变得不可预测。**唯一的形态切换条件是结构性原因**——即 `reply_ref` 合同上就不存在（Proactive）。这是对 tasks.md "固定策略二选一"的**冻结结果**。

### 6.3 Proactive 路径与收件人解析

```text
delivery.send_proactive(internal_user_id: str, text: str, idempotency_key: str) -> SendResult
```

**收件人解析（Proactive 独有，架构 §3.4）**：

```text
internal_user_id          例 "feishu:ou_A"
        ↓  channel_identity_service.resolve_recipient(internal_user_id, "feishu")
RecipientRef(channel="feishu", external_id="ou_A")
        ↓  作为 receive_id
POST {feishu_api_base}/open-apis/im/v1/messages?receive_id_type=open_id
Body: {"receive_id": "<open_id>", "msg_type": "text", "content": "<json 字符串>"}
```

| 情形 | 处理 |
|---|---|
| 解析成功 | 正常发送 |
| 解析失败（`None`） | **不发、不猜、不兜底到其他收件人**；记 `warning`（含 `internal_user_id`）；返回 `SendResult(ok=False, error=not_found)` |
| `idempotency_key` 为空/空白 | **拒绝发送**（调用方契约违规）；记 `error`；返回 `SendResult(ok=False, error=invalid_request)` |
| 文本为空 | 不发空消息；返回 `ok=False, error=invalid_request` |

- **`receive_id_type=open_id` 是本项目的固定选择**：`channel_identities.external_id` 存的就是 `open_id`（架构 §3.2），且它对同一应用稳定。
- **为什么 Proactive 不用 `reply`**：主动消息**没有**用户消息可锚定（这正是本 Task 存在的理由）。
- **为什么不走 `chat_id`**：`chat_id` 属于会话而非用户；第一阶段只支持单聊（架构 §3.3），且 `chat_id` 不参与身份映射。
- **`SendResult.external_message_id`**：飞书返回的 `message_id` —— 只用于日志与未来调用方记账，**不写入 DB**（本 Task 零 DB）。

### 6.4 幂等（**两套键**，本次修订核心）

| 形态 | 幂等键 | 理由 |
|---|---|---|
| **Reply** | `(reply_ref, segment_index)` | 有外部消息 id 可依托；同一用户消息的回复天然唯一 |
| **Proactive** | `(channel, recipient.external_id, idempotency_key, segment_index)` | **无外部消息 id**，因此必须由**调用方**提供 `idempotency_key`（未来 Autonomy 侧生成） |

| 项 | 决定 |
|---|---|
| 介质 | **进程内** `dict[str, float]` + `threading.Lock`（对齐 002 的去重表与 `api/rate_limit.py` 范式） |
| TTL | 复用 `feishu_dedupe_ttl_seconds`（**不新增配置键**） |
| 语义 | "该段曾成功投递过" → 跳过重发（记 debug），不报错 |
| 覆盖范围 | **仅防自身重复调用**（同一逻辑消息被投递两次） |
| **不覆盖** | "请求已送达但响应丢失"造成的重复（飞书 reply/send **不提供幂等键**，协议层无法消除） |
| 跨进程 | 不覆盖（单实例第一阶段；与 002/003/004 一致的范围限制） |
| 重置接缝 | `reset_delivery_state()`（与 `reset_feishu_client()` / `reset_event_state()` / `reset_feishu_adapter()` 并列） |

**与既有 `proactive_actions.dedupe_key` 的关系（重要）**：核心既有的 V7 主动链路**已经**在 `proactive_actions` 上有 `dedupe_key` 与状态机（`proactive_repository.enqueue` 拒绝重复键）。因此未来 Autonomy 接入时，`idempotency_key` 的**现成取值**就是该行的 `dedupe_key`（或 `action.id`）—— **不需要新造幂等机制**（架构 §2.5.6 候选 A）。本 Task 只要求"调用方提供它"。

### 6.5 官方 API 复核清单（**编码前必做**）

架构明确要求"以官方 Feishu API 文档为最终依据，不要凭记忆固定接口细节"。以下**必须逐条核对**：

```text
[ ] Reply 端点：POST /open-apis/im/v1/messages/{message_id}/reply
[ ] Send  端点：POST /open-apis/im/v1/messages?receive_id_type=open_id
[ ] Reply 请求体字段名：msg_type（还是 message_type？）+ content
[ ] Send  请求体字段名：receive_id + msg_type + content（receive_id_type 在 query 还是 body？）
[ ] content 是否为「JSON 字符串」（而非嵌套对象）—— 若是字符串，需 json.dumps 后再放入
[ ] Authorization 头格式：Bearer <tenant_access_token>
[ ] Content-Type：application/json; charset=utf-8
[ ] 文本消息 content 形态：{"text": "..."}
[ ] 单条文本长度上限与超限错误码
[ ] receive_id_type 支持值（open_id / union_id / user_id / email / chat_id）与 1:1 场景推荐值
[ ] 业务码语义：成功（code=0）；哪些码属"频率限制 / 可重试"
[ ] Reply 在何种情况下不可用（撤回 / 超回复窗口 / 权限）
[ ] 权限项：im:message / im:message:send_as_bot 的具体要求
```

**与架构/本文档冲突时**：以官方文档为准，并把差异记入 `regression-checklist.md`（不静默偏离）。

### 6.6 文本规范化（`outbound.normalize_text`）

```text
normalize_text(text: str) -> str
```

| 步骤 | 规则 | 理由 |
|---|---|---|
| 1 | `\r\n` / `\r` → `\n` | 统一换行 |
| 2 | 移除 C0 控制字符**（保留 `\n` / `\t`）** | 部分控制字符会导致 API 错误或显示错乱 |
| 3 | 去首尾空白（`strip()`） | 模型输出常带尾随换行 |
| 4 | **不动**内部空白、缩进、Markdown 标记 | 改写内容不属于投递层职责 |

- **不做** Markdown → 纯文本转换（飞书 text 消息不渲染 Markdown；转换属表现层决策，架构 §7.3 后置）。
- **不做** 长度截断（截断只在切分阶段，且为最后手段）。
- 空结果 → 投递层直接返回（不发空消息，架构 §6.2 #8）。

### 6.7 超长切分（`outbound.split_text`）

```text
split_text(text: str, max_chars: int) -> list[str]
```

**不变式（硬性，直接作断言）**：

```text
"".join(parts) == text                       # 不丢字、不重复、不插入分隔符
all(len(p) <= max_chars for p in parts)
parts 非空（text 非空时）
```

**切分点优先级**（就近向前取）：段落 `\n\n` → 行 `\n` → 句末标点 `。！？；…` / `. ! ? ;` → 空格 / 逗号 → 硬切（按代码点）。

**实现要点**：

- **Python `str` 切片按代码点**，不会产生非法 UTF-8、不会拆开代理对（astral emoji 安全）；中日文、emoji 均安全。
- **ZWJ 组合 emoji** 理论上可能被拆开（视觉拆分）。缓解：优先自然边界；接受残余风险（不改写内容优先于视觉完美）。
- **段数上限** `max_parts`（模块常量，如 10）：超出 → 前 `max_parts-1` 段正常发送，最后一段**截断**并标记（架构 §6.2 #10）。属病态路径（回复生成上限 `ANSWER_MAX_TOKENS=60`）。
- **顺序发送**：`for part in parts: await send(part)` 串行 await，保证到达顺序；段间**不 sleep**。

### 6.8 重试

**复用** 001 的 `RetryPolicy`（`feishu_http_max_attempts` / `feishu_http_backoff_seconds` / `feishu_http_backoff_max_seconds`）与可注入 `sleep` 的 `_with_retry`。**不新建重试机制**。

| 情形 | 重试 | 依据 |
|---|---|---|
| `429` | ✅ | `FeishuRateLimitError.retryable=True` |
| `5xx` | ✅ | `FeishuServerError.retryable=True` |
| 超时 / 连接失败 / DNS | ✅ | `FeishuTimeoutError.retryable=True` |
| 业务码 ∈ 频率限制类 | ✅ | §6.9 |
| `4xx`（400/401/403/404/422） | ❌ | `FeishuAuthError` / `FeishuClientError` |
| 认证失败 | ❌ | 重试无意义 |
| 未知业务码 | ❌ | 保守，避免放大 |

- **退避**：`min(backoff_seconds * 2^(attempt-1), backoff_max_seconds)`（001 实现）；测试注入 fake sleep（**零真实等待**）。
- **jitter**：架构未要求 → **不引入**（保持确定性，便于断言序列）。
- **日志**：每次重试 `warning`（operation / attempt / status / code）；终败 `error`；**不含**回复全文（用 `content_preview`，受 `log_content_preview_chars` 控制）。

### 6.9 业务码 → `ChannelErrorKind` 映射（唯一判定点）

飞书**可能在 HTTP 200 下返回非零业务码**（001 已在 token 端点踩过）。因此出站必须：

```text
1. errors.classify(operation, http_status, feishu_code)  → FeishuError | None
2. HTTP 2xx 且 code == 0                                 → 成功
3. HTTP 2xx 且 code ∈ RETRYABLE_BUSINESS_CODES           → FeishuRateLimitError（retry）
4. HTTP 2xx 且 code 为其他非零                            → FeishuClientError（不重试）
```

**再映射为通道无关词汇**（核心只见 `ChannelErrorKind`）：

| Feishu 错误 | → `ChannelErrorKind` |
|---|---|
| `FeishuRateLimitError` | `rate_limited` |
| `FeishuServerError` | `server_error` |
| `FeishuTimeoutError` | `timeout` |
| `FeishuAuthError` | `auth` |
| `FeishuClientError` | `client_error` |
| `FeishuConfigError` | `invalid_request` |
| `FeishuDisabledError` | `disabled` |
| 收件人解析失败 | `not_found` |
| 其他 | `unknown` |

- `RETRYABLE_BUSINESS_CODES: frozenset[int]` 放 `errors.py`（内容按官方文档填写；**未知码一律不重试**）。
- **不新增错误子类**；`classify` 仍是**全项目唯一**的 HTTP/业务码 → 错误映射点。
- **禁止**在 `client.py` / `delivery.py` 写 `if code == xxx` 之类的散落判断。

### 6.10 逐段失败的收口策略（**冻结**）

```text
第 k 段成功、第 k+1 段终败 → 停止后续段，记 error（含已发段数 / 失败段号）
```

- **不继续后续段**：让用户看到"不完整但连续"的文本，避免"中间缺一段、后面还在发"。
- **不重发已成功段**（幂等保护）。**不回滚**任何落库事实。**不向用户发"我发送失败了"**（噪声，且可能同样失败）。

### 6.11 失败隔离（**硬约束**，架构 §6.2 #9）

| 事实 | 状态 | 何时发生 |
|---|---|---|
| `messages`（human + ai）/ `conversation.mode` | ✅ 已落库 | 管线，**在出站之前** |
| `post_process`（scene / state / summary / memory / action） | ✅ 已调度 | 管线 |
| Memory / World / Inventory / Relationship / Character | ✅ 已更新 | 管线与后台 |
| **飞书投递成功 / 失败** | — | **本 Task** |

**结论**：投递失败**只影响"用户看不看得到"**，不影响角色是否"记得"。下一轮对话仍正常。§12 有逐项断言。

**实现纪律**：`delivery.py` / `client.py` / `outbound.py` **不得** import `repositories` / `conversation_service` / `application.post_process`。

### 6.12 对未来调用方的契约（**本 Task 定义，不实现调用方**）

未来 Autonomy（或任何出站调用方）必须提供：

```text
必填：internal_user_id（收件人内部标识，如 "feishu:ou_A"）
必填：text（要发送的文本）
必填（Proactive 无锚点时）：idempotency_key（调用方生成，稳定且可复用于重试）
可选：channel（默认 "feishu"）
```

- **调用方不得**：自行拼接 `open_id`、自行调用飞书 API、自行选择 Reply/Send、自行做文本切分或重试。
- **Feishu 侧不得**：决定何时调用、决定要不要发、读取 Autonomy 的状态。

两者的**唯一接触面**是 `channels/base.py` 的契约（架构 §2.5.5）。

## 7. Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `FeishuChannelAdapter.send` | `OutboundMessage` | `SendResult` | 实现 `ChannelAdapter` 协议；**不抛异常**；内部按 `reply_ref` 选 API |
| `delivery.deliver_reply` | `TurnOutcome`（004 产出） | `SendResult` | Reply 形态入口（adapter 调用） |
| `delivery.send_proactive` | `internal_user_id`, `text`, `idempotency_key` | `SendResult` | Proactive 形态入口（未来调用方使用；**本 Task 只交付能力**） |
| `client.reply_message` | `message_ref`, `text` | `SendResult` | 单次 Reply 请求（含重试） |
| `client.send_message` | `recipient_external_id`, `text` | `SendResult` | 单次 Send 请求（含重试） |
| `outbound.normalize_text` | `str` | `str` | 纯函数；幂等 |
| `outbound.split_text` | `str`, `max_chars` | `list[str]` | 纯函数；不丢字/不重复/不插分隔符 |
| `reset_delivery_state` | — | `None` | 测试接缝 |

**异常契约**：上表**所有**能力**永不抛出**。任何异常（token 失败 / transport 异常 / JSON 编码异常 / 未知错误）都在内部转为 `SendResult(ok=False, error=...)` + 日志。这是"投递不冒泡"不变式的可执行形式，也是 `ChannelAdapter` 协议可被核心安全调用的前提。

## 8. Data Model

**无数据库、无迁移、无新表**。进程内状态：

```text
_delivered: dict[str, float]        # 幂等键 → 时间戳（TTL 惰性驱逐）
_lock: threading.Lock
```

**为何不持久化投递状态**：

1. Reply 形态的幂等键由入站消息 id 派生 —— 复投的唯一来源（飞书重推同一事件）已被 FEISHU-002 的 `event_id` 去重拦住。
2. Proactive 形态的幂等**已在核心侧**由 `proactive_actions.dedupe_key` + 状态机保证（既有能力）；本层的表只是"同一进程内防重复调用"的第二道防线。
3. 持久化会引入表 + 迁移 + 清理循环，收益为负。

## 9. Error Handling

| 架构 §6.2 | 场景 | 本 Task 处理 | 用户可见 |
|---|---|---|---|
| #9 | Feishu API 调用失败（两形态同规则） | 429/5xx/timeout 退避重试（有上限）；4xx 不重试；终败 `error` 日志，**不改会话状态** | 本轮回复丢失 / 主动消息本轮不达；下一轮正常 |
| #10 | 回复超长 | 按 `FEISHU_MAX_REPLY_CHARS` 切分**顺序**发送；单条仍超限则截断并标记 | 消息分段到达 |
| #11 | 发送重复 | 两套幂等键（§6.4）防自身重复投递 | 同一条只收到一次 |
| #14 | 收件人解析失败（Proactive） | `resolve_recipient → None` → **不发、不猜、不兜底**；记 warning | 该用户收不到这条主动消息 |
| #15 | 无锚点且无幂等键（Proactive） | **拒绝发送**；记 error（调用方契约违规） | 无 |
| — | `outbound_text` / `text` 为空 | 不发送（不发空消息） | 无 |
| — | token 获取终败 | 记为投递失败 | 本轮不达 |
| — | 第 k+1 段终败 | 停止后续段 + `error` 日志（含已发段数） | 收到前 k 段 |
| — | `FeishuDisabledError`（未启用时被调用） | 不发送；返回 `error=disabled` | 无 |

**统一契约**：投递层**不产生 REST 响应**（由后台任务或未来调用方驱动）；唯一失败表现是日志 + 用户少收到消息。

## 10. Concurrency / Idempotency

| 项 | 决定 |
|---|---|
| 单条消息内部 | **串行**逐段发送（保顺序） |
| 不同会话 / 不同收件人 | 互不阻塞（004 的会话锁在组装 `TurnOutcome` 时已释放，投递在锁外） |
| 段内重试 | 复用 001 的 `_with_retry`（同段重试，不影响其他段） |
| 与 004 锁的关系 | **投递在锁外** → 慢投递不阻塞同一用户下一轮（避免"发送慢 → 对话卡住"） |
| Reply 幂等 | `(reply_ref, index)` |
| Proactive 幂等 | `(channel, external_id, idempotency_key, index)` |
| 重复投递防护 | 进程内幂等表 + 上游 002 的 `event_id` 去重（Reply）+ 核心 `dedupe_key`（Proactive） |
| 跨进程 | 不覆盖（单实例第一阶段） |

## 11. Security

| 项 | 要求 |
|---|---|
| **token 不泄漏** | `Authorization: Bearer <token>` 只出现在透传给 `Transport` 的 headers；**不得**进日志 / 异常 / `SendResult` |
| **文本不进日志全文** | 用 `core.logutils.content_preview`（受 `log_content_preview_chars`，默认 0）；日志只记 `len` / 段数 / 锚点 ID |
| **锚点与 open_id 可记** | `message_id` / `open_id` 是应用内标识、非凭据，允许入日志（排障必需） |
| **响应体不整体入日志** | 失败只记 `status` / `code` / `msg` 摘要（截断），不 dump 整个响应 |
| **URL 拼接** | `message_ref` 经 `quote` 后拼进 path，禁止字符串直拼 |
| **错误词汇不泄漏供应商细节** | 核心只看到 `ChannelErrorKind`；飞书业务码只出现在 `channels/feishu/` 的日志里 |
| **不落文本到 DB** | 本 Task 零 DB，无"出站副本"存储面 |
| **R3：不接触 Autonomy** | 不 import 任何 Autonomy / Life Loop / Scheduler / Policy 模块；不读取其状态 |

## 12. Testing

零真实网络（假 `Transport`）、零真实 LLM。

### 12.1 `tests/unit/test_feishu_outbound.py`（纯函数）

```text
规范化
[ ] "a\r\nb" → "a\nb"；"a\rb" → "a\nb"
[ ] 首尾空白移除："\n  hi  \n" → "hi"
[ ] 控制字符移除（\x00 \x07），但 \n 与 \t 保留
[ ] 幂等：normalize(normalize(x)) == normalize(x)
[ ] 纯空白 → ""（投递层据此不发送）
[ ] 不改写 Markdown 与内部缩进

切分（核心不变式）
[ ] 不变式：对样本集（短/长/无边界/纯中文/纯 emoji）断言 "".join(parts) == text
[ ] 每段 len <= max_chars
[ ] 边界优先级：\n\n → \n → 句末标点 → 空格 → 硬切（逐级构造用例）
[ ] 无边界超长串（5000 个"啊"）→ 硬切，段数 == ceil(n/max)，不丢字
[ ] 中文标点切分正确（。！？；）
[ ] emoji：单个 astral emoji 不被拆坏；ZWJ 序列不崩
[ ] 段数上限：超 max_parts → 最后一段截断 + 标记
[ ] max_chars=1 不崩；空输入 → 空列表
```

### 12.2 `tests/unit/test_feishu_delivery.py`（假传输 + 假 token）

```text
形态判定（本次修订核心）
[ ] reply_ref 非空 → 调 reply（断言 URL 含 message_id，且未调 send）
[ ] reply_ref 为空 + idempotency_key 非空 → 调 send（receive_id_type=open_id，
    receive_id == 解析出的 external_id，且未调 reply）
[ ] reply_ref 为空 + idempotency_key 缺失/空白 → 拒绝发送 + error 日志 + 零请求
[ ] Reply 运行时失败（403/404）→ **不**改走 send（一次请求后终止，形态不切换）

收件人解析（Proactive）
[ ] monkeypatch resolve_recipient 返回 RecipientRef → send 的 receive_id 正确
[ ] resolve_recipient 返回 None → 零请求 + warning + SendResult(ok=False, error=not_found)
[ ] recipient 的 external_id 只能来自 resolve_recipient（注入假值即被使用，证明无自造逻辑）

文本与切分
[ ] 短文本 → 恰好 1 次请求；content == json.dumps({"text": text}, ensure_ascii=False)
[ ] 超长 → 多次请求，次数 == 段数，顺序与段序一致（假传输记录调用序列）
[ ] text 为空/纯空白 → 0 次请求
[ ] content 为 JSON 字符串且含中文时不被转义（断言无 \uXXXX）

业务码
[ ] HTTP 200 + code=0 → 成功（external_message_id 正确）
[ ] HTTP 200 + 可重试业务码 → 重试
[ ] HTTP 200 + 其他非零码 → 不重试，映射为 client_error

重试
[ ] 429 / 500 / 502 / 503 → 重试；请求次数 == max_attempts
[ ] timeout → 重试；400 / 401 / 403 / 404 → 不重试（1 次）
[ ] 退避序列 = 指数且被 backoff_max 截断（注入记录型 fake sleep，零真实等待）
[ ] 首次失败后成功 → 只记 warning，不记 error

两套幂等
[ ] Reply：同一 reply_ref 投递两次 → 请求次数不翻倍
[ ] Proactive：同一 (channel, external_id, idempotency_key) 投递两次 → 不翻倍
[ ] Proactive：不同 idempotency_key → 各发一次（不复用键）
[ ] reset_delivery_state() 后可重发

错误词汇
[ ] 每个 Feishu 错误类型 → 期望的 ChannelErrorKind（逐条断言映射表）
[ ] SendResult.error 只取 ChannelErrorKind 值域（不出现飞书业务码）

收口
[ ] 第 2 段终败 → 第 3 段未发送（请求次数 == 1 + max_attempts）
[ ] 任何路径都不抛异常（token 失败 / transport 任意异常 / 编码异常）

安全
[ ] caplog 不含 tenant_access_token 值；Authorization 头不出现在日志
[ ] caplog 不含文本全文（长文本场景断言日志长度有界）
```

### 12.3 `tests/unit/test_feishu_adapter_protocol.py`（契约一致性，本次修订新增）

```text
[ ] FeishuChannelAdapter 实例 satisfies channels.base.ChannelAdapter（runtime_checkable）
[ ] send 的签名与协议一致（参数名 / 返回类型）
[ ] send 全程不抛异常（对 5 类假传输异常逐一断言返回 SendResult(ok=False)）
[ ] adapter 模块 import 面：不 import repositories / services.memory*|world* / chains /
    任何 Autonomy 模块（R3 静态断言的一部分）
```

### 12.4 `tests/integration/test_feishu_reply_flow.py`

```text
全链（FakeLLM + 假传输 + 内存 SQLite）
[ ] 一条飞书消息 → 假传输收到 1 次 reply，content 为 AI 回复文本
[ ] messages 表 +2 行；conversation 1 行

解耦（核心）
[ ] 假传输全部失败（500 × max_attempts）→ 不抛；messages 仍 +2 行（★ 不回滚）
[ ] 投递失败后 memories / worlds / relationship_state / character_state 不受影响（逐项断言）
[ ] 投递失败后再发一条 → 正常完成并成功投递（链路未中毒）

顺序
[ ] 超长回复 + 第 1 段延迟 → 飞书侧接收顺序与段序一致
```

### 12.5 `tests/integration/test_feishu_proactive_flow.py`（**本次修订新增**）

> **目的**：验证"已知 `internal_user_id` 可以正确解析到飞书 `external_id` 并发送消息"。**不需要实现 Autonomy**，测试直接调用 `send_proactive` 模拟未来调用方。

```text
收件人解析与发送
[ ] 先经 003 建身份（open_id=ou_A → feishu:ou_A）
[ ] send_proactive("feishu:ou_A", "在吗？", idempotency_key="k1")
    → 假传输收到 1 次 send：receive_id_type=open_id 且 receive_id == "ou_A"
[ ] 未建身份的用户（"feishu:ou_unknown"）→ 零请求 + ok=False + error=not_found
[ ] open_id（ou_A）与 internal_user_id（feishu:ou_A）**不相等**，
    证明解析确实经过 channel_identities 而非字符串截取

幂等与重试
[ ] 同 (recipient, "k1") 调两次 → 总请求 1 次
[ ] 同 recipient、不同 key（k1/k2）→ 各 1 次
[ ] 500 → 重试至上限 → ok=False，且**不抛**

失败隔离
[ ] send 失败后，A 的 conversation / memories / worlds 不被创建或修改
    （Proactive 是纯出站：既不改会话也不写库）
[ ] 无 idempotency_key → 零请求 + error=invalid_request

多用户
[ ] ou_A 与 ou_B 各一次 send_proactive → 各自 receive_id 正确、互不串
```

### 12.6 测试基建

| 需要 | 做法 |
|---|---|
| 假飞书 | 复用 001 的 `set_transport(FakeTransport)` + `reset_feishu_client()`；`FakeTransport` 支持"按调用序返回预设响应/异常序列" |
| token | 假传输对 `tenant_access_token/internal` 返回成功（或直接注入 token 缓存） |
| 身份 | 003 的 `channel_identity_service.resolve` / 仓储（内存 SQLite） |
| 幂等隔离 | 测试文件 autouse fixture 调 `reset_delivery_state()` |
| 日志断言 | `caplog`（对齐 001 的脱敏断言方式） |

**执行级别**：Focused（6 个新文件 + client/errors 改动）→ Module → **Integration**（含落库与身份）→ Fast。

## 13. Acceptance Mapping

> 对齐 [../tasks.md](../tasks.md) FEISHU-005 的 10 条 AC。

```text
[ ] Reply 路径：POST .../messages/{message_id}/reply，content 为 {"text": "..."}；
    reply_ref 缺失时不"对别的消息 reply"，而走 Proactive 路径                          (AC-1)
[ ] Proactive 路径：internal_user_id → resolve_recipient → open_id →
    POST .../messages?receive_id_type=open_id；解析失败 → 不发、不猜、记 warning        (AC-2)
[ ] 无锚点且无幂等键 → 拒绝发送（记 error）                                           (AC-3)
[ ] 空/纯空白文本不发送空消息（兜底文案策略；静默已否决）                              (AC-4)
[ ] 超长按 FEISHU_MAX_REPLY_CHARS 切分顺序发送；"".join(parts) == 规范化文本          (AC-5)
[ ] 429/5xx/timeout 退避重试（有上限）；4xx 不重试；终败只记日志、send 返回 ok=False    (AC-6)
[ ] 两套幂等键；重复投递同一逻辑消息 → 请求次数不翻倍                                  (AC-7)
[ ] 发送失败时 conversation / messages / memory / world / character / relationship
    全部不变（逐项断言）                                                              (AC-8)
[ ] 日志与异常不泄漏 APP_SECRET / ENCRYPT_KEY / tenant_access_token                  (AC-9)
[ ] 不 import 任何 Autonomy / Life Loop / Scheduler / Policy 模块（静态断言）          (AC-10)
[ ] FeishuChannelAdapter satisfies channels.base.ChannelAdapter（契约一致性）
[ ] Reply 运行时失败**不**切换形态到 send（形态只由 reply_ref 有无决定）
[ ] 零 DB 访问（不 import repositories / conversation_service）
```

## 14. Out of Scope

| 不做 | 归属 / 理由 |
|---|---|
| **Autonomy / Scheduler / Desire / Decision / Life Loop / Proactive Message Policy** | Character / Autonomy 领域；**本次只交付出口能力**（用户明确要求） |
| **主动消息触发方与推送循环** | 未决装配问题（architecture §2.5.6 候选 A/B）；需先决策再实现 |
| **为主动消息新增 schema**（外部推送态载体） | 未来任务；`proactive_actions.message_id` 列现为**本地 message 行 id**，语义不可复用 |
| 入站 Webhook / 验签 / 解密 / 去重 | FEISHU-002 |
| 身份映射与 `channel_identities` | FEISHU-003 |
| 管线接入 / LLM / 回复生成 | FEISHU-004 |
| 错误矩阵全量收口 / 边界静态断言 / 冒烟清单 | FEISHU-006 |
| Interactive Card（含"打字机"占位 + 反复 update） | 架构 §7.2；这也是 Streaming 的唯一现实实现方式 |
| 富文本（`post` / `interactive` msg_type）/ 图片 / 文件 / 语音 | 架构 §7.2 |
| 群聊发送 | 架构 §3.3（群聊入站已被 002 拒绝） |
| 撤回 / 编辑 / 已读回执 / 表情回复 | 与"文本最小闭环"无关 |
| Markdown → 纯文本渲染转换 | 表现层决策，后置（§6.6） |
| 跨进程幂等 / 分布式去重 | 不做（§6.4 已登记残余风险） |

## 15. Implementation Notes

### 15.1 本 Task 完成后，"第一阶段"真正达成

架构 §7.1 的两个目标——"飞书发消息 → 角色正常回复"与"飞书多轮对话 → Memory / World / Session 正常保持"——在 005 完成后**首次可端到端验证**，且出站**同时具备 Reply 与 Proactive 两种形态**（后者的触发方留给未来）。因此本 Task 收口时必须执行一次真实链路（真模型 + 真飞书应用）的**人工冒烟**（清单由 FEISHU-006 产出）。

### 15.2 二选一策略的冻结结果（**已在本 Detail 定案**）

| 待定项 | 冻结结果 | 位置 |
|---|---|---|
| "reply 不可用时降级 send" | **仅当 `reply_ref` 结构性缺失（Proactive）时用 send**；Reply 的运行时错误**不**触发形态切换 | §6.2 |
| "空回复：兜底文案 or 静默" | **发兜底文案**（由 004 决定，`outbound_text` 恒非空）；005 对空白输入**跳过发送**作为第二道 | §6.6 |
| "单条仍超限则截断" | 段数超 `max_parts` 时截断最后一段并标记 | §6.7 |
| "终败是否继续后续段" | **不继续**（停止后续段） | §6.10 |
| **（新增）两个 model 还是一个** | **统一 `OutboundMessage`**（`reply_ref` 区分形态） | §6.1 |
| **（新增）Proactive 幂等键从哪来** | **调用方提供**（未来可取既有 `proactive_actions.dedupe_key`） | §6.4 |

### 15.3 与 tasks.md 的文件偏差

tasks.md 原写"填充 `client.py` + `adapter.py` + `errors.py`"，本 Detail 新增文件：

```text
app/channels/feishu/outbound.py                   # 纯函数（规范化 / 切分）
app/channels/feishu/delivery.py                   # ★ 出站编排（两形态 + 幂等 + 收口）+ ChannelAdapter 实现
tests/unit/test_feishu_adapter_protocol.py        # 契约一致性
tests/integration/test_feishu_proactive_flow.py   # ★ Proactive 能力验证
```

理由：`client.py` 在 001 已承担"token + transport + 重试"三责；再塞入"文本切分 + 形态判定 + 逐段编排 + 幂等"会使其成为万能模块，且让"一次请求"与"一次投递"两个粒度的测试纠缠。分层仍全在 `channels/feishu/` 内，不越界。

### 15.4 不新增配置键

只消费 001 冻结的键（`feishu_max_reply_chars` / `feishu_timeout_seconds` / `feishu_http_*` / `feishu_api_base`）与 002 已在用的 `feishu_dedupe_ttl_seconds`（复用为幂等 TTL）。`max_parts` 等实现细节用模块常量，**不新增环境变量**；若确需，须先回填 architecture.md §5.1（与 001/002 同一流程）。

### 15.5 段间不 sleep 的理由

顺序 `await` 已足够保证顺序；人为 sleep 会拖长等待、增加跨段失败面并拖慢测试。**限流保护应在入站侧（002）与重试退避（001）解决。**

### 15.6 三步易错点

1. **`content` 是字符串而非对象**：`json.dumps({"text": text}, ensure_ascii=False)` 的结果作为 `content` 的**值**；`ensure_ascii=False` 必须显式传。**禁止**手工拼 JSON。
2. **`receive_id_type` 的位置**：官方文档可能是 query 参数而非 body 字段 —— 必须按 §6.5 复核后确定。
3. **形态判定只看 `reply_ref`**：不要引入"尝试 reply、失败再 send"的重试式降级（会让投递目标不可预测）。

### 15.7 未来接入点（**本 Task 不实现**）

飞书出站能力交付后，"何时开口"仍缺一个触发方。候选路径见 architecture §2.5.6（推荐 A：复用既有 `proactive_actions` 拉取模型）。**本 Task 不实现、不设计其 schema 变更**；未来立项时需先解决"外部推送态载体"这一缺口。

### 15.8 Implementation Order

```text
1. outbound.py（normalize + split）→ 单测（不变式优先，红→绿）
2. errors.py：Feishu 错误 → ChannelErrorKind 映射 + RETRYABLE_BUSINESS_CODES → 单测
3. client.py：reply_message / send_message（复用 transport + token + RetryPolicy）→ 单测（假传输）
4. delivery.py：FeishuChannelAdapter（实现契约）+ 形态判定 + 幂等 + 逐段 + 收口 → 单测
5. adapter.py：Reply 形态接线（004 → 005）
6. 契约一致性单测（adapter satisfies ChannelAdapter）
7. 集成测试：Reply 全链 + 解耦 + 顺序
8. 集成测试：Proactive 全链（身份解析 → send）
9. 人工冒烟（真模型 + 真飞书应用，清单由 006 产出）
10. Focused → Module → Integration → Fast
```
