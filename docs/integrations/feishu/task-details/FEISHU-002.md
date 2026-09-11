# FEISHU-002 — Webhook 与事件接收

> 上游：[../tasks.md](../tasks.md) FEISHU-002 ｜ 架构：[../architecture.md](../architecture.md) §4 / §6.2 #1~#5 / #13 ｜ 依赖：**FEISHU-001**
> Priority：**P0** ｜ 层级：Inbound（入站链路第一段，FEISHU-003 / 004 的输入提供方）
> **本 Task 的产出形态**：`POST /api/v1/feishu/events` 可在 3s 内 ack，并把一个**已通过校验、已去重、通道无关的 `InboundMessage`** 交给后台处理入口。**不含**身份映射、管线调用、消息发送。

---

## 1. Goal

建立飞书入站链路，把"外部 HTTP 事件"变成"内部消息对象"：

```text
Feishu Event ──► POST /api/v1/feishu/events
                      │
                      ├─[1] 读原始 body（签名/解密必须基于原始字节）
                      ├─[2] 解密（若配置 Encrypt Key）
                      ├─[3] 校验（Verification Token / 签名 / 时间戳窗口）
                      ├─[4] challenge 回显（配置期）
                      ├─[5] 事件解析 + 过滤（只留 p2p 文本）
                      ├─[6] event_id 去重
                      ├─[7] 快速 ACK 200  ← 目标 < 3s
                      └─[8] 后台派发（fire-and-forget）
                                  ▼
                        adapter.handle_inbound_message(inbound)
                                  ▼
                        （处理体由 FEISHU-003 / 004 填充）
```

本 Task 交付 4 件事：

1. **可被飞书回调的端点**，且未启用时对系统隐身（404）。
2. **三重校验**（token / 签名 / 时间戳）＋ **加密事件解密（正式支持；Encrypt Key 配置时为必走路径）**，全部在触碰业务代码之前完成。
3. **`event_id` 去重**（进程内、有 TTL），保证飞书重推与并发重复只处理一次。
4. **ack 与处理解耦**：HTTP 响应不等 LLM，处理入口签名冻结，供 003/004 填实现。

## 2. Dependencies

| 依赖 | 提供物 | 使用方式 |
|---|---|---|
| **FEISHU-001** | `FeishuSettings`（`feishu_enabled` / `verification_token` / `encrypt_key` / `dedupe_ttl_seconds` / `signature_window_seconds` / `api_base`） | 只读 `get_settings()` |
| **FEISHU-001** | **`cryptography` runtime 依赖**（已由 001 通过 `uv add` 引入；Risk #1 = 方案 A） | `events.py` 内 `from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes`。**本 Task 不自行添加依赖** |
| FEISHU-001 | `errors.FeishuError` 及子类（`FeishuDisabledError` / `FeishuConfigError` / `FeishuAuthError` / `FeishuClientError`） | 校验类失败复用既有分类，**不新增错误体系** |
| FEISHU-001 | `channels/base.py::InboundMessage` | 本 Task 的**唯一产出类型**（通道无关） |
| 既有 | `application/observability.py::spawn_background(coro)` | 后台派发（见 §6.8：同时自动接入 conftest 的 teardown 等待） |
| 既有 | `api/rate_limit.py` 的进程内滑动窗口范式 | 按 `open_id` 限流（见 §6.9） |

> **反向输出（本 Task 必须供给下游）**：`InboundMessage` 的 `external_user_id` 必须**已经是 `open_id`**、`reply_ref` 必须**已经是 `message_id`**、`external_thread_id` 必须是 `chat_id`。FEISHU-003 只做 `open_id → internal_user_id` 映射，**不得**再回头解析原始事件（见 §7.4 字段映射表）。

## 3. Scope

**做**：

- `POST /api/v1/feishu/events` 路由：原始 body 读取、JSON 解析、解密、三重校验、challenge 回显、解析过滤、去重、快速 ack、后台派发；未启用 404。
- 校验与解析**全部实现为纯函数**（`events.py`），可脱离 HTTP 单测。
- 进程内 `event_id` 去重（TTL 来自 `feishu_dedupe_ttl_seconds`）＋ 进程内按 `open_id` 限流。
- `adapter.py` 的**入站编排骨架**：`handle_inbound_message(inbound)` 的签名与"处理体占位 + 异常兜底 + trace 起点"。

**不做**（见 §14）：身份映射、`channel_identities`、管线调用、LLM、回复生成与发送、群聊、非文本、卡片、**主动消息（出口能力属 005、触发方不做）**、Streaming。

## 4. Files

### New Files

```text
app/api/v1/feishu.py            # 传输层：路由 + 原始 body + 校验编排 + 快速 ack + 后台派发
app/channels/feishu/events.py   # 纯函数：解密 / 验签 / challenge / 事件解析 / 过滤 / 去重存储
app/channels/feishu/adapter.py  # 入站编排入口（handle_inbound_message）+ 后台任务集合 + reset 接缝
tests/unit/test_feishu_events.py       # events.py 纯函数矩阵
tests/e2e/test_feishu_webhook.py       # 端点行为（ASGITransport + 假传输，零网络）
```

### Modified Files

```text
app/api/v1/router.py       # +1 行：api_router.include_router(feishu.feishu_router)
tests/conftest.py          # 仅当需要"等待飞书后台任务"的辅助函数（见 §6.8 与 §15.3；如复用 observability 集合则无需修改）
```

> **不得修改**：`app/main.py`（不注册 lifespan / 不改 middleware 顺序）、`app/api/rate_limit.py`（既有中间件只管 `/api/v1/chat/message`，本 Task 加**独立**限流）、`core/settings/feishu.py`（配置在 001 已冻结，本 Task 只读）。

### Forbidden Files

```text
application/**            # 既有编排零修改
services/**               # 域服务零修改（channel_identity_service 属 FEISHU-003）
repositories/**           #
models/**                 #
character/**  chains/**  prompts/**
api/v1/chat.py  api/v1/schemas.py
core/db.py                # 无表（去重是进程内，见 §10）
migrations/**             # 无迁移
pyproject.toml  uv.lock   # 见 §15.1 依赖决策
```

## 5. Architecture / Data Flow

### 5.1 端到端（一次成功事件）

```text
飞书
 │  POST /api/v1/feishu/events   Content-Type: application/json
 ▼
[api/v1/feishu.py] feishu_events(request)
 │
 ├─ 0. settings.feishu_enabled == False ─────────────► 404（端点隐身）
 │
 ├─ 1. raw = await request.body()          ← 必须先取原始字节
 │      └─ 解析 JSON：json.loads(raw)（失败 → 400）
 │      └─ 提取 header 三元组：
 │           X-Lark-Request-Timestamp / X-Lark-Request-Nonce / X-Lark-Signature
 │
 ├─ 2. 若 body 含 "encrypt"：
 │      plain = events.decrypt(encrypt_key, body["encrypt"])   ← 纯函数
 │      └─ 解密失败 → 400（FeishuConfigError，不解析、不派发）
 │
 ├─ 3. events.verify_token(header_token, verification_token)   ← 纯函数
 │      └─ 不匹配 → 401
 ├─ 4. events.verify_signature(raw, ts, nonce, encrypt_key, headers)  ← 纯函数
 │      └─ 签名不匹配 → 403；时间戳超窗 → 403
 │
 ├─ 5. 若 type == "url_verification" ──► 返回 {"challenge": <原样>}   ← 配置期一次性
 │
 ├─ 6. parsed = events.parse_message_event(payload)             ← 纯函数
 │      └─ 非 im.message.receive_v1 / 非 p2p / 非 text → 200 + 忽略（记日志）
 │
 ├─ 7. events.accept_event(event_id)                            ← 去重（进程内 TTL）
 │      └─ 已见过 → 200 + 忽略（不派发）
 │
 ├─ 8. inbound = events.to_inbound_message(parsed)              ← 纯函数 → InboundMessage
 │
 ├─ 9. observability.spawn_background(adapter.handle_inbound_message(inbound))  ← 不 await
 │
 └─ 10. return 200  ◄── 至此与飞书的交互结束（LLM 尚未开始）
```

### 5.2 关键不变式

| 不变式 | 含义 |
|---|---|
| **verification before business** | 步骤 2~4 任一失败 → 直接返回，**不解析业务字段、不去重、不派发** |
| **ack 先于处理** | `spawn_background` 不被 `await`；响应时刻与 LLM 无关 |
| **raw body 唯一来源** | 校验与解密都基于 `request.body()` 的原始字节，**不得**用 `await request.json()` 的结果反推（键序/空白会破坏签名） |
| **校验失败不放大** | 校验类失败返回 4xx（拒绝重试）；解析/过滤类失败返回 **200**（避免飞书无限重推） |
| **下游只吃 `InboundMessage`** | 003/004 不得接触飞书事件结构（§7.4 表是唯一翻译点） |

## 6. Detailed Implementation

### 6.1 路由与原始 body

```text
@feishu_router.post("/feishu/events")
async def feishu_events(request: Request) -> Response
```

- **不用 Pydantic body 模型**：需要原始字节（签名/解密），`await request.body()` 是唯一入口。Pydantic 模型会隐藏原始形态。
- `request.body()` 在 Starlette 内可重复读取（有缓存），不必担心二次读取。
- Content-Type 只做**宽容判断**（缺失或含 `json` 均可），不因 Content-Type 缺失而 400——飞书侧以 `application/json` 发送，但严格校验无收益且易误伤。
- **不挂 `Depends`**：本路由不需要 LLM（FEISHU-004 才需要），不给未来埋隐式依赖。

### 6.2 解密（**正式支持的路径**，Risk #1 = 方案 A）

```text
events.decrypt(encrypt_key: str, ciphertext_b64: str) -> dict
```

**完整入站流程**：

```text
HTTP Request
    ↓
Raw Body
    ↓
Feishu Request Verification（token + 时间戳窗口 + 签名）
    ↓
Encrypted?
    ├─ No  → Parse Event
    └─ Yes → AES-256-CBC decrypt → Parse Event
```

- **触发条件**：payload 顶层存在 `"encrypt"` 键。此时 payload 的其他字段**都不可信**（只有 `encrypt` 一个键）。
- **实现依赖**：`cryptography`（`hazmat.primitives.ciphers`）；**禁止**纯 Python 实现 AES，**禁止** monkeypatch 一个"假解密"来绕过真实 crypto path。
- **算法（示意，实现期必须以官方文档复核，见 §15.2）**：`AES-256-CBC`；`key = sha256(encrypt_key.encode()).digest()`；密文 base64 解码后**前 16 字节为 IV**，其余为密文；**PKCS#7** 去填充。
  > ⚠️ 上面是**示意性算法**。**具体算法、字段与参数一律以飞书官方开放平台文档为最终依据**——不得仅依赖本文档。
- **解密失败**（密钥不匹配 / base64 非法 / 长度不足 16 / 填充错误）→ 统一归为 `FeishuConfigError` + `400`，**不重试、不派发、不进入任何业务处理**（不建 identity / 不建 conversation / 不调管线 / 不产生回复）。
- **`encrypt_key` 为空 + 收到 `encrypt` payload** → 同一路径失败（`400`）：**配置与来件不一致，必须显式暴露**，不得静默忽略、不得"当作未加密处理"。
- **解密成功后仍需按事件结构解析**：若明文结构非法（不是合法事件结构）→ 按 §9.2 处理为 **`200` + 忽略**（并记脱敏日志）——这与"解密失败 400"是**两种不同的失败**，不要混为一谈。

### 6.3 三重校验

```text
events.verify_token(header_token: str | None, expected: str) -> None      # 失败 raise FeishuAuthError
events.verify_signature(raw: bytes, timestamp: str | None, nonce: str | None,
                        encrypt_key: str, signature: str | None) -> None  # 失败 raise FeishuAuthError
```

| 校验 | 规则 | 失败响应 |
|---|---|---|
| **Verification Token** | `payload.header.token == feishu_verification_token`（兼容旧版顶层 `payload.token`） | `401` |
| **时间戳窗口** | `abs(now - int(timestamp)) <= feishu_signature_window_seconds`（秒） | `403` |
| **签名** | `sha256(timestamp + nonce + encrypt_key + raw_body_text)`，与 `X-Lark-Signature` **常量时间比较**（`hmac.compare_digest`） | `403` |

**职责分工（**不可混淆**，架构 §6.4）**：`verification token` 证明"请求来自我们配置的应用"，**签名**证明"请求体未被篡改"。两者是**并列的两道关，不是替代关系**——**禁止把 token 当作签名校验的替代品**。

- **签名的启用条件**：`encrypt_key` 非空**且** 签名 header 齐备。
- **`encrypt_key` 为空时**：飞书侧不下发签名头，此时可执行的校验只有 `verification token` + 时间戳窗口。这属于**安全能力降级**（不是"等价替代"）：**不得因缺签名而拒绝**（否则未加密配置直接不可用），但必须记 `warning`，且**"官方在未配置 Encrypt Key 时提供哪些校验要素"必须在实现期以官方文档确认**——不得自行设计一套"看起来合理"的验证协议。
- **时间戳必须先于签名比较**：时间戳非法（非整数/缺失）同样按 `403` 处理，且**不触发**任何比较逻辑。
- 比较一律用 `hmac.compare_digest`（防时序侧信道）；`hashlib` + `hmac` 均属**标准库**（**不需要** `cryptography` —— 该依赖只用于 AES 解密）。

### 6.4 Challenge 回显

```text
payload 的 type == "url_verification"
   └─► 200 {"challenge": payload["challenge"]}
```

- **原样回显**（不做任何加工/截断）。
- 仍需**先通过校验**（token/签名/时间戳）：避免把端点变成任意探测点。
- 缺失 `challenge` 字段 → `400`（结构非法），不返回空字符串。

### 6.5 事件解析与过滤

```text
events.parse_message_event(payload) -> ParsedMessageEvent | None
```

解析产物（内部数据类，**不对外暴露**）：

| 字段 | 来源 | 必需 | 说明 |
|---|---|---|---|
| `event_id` | `header.event_id` | ✅ | 去重键（缺失 → 视为结构非法，200 忽略 + 记日志） |
| `event_type` | `header.event_type` | ✅ | 必须 `im.message.receive_v1` |
| `create_time` | `header.create_time` | ⭕ | 毫秒字符串（仅日志） |
| `tenant_key` | `header.tenant_key` | ⭕ | → `InboundMessage.metadata` |
| `app_id` | `header.app_id` | ⭕ | 仅日志（用于排障，不泄漏） |
| `message_id` | `event.message.message_id` | ✅ | → `reply_ref` |
| `chat_id` | `event.message.chat_id` | ✅ | → `external_thread_id` |
| `chat_type` | `event.message.chat_type` | ✅ | **必须 `p2p`** |
| `message_type` | `event.message.message_type` | ✅ | **必须 `text`** |
| `content` | `event.message.content` | ✅ | **JSON 字符串**：`"{\"text\":\"...\"}"` → 二次解析取 `text` |
| `open_id` | `event.sender.sender_id.open_id` | ✅ | → `external_user_id` |
| `union_id` | `event.sender.sender_id.union_id` | ⭕ | → `metadata`（供 003 备用） |
| `user_id` | `event.sender.sender_id.user_id` | ⭕ | → `metadata`（租户内 ID，备用） |

**过滤规则（任一不满足 → 返回 `None`，路由侧回 200 并记日志）**：

```text
event_type != "im.message.receive_v1"        → 忽略（订阅了其他事件类型）
chat_type  != "p2p"                          → 忽略（群聊：架构 §3.3 隔离硬要求）
message_type != "text"                       → 忽略（图片/文件/语音/卡片，第一阶段不支持）
content 非合法 JSON 或缺 text                → 忽略（结构非法）
open_id 缺失                                 → 忽略（无法映射身份，宁可丢弃不猜）
```

**`content` 处理细节**：飞书 `message.content` 是**字符串化的 JSON**（形如 `{"text":"你好"}`），需**二次 `json.loads`**；取出的 `text` 需 `strip()`；**空文本同样忽略**（不产生空轮次、不给管线送空 content）。

### 6.6 去重

```text
events.accept_event(event_id: str) -> bool      # True=首次（继续处理）；False=重复（忽略）
```

- **进程内**存储：`dict[str, float]`（key=event_id，value=单调时间戳）＋ `threading.Lock`（对齐 `api/rate_limit.py` 的既有实现风格）。
- **TTL**：`feishu_dedupe_ttl_seconds`（默认 600）；读取时惰性驱逐（`now - ts > ttl` 即视为过期），**不引入后台清理线程**。
- **容量兜底**：设进程内条目上限（复用 `feishu_dedupe_ttl_seconds` 之外不新增配置 —— 上限由"惰性驱逐 + 事件速率自然收敛"保证；若需要硬上限，取 `10 * feishu_session_queue_limit` 这类既有一致性常数，**实现期不得引入新配置键**；见 §15.4）。
- **并发重复**：断言"同一 `event_id` 并发进入 → 恰好一个返回 `True`"（锁内 check-and-set 原子完成）。
- **进程外边界**：多 worker 部署下每个进程各有一份去重表 → 同一事件可能被两个 worker 各处理一次。**这是有意的范围限制**（见 §10），与架构 §5.2 "不做跨进程" 一致。

### 6.7 快速 ACK

| 项 | 要求 |
|---|---|
| 目标 | **< 3s**（飞书事件回调超时会重推） |
| 实测口径 | 在**处理入口被人为阻塞**的前提下，HTTP 响应仍 < 3s（§12 时序断言） |
| 保证方式 | 处理体不 `await`；路由内不做任何 LLM / 网络 / DB 调用 |
| 校验失败的响应 | `401` / `403` / `400`（**立即**返回，不派发） |
| 解析/过滤/去重的响应 | `200`（不派发） |

### 6.8 后台派发

```text
observability.spawn_background(adapter.handle_inbound_message(inbound))
```

**为什么用它，而不是自己 `asyncio.create_task`**：

1. 它就是项目为"fire-and-forget"建立的既有机制（`application/observability.py`），已处理"主循环 vs 工作线程"的差异（`set_main_loop` 注册 + `run_coroutine_threadsafe` 回投）。
2. 它会把任务登记进 `observability.background_tasks` 集合并自动 discard。
3. **关键收益**：`tests/conftest.py` 的 autouse `_offline_repos` teardown 已经在等待 `observability_tasks()` —— **复用它即可让测试自动等待飞书后台任务结束，无需修改 conftest**（避免后台任务跨测试泄漏造成的偶发失败）。

**请求生命周期结束后是否安全**：安全。任务归属**事件循环**而非请求对象；`inbound` 是纯值对象（无 ORM 实体、无 session 绑定、无 request 引用），不持有任何随请求销毁的资源。

### 6.9 限流（独立于既有中间件）

- 既有 `chat_rate_limit_middleware` **只作用于 `POST /api/v1/chat/message`**（按客户端 IP），Webhook 路径**不在其覆盖范围**（架构 §6.2 #13）。
- 本 Task 增加**按 `open_id`** 的独立滑动窗口，复用 `api/rate_limit.py` 的同一实现形态（`dict[str, deque[float]]` + `threading.Lock`），阈值沿用既有 `settings.chat_rate_limit_per_minute`（**不新增配置键**，避免与 001 冻结的配置集冲突）。
- 超限 → `429` + 不派发。

### 6.10 `adapter.handle_inbound_message`（本 Task 冻结的接缝）

```text
adapter.handle_inbound_message(inbound: InboundMessage) -> None
```

本 Task 的实现体：

```text
1. trace = trace_collector.begin_trace()            # 起点在此，链路可观测
2. 记 info 日志：channel / external_user_id / reply_ref / text_len
3. 处理体占位：
   - FEISHU-003 填："身份映射 → (user_id, session_id)"
   - FEISHU-004 填："调 stream_chat → 累积回复"
   - FEISHU-005 填："出站发送"
   本 Task 落地为：解析后即返回（并 mark_status("feishu_dispatch", "not_implemented")）
4. 全异常兜底：logger.exception + trace.mark_status(..., "error")，**绝不向外抛**
   （后台任务的异常无人接收，必须在此收口）
```

> **设计意图**：本 Task 只交付"入口 + 兜底 + trace 起点"。003/004/005 各自**在同一函数体内顺序接线**，不新增调度层、不新增第二套编排。这样"一条消息只有一条链路"在代码结构上就是显然的。

## 7. Interfaces

### 7.1 HTTP 契约

| 情形 | 状态码 | Body |
|---|---|---|
| 未启用（`FEISHU_ENABLED=false`） | `404` | FastAPI 默认 |
| `url_verification` 且校验通过 | `200` | `{"challenge": "..."}` |
| 有效文本单聊事件（首次） | `200` | 空（`{}`） |
| 重复 `event_id` | `200` | 空 |
| 非文本 / 群聊 / 非目标事件类型 / 空文本 | `200` | 空 |
| 解析失败（结构非法） | `200` | 空（记日志；避免重推） |
| body 非 JSON / 缺 `header` | `400` | `{"detail": ...}` |
| 解密失败 | `400` | `{"detail": ...}` |
| `header.token` 不匹配 | `401` | `{"detail": ...}` |
| 签名不匹配 / 时间戳超窗或非法 | `403` | `{"detail": ...}` |
| 超出按 `open_id` 限流 | `429` | `{"detail": ...}` |

**约定**：`detail` 文案**不含** token / secret / 密文 / 原始 body 片段。

### 7.2 `events.py` 纯函数契约

| 函数 | 输入 | 输出 | 异常 |
|---|---|---|---|
| `decrypt(encrypt_key, ciphertext_b64)` | 密钥 + 密文 | `dict`（明文 payload） | `FeishuConfigError` |
| `verify_token(header_token, expected)` | 收到值 + 期望值 | `None` | `FeishuAuthError` |
| `verify_signature(raw, timestamp, nonce, encrypt_key, signature)` | 原始字节 + header + 密钥 | `None` | `FeishuAuthError` |
| `is_challenge(payload)` | payload | `bool` | — |
| `parse_message_event(payload)` | payload | `ParsedMessageEvent \| None` | —（失败返回 None） |
| `to_inbound_message(parsed)` | 解析产物 | `InboundMessage` | `ValueError`（`base.py` 守卫） |
| `accept_event(event_id)` | 事件 ID | `bool` | — |
| `allow_rate(open_id)` | 用户 ID | `bool` | — |
| `reset_event_state()` | — | `None` | —（测试接缝：清去重表与限流窗口） |

**全部为纯函数/无 HTTP**，因此 `tests/unit/` 可直接覆盖，不需要起 app。

### 7.3 `adapter.py` 契约

| 符号 | 说明 |
|---|---|
| `handle_inbound_message(inbound) -> None` | 后台处理入口（本 Task 为骨架 + 兜底 + trace） |
| `reset_feishu_adapter()` | 测试接缝（清 trace 相关缓存；与 001 的 `reset_feishu_client()` 并列） |

### 7.4 事件字段 → `InboundMessage` 映射（下游契约，**唯一翻译点**）

| 飞书事件 | → `InboundMessage` | 备注 |
|---|---|---|
| `header.event_id` | （不入基元） | 仅用于去重与日志；见 §15.5 的取舍说明 |
| `event.message.message_id` | `reply_ref` | FEISHU-005 出站直接使用 |
| `event.sender.sender_id.open_id` | `external_user_id` | FEISHU-003 的映射输入 |
| `event.message.chat_id` | `external_thread_id` | 本阶段不参与映射（只用 open_id） |
| `event.message.content.text` | `text` | 已 `strip()`；空则丢弃 |
| `header.create_time` 等 | `received_at` | 无 create_time 时取 `datetime.now(tz)` |
| `tenant_key` / `union_id` / `user_id` / `chat_type` / `message_type` | `metadata` | 有界、可序列化；供后续 Task 备用 |

**FEISHU-003 需要的字段全部在此表内**（`event_id` 已在 002 消费；`message_id` / `open_id` / `chat_id` / `chat_type` / `content` 均已落入基元），003 **不需要**再解析原始事件。

## 8. Data Model

**无数据库、无迁移、无新表**。本 Task 只有两类内存结构：

### 8.1 去重表

```text
_seen_events: dict[str, float]      # event_id → 单调时间戳
_lock: threading.Lock               # check-and-set 原子化
```

### 8.2 限流窗口

```text
_rate_windows: dict[str, deque[float]]   # open_id → 最近 60s 内的请求时间
_lock: threading.Lock
```

### 8.3 解析产物（内部，进程内）

```text
ParsedMessageEvent(frozen dataclass)
  event_id, event_type, tenant_key, app_id,
  message_id, chat_id, chat_type, message_type, text,
  open_id, union_id, user_id, create_time_ms
```

**不持久化理由**：两者都是"短时效、可丢失、重建成本为零"的状态。持久化会引入表、迁移、清理循环与跨进程一致性要求，而收益仅为"多 worker 下去重更严"——第一阶段单实例，**收益为负**。（对齐 TESTING.md §2「无 Redis / Celery / MQ，队列用 DB 表实现」的项目克制传统：连 DB 表都不需要。）

## 9. Error Handling

### 9.1 与架构 §6.2 的对应

| §6.2 # | 场景 | 本 Task 处理 | 返回 |
|---|---|---|---|
| 1 | Webhook 验证失败（token / 签名 / 时间戳） | `FeishuAuthError`，记 warning，**不解析、不去重、不派发** | `401` / `403` |
| 2 | **解密失败**（密钥不匹配 / base64 非法 / 长度不足 / 填充错误 / Encrypt Key 为空却收到密文） | `FeishuConfigError`，记 error（**脱敏**），不进解析 | `400` |
| 2b | 解密成功但**明文结构非法** | 记**脱敏**日志（明文内容不入日志）后忽略 | `200` |
| 3 | Event 解析失败 | 返回 `None` → 记 info/warning，跳过 | `200` |
| 4 | 事件不适用（群聊/非 text/非目标类型） | 返回 `None` → 记 info（**含忽略原因**） | `200` |
| 5 | 重复事件 | `accept_event` 返回 `False` → 直接忽略 | `200` |
| 13 | 限流 | 按 `open_id` 窗口超限 → 记 warning | `429` |

（#6~#12 属 003/004/005，见各自 Detail。）

**红线（#1 与 #2 共同）**：验证失败与解密失败都必须**在任何业务代码之前**短路返回——**不得**创建 identity、**不得**创建 conversation、**不得**进入 Chat Pipeline、**不得**产生任何 AI 回复、**不得**去重写入。这是"安全默认拒绝"的可执行形式（架构 §6.1 原则 2）。

### 9.2 输入健壮性总表

| 输入 | 处理 |
|---|---|
| 空 body / 非 JSON | `400`（不抛 5xx） |
| 缺 `header` / `header` 非对象 | `400` |
| 缺 `header.event_id` | `200` + 忽略（宁可丢弃不猜） |
| `content` 非 JSON 字符串 / 缺 `text` | `200` + 忽略 |
| `content.text` 为空白 | `200` + 忽略 |
| `timestamp` 非整数 / 缺失（且启用签名时） | `403` |
| **密文 base64 非法 / 解码后 < 16 字节 / 填充错误** | `400`（解密失败） |
| **`encrypt_key` 为空却收到 `encrypt` payload** | `400`（配置与来件不一致） |
| **解密成功但明文不是合法事件结构** | `200` + 忽略（记脱敏日志） |
| payload 里出现未知字段 | **忽略**（飞书会演进字段，不做白名单拒绝） |

**硬性要求**：本路由对**任何**输入都不得返回 `5xx`（除进程级致命错误）。上表穷举的失败全部落 4xx（拒绝）或 200（忽略）。

**日志脱敏**：涉及密文 / 明文 payload 的日志**只记长度与结构要点**（如 `raw_len`、`cipher_len`、失败原因类别），**不得**输出密文、明文内容、`Encrypt Key`、`App Secret`、`Verification Token`、`access token`。

## 10. Concurrency / Idempotency

| 项 | 决定 |
|---|---|
| 幂等键 | `event_id`（飞书重推保留同一 `event_id`，故它是正确的幂等键） |
| 幂等介质 | **进程内** `dict` + `threading.Lock`（非 DB、非 Redis） |
| 并发重复 | 锁内 check-and-set：**恰好一个** `True`，其余 `False`（§12 有据） |
| TTL | `feishu_dedupe_ttl_seconds`（600s），惰性驱逐 |
| ACK 与处理并发 | ack 立即返回；后台任务在**同一事件循环**中并发执行，受 FEISHU-004 的 per-user 串行约束（本 Task 不引入全局串行，避免无谓排队） |
| 多 worker 边界 | 每进程独立去重表 → 跨进程重复**存在**，**接受**（第一阶段单实例；飞书重推间隔远大于处理耗时） |
| 线程安全 | `events.py` 内的锁为 `threading.Lock`（对齐 `api/rate_limit.py`）；测试各自 `reset_event_state()` 隔离 |

> **为什么不用 DB 表做去重**：为"一次 600s 内的重推"引入一张表 + 迁移 + 清理循环，成本远高于收益，且会把"入站路径"变成"DB 阻塞路径"（直接威胁 < 3s ACK）。**为什么不用 Redis**：项目刻意未引入（TESTING.md §2），且第一阶段单实例无此需求。

## 11. Security

| 项 | 要求 |
|---|---|
| **校验先于业务** | §5.2 不变式：未通过 token/签名/时间戳时，**不触碰任何业务函数**（§12 有"入口未被调用"断言） |
| **拒绝无歧义** | 校验失败一律 401/403，不做"宽松放行 + 仅记日志" |
| **签名比较** | `hmac.compare_digest`（常量时间），禁止 `==` |
| **时间戳窗口** | 防重放：超窗即拒（`feishu_signature_window_seconds`） |
| **密钥零泄漏** | `verification_token` / `encrypt_key` / 密文 / 明文 payload **不得**进日志、异常 `detail`、trace |
| **open_id 可记** | `open_id` 是应用内标识、非凭据，允许入日志（排障必需）；`app_id` 同理 |
| **原始 body 不落日志** | 需要留证时只记 `len(raw)` 与 `event_id`（对齐 `observability` 的有界/脱敏传统） |
| **脱敏出口** | 复用 001 的 `FeishuSettings.secret_values()` + `_scrub(...)`；`api/v1/feishu.py` 产出的每个 `detail` 都经同一出口 |
| **未启用即隐身** | `FEISHU_ENABLED=false` → `404`（端点不暴露，也不产生任何校验副作用） |

## 12. Testing

零真实网络、零真实 LLM；端点测试用 `httpx.ASGITransport` + 内存 SQLite（本 Task 无 DB，但 autouse fixture 会注入）+ `override_settings(feishu_enabled=True, ...)`。

### 12.1 `tests/unit/test_feishu_events.py`

```text
challenge
[ ] is_challenge 判定 + 回显原样（含特殊字符不转义丢失）
[ ] 缺 challenge 字段 → 结构非法（路由 400）

valid event
[ ] 合法 p2p 文本事件 → parsed 全字段正确（open_id/message_id/chat_id/text）
[ ] content 二次解析：{"text":"你好"} → "你好"
[ ] 文本首尾空白被 strip；纯空白 → None

invalid token
[ ] header.token 不匹配 → FeishuAuthError

invalid signature
[ ] 签名不匹配 → FeishuAuthError
[ ] 签名匹配 → 通过
[ ] encrypt_key 为空 + 无签名头 → 通过（未加密配置不得被拒）

invalid timestamp
[ ] 时间戳超窗（前/后）→ FeishuAuthError
[ ] 时间戳非整数 / 缺失 → FeishuAuthError
[ ] 边界：恰好等于 window → 通过（含等号语义需与实现一致并断言）

真实 crypto path（Risk #1 = 方案 A；**11 项强制用例**）
[ ] 1. 正确 Encrypt Key + 正确密文 → 成功解密（真实 AES-256-CBC，**不得 monkeypatch 假解密**）
[ ] 2. 错误 Encrypt Key → decrypt failure（FeishuConfigError）
[ ] 3. 损坏 ciphertext（截断 / 改字节 / 非法 base64 / 填充错误）→ decrypt failure
[ ] 4. encrypted event → 解密后**正确解析出真实事件结构**（open_id / message_id / chat_id / text 全字段）
[ ] 5. unencrypted event（无 encrypt 键）→ 同样正确解析（两种来件都必须支持）
[ ] 6. invalid signature → rejected（403）
[ ] 7. invalid verification token → rejected（401）
[ ] 8. expired timestamp → rejected（403；含恰好等于窗口边界的通过断言）
[ ] 9. malformed encrypted payload（能解开但明文结构非法）→ 200 + 忽略，**不派发**
[ ] 10. secret 不出现在日志（caplog 全文本不含 Encrypt Key / App Secret / Verification Token /
       access token / 密文 / 明文 payload）
[ ] 11. 全程**零真实 Feishu 网络请求**（不依赖真实飞书服务；transport 未被构造或调用计数为 0）

密文测试向量
[ ] 固定向量（含 IV），**不得每次运行随机生成**——否则失败不可复现
[ ] 测试侧用同一套 `cryptography` 原语生成密文（与实现对称，避免"自证"偏差）：
    优先采用飞书官方文档给出的示例密文/密钥作为额外交叉验证

签名校验（与 token 独立，**不可混同**）
[ ] 签名基于**原始 body**（加密场景下也是原始密文 body，不是解密后明文）
[ ] 加密 + 签名齐备 → 两者都执行；只验一个不构成通过
[ ] encrypt_key 为空 + 无签名头 → 不因缺签名而拒绝，但产生安全性降级 warning

malformed JSON
[ ] 缺 header / header 非对象 / event_id 缺失 → None 或 400（按 §9.2 表）
[ ] 未知字段不影响解析

duplicate event
[ ] accept_event 首次 True、再次 False
[ ] TTL 过期后同 ID 再次 True（用注入时钟推进，不 sleep）
[ ] 并发：多线程同时 accept 同一 event_id → 恰好 1 个 True

group message
[ ] chat_type = "group" → None
[ ] chat_type = "p2p" → 通过

non-text message
[ ] message_type = image/file/audio/post → None

others
[ ] event_type != im.message.receive_v1 → None
[ ] open_id 缺失 → None
[ ] reset_event_state() 后去重表与限流窗口均为空
```

### 12.2 `tests/e2e/test_feishu_webhook.py`

```text
disabled mode
[ ] FEISHU_ENABLED=false → POST 返回 404，且未触发任何校验/派发

challenge
[ ] 合法 url_verification → 200 + challenge 原样

valid event
[ ] 合法事件 → 200，且 handle_inbound_message 被调用一次（monkeypatch 计数）
[ ] 200 的 body 为空（不泄漏任何中间态）

auth failures
[ ] token 不匹配 → 401；签名不匹配 → 403；时间戳超窗 → 403
[ ] 三者均断言 handle_inbound_message 未被调用（"verification before business"）

encrypted / unencrypted 全链
[ ] 加密 payload + 正确密钥 → 200 且 handle_inbound_message **被调用一次**（真实解密后的完整全链）
[ ] 未加密 payload → 200 且被调用一次（两种来件路径都端到端可用）
[ ] 加密 payload + 密钥错 → 400；未派发；**未建 identity / 未建 conversation / 未调管线**
[ ] 加密 payload + 签名错 → 403；未派发
[ ] 能解开但明文结构非法 → 200；未派发

malformed JSON
[ ] 非 JSON body → 400，不抛 5xx

duplicate event
[ ] 同一 event_id 连续两次 → 第二次 200 且派发计数仍为 1

group / non-text
[ ] 群聊事件 → 200 且未派发
[ ] 图片事件 → 200 且未派发

slow downstream
[ ] monkeypatch handle_inbound_message 为 sleep(5) 的协程
    → 断言 POST 在 < 1s 内返回 200（ACK 解耦的时序证明）
    → 断言后台任务最终执行（用 wait_until 等待，不用裸 sleep）

rate limit
[ ] 同 open_id 连续超过 chat_rate_limit_per_minute 次 → 429
```

### 12.3 测试基建

| 需要 | 做法 |
|---|---|
| 触发事件 | 复用 `tests/conftest.py` 既有 `ASGITransport` / `TestClient` 与 `override_settings`（`feishu_*` 键走 `key.upper()` 兜底，**无需改 env_map**） |
| 签名/加密构造 | 测试侧用标准库 `hashlib`/`hmac` 生成签名；密文用固定测试向量（见 §15.2） |
| 隔离 | 测试文件内 autouse fixture 调 `events.reset_event_state()`；001 的 `reset_feishu_client()` 同样在用例内重置 |
| 后台任务收尾 | 复用 `observability.spawn_background` → conftest teardown 既有等待覆盖（§6.8） |
| 时序断言 | 用 `time.perf_counter()` 度量 ack 延迟；用 `conftest.wait_until` 等待后台完成 |

**执行级别**：Focused（2 个新文件）→ Module（`pytest tests/unit tests/e2e -m "unit or api"`）→ Fast（`pytest -m "(unit or api) and not slow"`，因触及 `api/` 与 `router.py`）。

## 13. Acceptance Mapping

> 对齐 [../tasks.md](../tasks.md) FEISHU-002 的 8 条 AC。

```text
[ ] url_verification 原样返回 challenge                                          (AC-1)
[ ] token 不匹配 → 401；签名不匹配 → 403；时间戳超窗 → 403；
    且三者均不触发业务代码（派发计数 = 0 断言）                                    (AC-2)
[ ] ★ 加密事件为**正式能力**（Risk #1 = 方案 A）：真实 AES-256-CBC 解密成功；
    解密失败（密钥错 / 密文损坏 / Encrypt Key 为空却收到密文）→ 400，
    且**不进入任何业务处理**（不建 identity / 不建 conversation / 不调管线 / 不产生回复） (AC-3)
[ ] ★ 两种来件都支持：encrypted 与 unencrypted 事件均能端到端解析                  (AC-9)
[ ] ★ 验证机制不混同：token（401）与签名（403）各自独立断言，签名基于**原始 body**   (AC-10)
[ ] ★ 真实 crypto path 11 项强制用例全绿；测试**零真实飞书网络请求**               (AC-11)
[ ] FEISHU_ENABLED=false 时路由 404（端点不暴露）                                  (AC-4)
[ ] 重复 event_id 只处理一次，第二次 200 且不派发                                  (AC-5)
[ ] 群聊与非 text 被忽略：200 且不派发                                            (AC-6)
[ ] ack 先行：处理入口被阻塞时 HTTP 仍 < 3s 返回 200                              (AC-7)
[ ] 空/畸形 body、缺 header、content 非合法 JSON 均不抛 5xx                       (AC-8)
[ ] 能解开但明文结构非法 → 200 + 忽略（与"解密失败 400"区分清楚）
[ ] 日志脱敏：Encrypt Key / App Secret / Verification Token / access token / 密文 / 明文 payload
    均不出现在 caplog
[ ] 下游可获得 open_id / message_id / chat_id / text（§7.4 映射表逐行断言）        (供给 003/004)
[ ] 既有 Web 路径零回归：git diff 不含 api/v1/chat.py、main.py、application/**     (约束)
[ ] 既有文件改动仅 api/v1/router.py（+1 行）与（必要时）tests/conftest.py          (约束)
    ⚠️ 注意：`pyproject.toml` / `uv.lock` 的改动属 **FEISHU-001**，不在本 Task
```

## 14. Out of Scope

| 不做 | 归属 |
|---|---|
| `open_id → internal_user_id / session_id` 映射 | FEISHU-003 |
| `channel_identities` 表与迁移 0036 | FEISHU-003 |
| 调 `agent_service.stream_chat`、LLM 获取、回复累积 | FEISHU-004 |
| per-user 串行 / 队列上限（`FEISHU_MAX_CONCURRENT_TURNS`、`FEISHU_SESSION_QUEUE_LIMIT`） | FEISHU-004 |
| 出站 `im/v1/messages/{message_id}/reply`、文本切分、出站重试幂等 | FEISHU-005 |
| 错误矩阵全量收口、静态依赖边界断言、冒烟清单 | FEISHU-006 |
| 群聊、非文本、卡片、Streaming、多机器人 | 不做（架构 §7.2）。**主动消息**：出口能力属 FEISHU-005，触发方（Autonomy / Scheduler / Policy）不在本次范围 |
| 跨进程去重 / Redis / MQ / 持久化事件表 | 不做（§10 已论证） |

## 15. Implementation Notes

### 15.1 依赖决策（**已决策：方案 A —— 正式支持 Encrypt Key**）

**决策（Risk #1 = A）**：

> 引入 **`cryptography`** 到 `[project].dependencies`，**完整支持 Feishu Encrypt Key**——包括 `AES-256-CBC` 解密、以及协议要求的 `X-Lark-Signature` 签名校验。

**背景（为什么必须引入依赖）**：加密事件（`{"encrypt": ...}`）必须做 AES 解密，而 **Python 标准库没有 AES**，且**决策时**全仓库与 `uv.lock` 中**不存在任何加密库**（已核实：`cryptography` / `pycryptodome` 当时均未出现在锁文件）。因此**不存在 stdlib 替代方案**。（依赖现已由 FEISHU-001 经 `uv add` 落入锁文件——上文描述的是决策依据，不是当前状态。）

> 与 FEISHU-001 的 httpx 情形**必须区分**：HTTP 传输层能守白名单，是因为 `urllib` 有等价替代；**AES 没有替代** —— 两者是**独立的决策**，不要因为"引入了 cryptography"就顺手也把 HTTP 换成 httpx。

**决策理由（逐条）**：

1. Feishu Webhook 需要支持 Encrypt Key 场景；
2. Python 标准库没有 AES 实现；
3. 当前项目依赖中没有现成 AES 加密库；
4. 项目未来需要**公网**接收 Feishu Webhook；
5. 不启用 Encrypt Key 会**同时削弱签名校验能力**（飞书签名以 Encrypt Key 为密钥材料）；
6. 本项目是**长期角色系统**而非一次性 Demo，不应为少一个依赖而牺牲 Webhook 安全能力；
7. `cryptography` 成熟、职责明确、wheel 齐全，增加成本很小。

**落地结果（属 FEISHU-001 的职责，本 Task 消费）**：

```text
[ ] cryptography 进入 [project].dependencies（非 dev 组，生产 uv sync --no-dev 才装得到）
[ ] uv add cryptography → uv.lock 由 uv 生成（禁止手工编辑 lock）
[ ] 实测可导入：from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
```

**签名校验不受影响**：`hashlib` + `hmac` 是标准库，无需额外依赖。

**被否决的替代方案（仅作记录，不再作为选项）**：

| 方案 | 否决理由 |
|---|---|
| 只支持未加密事件（不引入依赖） | 公网 Webhook 需要加密 + 签名；且本项目是长期系统，不应为此降级安全能力 |
| 纯 Python 实现 AES | 安全与性能均不可接受，**禁止** |

> **与 R4 的关系**：`cryptography` 只在 `channels/feishu/`（`events.py`）内使用；`channels/base.py` **仍必须零第三方依赖**。换言之，**加密能力不会让核心层间接染上第三方依赖**。

### 15.1b 配置语义（Encrypt Key 的两种状态都有明确定义）

| `FEISHU_ENCRYPT_KEY` | 接受的来件 | 可执行的校验 | 备注 |
|---|---|---|---|
| **非空** | **加密事件**（并兼容未加密事件，若飞书侧混发） | `verification token` + 时间戳窗口 + **`X-Lark-Signature`** + **AES 解密** | **推荐的生产姿态**（完整验证） |
| **为空** | **未加密事件** | `verification token` + 时间戳窗口 | **不允许**被描述为"暂不支持/未来实现"；这是**允许但降级**的运行状态，启动时记安全性降级 `warning`。**官方协议下未配置 Encrypt Key 时提供的校验要素，实现阶段必须以官方文档确认**，不得自行设计一套"看起来合理"的验证协议 |

**不得混同（架构 §6.4）**：`verification token` 与 **签名校验**是**并列的两道关**，职责不同 —— 前者证明"请求来自我们配置的应用"，后者证明"请求体未被篡改"。**禁止把 token 当作签名校验的替代品。**

### 15.2 官方文档复核清单（**实现期必做**）

本 Task 涉及的飞书协议细节**必须在编码前对照飞书开放平台官方文档复核**，不得凭记忆固化：

```text
[ ] 事件订阅版本：v2（header.token）vs v1（body.token）字段位置
[ ] Verification Token 的字段路径（header.token / token）
[ ] 签名 header 名：X-Lark-Signature / X-Lark-Request-Timestamp / X-Lark-Request-Nonce
[ ] 签名拼接顺序与是否使用「原始 body 原文」（键序不得重排）
[ ] 时间戳单位（秒 vs 毫秒）与允许偏差
[ ] 加密算法与参数：AES-256-CBC、key=SHA256(encrypt_key)、IV=前 16 字节、PKCS#7
[ ] 官方是否给出可直接复用的示例密文/密钥（作为测试交叉验证向量）
[ ] 未配置 Encrypt Key 时官方提供的校验要素（哪些 header、是否仍下发签名）
[ ] 加密与未加密两种来件在官方协议下是否可能混发
[ ] encrypt payload 的形态（顶层仅 "encrypt" 一个键）
[ ] im.message.receive_v1 事件结构：sender.sender_id.open_id / message.{message_id,chat_id,chat_type,message_type,content}
[ ] content 为字符串化 JSON（需二次解析）
[ ] 飞书事件回调超时阈值与重推策略（确认 3s 口径）
[ ] 重推时 event_id 是否保持不变（去重键有效性的前提）
```

**测试向量**：加密用例的密文必须用**官方文档给出的示例**或本地按同一算法生成的**固定向量**（含 IV），禁止每次运行随机生成（否则失败不可复现）。

### 15.3 conftest 的两种情形

- **首选**：复用 `observability.spawn_background` → 任务进 `observability.background_tasks` → conftest 既有 teardown 已等待 → **conftest 零修改**。
- **若实现选择自建 `channels` 自己的 `background_tasks` 集合**：则**必须**在 conftest teardown 的等待条件中并联该集合（新增 `feishu_tasks()` 辅助），否则后台任务会跨用例泄漏 → 偶发失败。此时 conftest 属白名单内允许修改。

### 15.4 不新增配置键

本 Task 只消费 001 已冻结的键（`feishu_enabled` / `verification_token` / `encrypt_key` / `dedupe_ttl_seconds` / `signature_window_seconds`）。去重表容量、限流阈值等**不得**新增配置；限流阈值复用既有 `chat_rate_limit_per_minute`。若实现期发现确需新键，须先回填 architecture.md §5.1 再实现（与 001 的 3 个重试键同一流程）。

### 15.5 `event_id` 为何不进 `InboundMessage`

`event_id` 是**通道私有**概念（它的唯一用途是本 Task 的去重），进入通道无关基元会污染 §7.4 的复用契约。若后续 Task 确实需要（例如在 trace 里关联飞书事件），走 `metadata` 扩展位——这也是 `base.py` 保留 `metadata` 的用意。

### 15.6 不添加代码注释

遵守项目全局约定：用命名表达意图（`events.py` 的函数名即为文档）。

### 15.7 Implementation Order

```text
1. events.py 纯函数（解密/验签/challenge/解析/过滤/去重/限流）+ 对应单测（红→绿）
2. adapter.py 骨架（handle_inbound_message + trace + 全异常兜底）+ reset 接缝
3. api/v1/feishu.py 路由（原始 body → 校验 → 解析 → 去重 → ack → spawn_background）
4. router.py 注册（+1 行）
5. tests/e2e/test_feishu_webhook.py（含 ack 时序、auth 不派发、disabled 404）
6. Focused → Module → Fast Test
7. 文档收口：architecture.md §5.1 已回填（crypto 依赖与 Encrypt Key 语义，本次决策已完成）
```
