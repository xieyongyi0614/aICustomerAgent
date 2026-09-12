# FEISHU-001 Task Detail — Feishu 基础配置与认证

> 上游：[../tasks.md](../tasks.md) FEISHU-001 ｜ 架构：[../architecture.md](../architecture.md) §5 / §6.2 ｜ 依赖：**无**
> Priority：**P0** ｜ 层级：Foundation（Channel Adapter 地基层，FEISHU-002~006 全部依赖本 Task 的产物）
> **本 Task 的产出形态**：`Feishu 配置 → Settings → Feishu Client → tenant_access_token → HTTP 请求基础设施`。**不含** Webhook、入站事件、User/Session 映射、Chat Pipeline、AI 回复、消息发送。

---

## Background

飞书接入的第一段是"**能安全地跟飞书通信**"这一件事本身。看似简单，但这里埋着三个会在后续 Task 放大成事故的点：

1. **凭据的落点**。飞书用 `App ID` + `App Secret` 换取 `tenant_access_token`。密钥一旦进代码或进日志，后续所有 Task 都在错误的基线上建设——而项目全局约定要求"禁止在源码硬编码密钥，只从环境变量或 `.env` 读取"。
2. **token 的获取语义**。飞书 token 有 TTL（`expire=7200`）。如果每次请求都去换一次 token，等于每个用户消息都多一次跨公网往返，并且会被飞书侧限流；如果只在"过期后才刷新"，则会出现"token 在请求飞行途中过期"的边界失败。因此必须有**缓存 + 提前刷新 + 并发单飞**。
3. **失败的可判定性**。后续 Task（尤其是 FEISHU-005 发送消息）需要根据"这个失败该不该重试"做决策。如果错误判定散落在调用点（`if status_code == 429 ...`），后续每个调用点都要重复一遍这套判断，必然漂移。因此错误分类必须在**本 Task 一次性收口**。

同时，本 Task 必须证明一件架构上的事：**`FEISHU_ENABLED=false` 时，飞书接入对系统完全无副作用**（不建 HTTP 客户端、不请求 token、不发网络请求）。这是 architecture.md §5.2「未启用即隐身」的可执行形式，也是它能安全合入主干的前提。

## Objective

交付 Channel Adapter 的地基，使后续 Task 只需"调用"而不需要"再搭一遍基础设施"：

- **配置**：`FeishuSettings` 覆盖 architecture.md §5.1 的 14 项 + 本 Task 增补的 3 项重试策略（共 17 项，见「Data Model」），含启用即校验、类型/区间校验、env 可覆盖。
- **接线**：`FeishuSettings` 组合进既有 `Settings`，最小改动、不影响既有配置与旧测试。
- **通道无关契约**：`app/channels/base.py` 定义**入站基元**（`InboundMessage` / `ChannelIdentity` / `ChannelReply`）与**出站契约**（`RecipientRef` / `OutboundMessage` / `SendResult` / `ChannelErrorKind` / `ChannelAdapter` Protocol），任何飞书特有概念都不得进入。**本 Task 只冻结契约，不实现出站行为**（Feishu 侧的 `send` 实现在 FEISHU-005）。
- **出站基础设施**：`tenant_access_token` 获取 / 缓存 / 提前刷新 / 并发单飞，以及可复用的 HTTP 传输层、错误分类、重试骨架。
- **安全**：密钥零硬编码、日志与异常零泄漏。
- **隐身边界**：`FEISHU_ENABLED=false` → 网络请求数恒为 0。

**本 Task 结束时的系统状态**：可以（在测试中）拿到一个有效的 `tenant_access_token`，并且知道每一次失败属于哪一类、该不该重试。除此之外系统行为与现状**完全一致**。

## Existing Architecture

审计结论（决定本 Task 的落地形态）：

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/core/settings/`（16 个领域模块） | `_shared.py` 提供 `DOMAIN_MODEL_CONFIG`（`env_file=".env"`, `extra="ignore"`）+ `SettingsError`；各领域模块用 `@model_validator(mode="after")` 做校验（见 `observability.py`） | **新增** `feishu.py`，形状对齐既有领域模块 |
| `app/core/settings/__init__.py` | `Settings(...)` 多继承组合 16 个领域基类 + `get_settings()`（`@lru_cache`） | **修改**：加 1 个 import + 在基类列表追加 `FeishuSettings` |
| `app/core/llm_factory.py` | **既有懒构造范式**：模块级 `_llm_cache: dict`、首次使用时构造、`set_llm()` / `reset_llm()` 作为测试接缝 | **照此模式**实现 client 单例与 token 缓存（见「Data Model」） |
| `app/application/post_process.py` | 既有锁范式：模块级 `_user_write_locks: dict[str, asyncio.Lock]` + `get_user_write_lock()` + `reset_user_write_locks()` | 单飞锁沿用「模块级 + reset 接缝」风格；**但注意 `asyncio.Lock` 的事件循环绑定问题**（见「Implementation Constraints」） |
| `app/core/errors.py` | **不存在**（`target-architecture.md` §4 曾建议新建，实际未落地） | **不创建**；错误类型放 `channels/feishu/errors.py`（Layer 内聚，不污染 core） |
| `app/channels/`、任何 `feishu` 相关代码 | **完全不存在**（全库无 `feishu` / `Feishu` / `app.channels` 命中） | 全新包 |
| `pyproject.toml` | `httpx>=0.28.1` 在 **[dependency-groups].dev**，不在 `[project].dependencies`；`cryptography` 尚未进入 runtime 依赖 | 本 Task 仅限 `uv add cryptography`（Risk #1 = 方案 A）；**不迁移 httpx**（见下方「依赖决策」） |
| `Dockerfile` | 生产镜像执行 `uv sync --frozen --no-dev` | 确认：dev 组依赖在生产**不存在** |
| `tests/conftest.py` | `override_settings` 的 `env_map` 未收录飞书键，但**有兜底**：`key.upper()` 直接 `setenv`（`feishu_enabled` → `FEISHU_ENABLED`）；`get_settings.cache_clear()` 为标配 | **不改**（见「Testing」） |
| `tests/` 分层 | `tests/unit/`（纯逻辑，marker 自动打标）+ `tests/integration/` + `tests/e2e/`；`marker` 由 `pytest_collection_modifyitems` 自动分配 | 新增测试全部落 `tests/unit/` |

### 依赖决策（**HTTP 传输层**，与 Risk #1 crypto 无关）

> 本节只讨论 **HTTP 传输层**用 stdlib 还是 httpx。**与 crypto 依赖无关**——`cryptography` 的引入已在 **Risk #1 中决策为方案 A**（见 §1「runtime 依赖」与 FEISHU-002 §15.1），本 Task 必须引入。

`httpx` 是 dev-only 依赖，生产镜像 `--no-dev` 不会安装它。若让 Feishu Client 直接使用 `httpx`，就必须把 `httpx` 提升到 `[project].dependencies` 并同步 `uv.lock`。虽然这两个文件因 Risk #1（`uv add cryptography`）已在允许改动的白名单内，但白名单**仅限于 cryptography 一项依赖变更**，不应再叠加 httpx 的迁移。

**决策：本 Task 的传输层使用标准库 `urllib.request` + `asyncio.to_thread`，封装在可注入的 `Transport` 协议之后。**

理由：① 避免本 Task 的依赖变更超出 cryptography 一项（白名单约束）；② 与项目既有"阻塞 IO 走 `asyncio.to_thread`"惯例一致（repositories 全量如此）；③ 本 Task 只需要一个 JSON POST 端点，httpx 的连接池 / HTTP2 / 细粒度超时能力用不上；④ 可注入 transport 让测试**零网络**。

> **若团队更倾向 httpx**：需把 `httpx` 从 dev 组移入 `project.dependencies` 并 `uv lock`（额外改 `pyproject.toml` + `uv.lock` 两个文件），同时 `httpx.AsyncClient` 的构造时机必须落到懒构造里（不得在 import 期创建）。此处不实施，留待评审时二选一。

## Data Model

### 1. `FeishuSettings`（`app/core/settings/feishu.py`）

继承 `BaseSettings`，`model_config = DOMAIN_MODEL_CONFIG`（复用 `_shared.py`，继承 `env_file=".env"` / `extra="ignore"`）。字段名平铺（项目惯例），env 名 = 字段名大写。

| 字段 | env | 类型 | 默认 | 校验 | 说明 |
|---|---|---|---|---|---|
| `feishu_enabled` | `FEISHU_ENABLED` | bool | `False` | 无 | 总开关。默认关，与项目"新能力默认关"惯例一致 |
| `feishu_app_id` | `FEISHU_APP_ID` | str | `""` | enabled 时非空 | 飞书应用 ID（非密钥） |
| `feishu_app_secret` | `FEISHU_APP_SECRET` | str | `""` | enabled 时非空 | **敏感** |
| `feishu_verification_token` | `FEISHU_VERIFICATION_TOKEN` | str | `""` | enabled 时非空 | **敏感**；本 Task 只做"配置存在性"校验，校验逻辑属 FEISHU-002 |
| `feishu_encrypt_key` | `FEISHU_ENCRYPT_KEY` | str | `""` | 无（**允许为空**） | **敏感**。**正式支持的配置项**：非空 → 支持加密事件 + 启用签名校验；为空 → 只接受未加密事件（安全性降级，见启动告警）。**解密业务属 FEISHU-002，本 Task 只做配置与取值出口** |
| `feishu_api_base` | `FEISHU_API_BASE` | str | `"https://open.feishu.cn"` | 必须以 `http://`/`https://` 开头；尾部 `/` 归一化 | 可指向假服务以便测试 |
| `feishu_llm_profile` | `FEISHU_LLM_PROFILE` | str | `""` | 无 | 空 = 走 `DEFAULT_LLM_PROFILE`（本 Task 不消费，仅登记） |
| `feishu_timeout_seconds` | `FEISHU_TIMEOUT_SECONDS` | float | `10.0` | `> 0` | 单次出站 HTTP 超时 |
| `feishu_token_refresh_ratio` | `FEISHU_TOKEN_REFRESH_RATIO` | float | `0.8` | `0.0 < r < 1.0` | 提前刷新比例（见 §「Token 语义」） |
| `feishu_max_reply_chars` | `FEISHU_MAX_REPLY_CHARS` | int | `4000` | `> 0` | 本 Task 只登记（消费在 FEISHU-005） |
| `feishu_dedupe_ttl_seconds` | `FEISHU_DEDUPE_TTL_SECONDS` | int | `600` | `> 0` | 只登记（消费在 FEISHU-002） |
| `feishu_signature_window_seconds` | `FEISHU_SIGNATURE_WINDOW_SECONDS` | int | `300` | `> 0` | 只登记（消费在 FEISHU-002） |
| `feishu_max_concurrent_turns` | `FEISHU_MAX_CONCURRENT_TURNS` | int | `4` | `> 0` | 只登记（消费在 FEISHU-004） |
| `feishu_session_queue_limit` | `FEISHU_SESSION_QUEUE_LIMIT` | int | `5` | `> 0` | 只登记（消费在 FEISHU-004） |
| `feishu_http_max_attempts` | `FEISHU_HTTP_MAX_ATTEMPTS` | int | `3` | `>= 1` | **本 Task 增补** |
| `feishu_http_backoff_seconds` | `FEISHU_HTTP_BACKOFF_SECONDS` | float | `0.5` | `>= 0` | **本 Task 增补** |
| `feishu_http_backoff_max_seconds` | `FEISHU_HTTP_BACKOFF_MAX_SECONDS` | float | `8.0` | `>= backoff_seconds` | **本 Task 增补** |

**配置增补说明**：最后 3 项（重试策略）不在 architecture.md §5.1 的 14 项之内，合计 17 项。之所以新增而不是把 `3` / `0.5` / `8.0` 硬编码进 `client.py`，是因为项目全局约定"**所有阈值/魔法数字放 `core/settings/` 包，禁止硬编码**"——该约定优先级高于"字段列表不变"。**回填事项**：architecture.md §5.1 表格需补这 3 行（本 Task 不改该文件，留待评审统一回填）。

**validator（`@model_validator(mode="after")`）**

```text
1. 区间校验：refresh_ratio ∈ (0,1)、timeout > 0、各 int 项 > 0、
   http_max_attempts >= 1、backoff_max >= backoff
2. api_base 前缀与尾部斜杠归一化（归一化后回写字段，供 client 直接拼接）
3. 启用即校验：feishu_enabled 为真 → app_id / app_secret / verification_token 三者
   任一为空 → raise SettingsError（消息里只提"哪个键缺失"，绝不含值）
4. 未启用时：只做 1/2 的静态校验，不校验凭据（允许 FEISHU_ENABLED=false 且凭据全空）
```

失败一律 `raise SettingsError(...)`（沿用 `observability.py` 既有风格），**不新增异常类型**。

**secret 处理方式**：保持 `str` 类型（与 `LlmProfile.api_key` 的既有处理一致，不引入 `SecretStr` 以免与既有设置风格分叉）。配套提供两个方法作为**唯一的取值出口**：

- `secret_values() -> tuple[str, ...]`：返回所有**非空**的敏感值（app_secret / verification_token / encrypt_key），供日志脱敏使用。
- 约束：settings 实例本身**不得**被日志 / `model_dump` / 异常串直接打印。本 Task 不新增"公开序列化"入口。

### 2. Channel 基元类型（`app/channels/base.py`）

三个 `@dataclass(frozen=True, slots=True)`。**字段名必须通道无关**——这是本 Task 里"可被后续渠道复用"的契约。

| 类型 | 字段 | 必需 | 说明 |
|---|---|---|---|
| `InboundMessage` | `channel: str` | ✅ | 通道标识（本阶段恒 `"feishu"`；字段本身通道无关） |
| | `external_user_id: str` | ✅ | 通道内稳定的用户标识（**飞书侧填 `open_id`，但字段名不得叫 `open_id`**） |
| | `external_thread_id: str \| None` | ⭕ | 通道内会话/线程标识（飞书侧可填 `chat_id`） |
| | `text: str` | ✅ | 纯文本内容（非空） |
| | `reply_ref: str \| None` | ⭕ | 回复锚点（飞书侧可填 `message_id`；**可选**，不得成为强制字段） |
| | `received_at: datetime` | ✅ | 接收时间（时区感知） |
| | `metadata: Mapping[str, Any]` | ⭕ | 有界、可序列化；通道私有扩展一律进这里 |
| `ChannelIdentity` | `channel: str` / `external_user_id: str` | ✅ | 外部身份二元组（映射主键语义） |
| | `tenant: str \| None` | ⭕ | 多租户预留（飞书侧可填 `tenant_key`） |
| | `display_name: str \| None` | ⭕ | 可读名（仅用于日志可读性） |
| `ChannelReply` | `text: str` | ✅ | 要发出的文本（非空） |
| | `reply_ref: str \| None` | ⭕ | 回复锚点（同 `InboundMessage`） |
| | `metadata: Mapping[str, Any]` | ⭕ | 同上 |

**禁止出现在基元中的名字（作为强制字段）**：`open_id` / `union_id` / `tenant_key` / `chat_id` / `message_id` / `event_id` / `app_id` / `tenant_access_token` / `encrypt_key` / `signature` / `lark_*`。允许出现在**值**里（如 `external_user_id` 存的就是 open_id 的值），但不得作为**字段名**。

**守卫（`__post_init__`）**：`channel` 非空、`external_user_id` 非空、`text` 非空且有上限（超限截断并置 `metadata["truncated"]=True`，避免无界内存）、`received_at` 必须时区感知。违规抛 `ValueError`（纯值对象，fail-fast）。

### 3. 出站契约（`app/channels/base.py`，本次修订新增）

通道无关的出站契约。**本 Task 只定义、不实现**；Feishu 侧实现在 FEISHU-005。

| 类型 | 字段 | 必需 | 说明 |
|---|---|---|---|
| `RecipientRef` | `channel: str` | ✅ | 通道标识 |
| | `external_id: str` | ✅ | 通道内收件人标识（飞书侧填 `open_id`，**字段名不得叫 `open_id`**） |
| `OutboundMessage` | `channel: str` | ✅ | 通道标识 |
| | `recipient: RecipientRef` | ✅ | 收件人（**Reply 与 Proactive 都需要**，因为出站抽象不假设"有锚点"） |
| | `text: str` | ✅ | 要发送的文本（非空） |
| | `reply_ref: str \| None` | ⭕ | **有 = Reply 形态**（锚定某条外部消息）；**无 = Proactive 形态**（主动开口）。实现据此选择底层 API，调用方无需知道有哪些 API |
| | `idempotency_key: str \| None` | ⭕ | **Proactive 必填**（无 `reply_ref` 时无外部消息 id 可依托）；Reply 可省略（由 `reply_ref` 充当） |
| | `metadata: Mapping[str, Any]` | ⭕ | 有界、可序列化；通道私有扩展 |
| `SendResult` | `ok: bool` | ✅ | 是否成功 |
| | `external_message_id: str \| None` | ⭕ | 通道返回的消息 id（飞书 `message_id`；**不含敏感值**） |
| | `error: ChannelErrorKind \| None` | ⭕ | 失败类别（`ok=False` 时非空） |
| `ChannelErrorKind` | `StrEnum` | — | **通道无关错误词汇**：`not_found` / `auth` / `rate_limited` / `timeout` / `server_error` / `client_error` / `disabled` / `invalid_request` / `unknown` |
| `ChannelAdapter` | `Protocol` | — | `async def send(message: OutboundMessage) -> SendResult` |

**三条强制约束**

1. **一个 `send` 而非两个方法**：`reply` 被建模为"带锚点的 send"。拆成 `reply_message` / `send_message` 会要求**调用方**判断"该用哪个"，等于把飞书 API 形态泄漏给核心。合并后由 `reply_ref` 的有无决定，调用方只表达"这条消息是否锚定在某条用户消息上"。
2. **返回 `SendResult`、不抛异常**：出站失败是**正常业务分支**（架构 §6.2 #9），用返回值表达可让"投递永不冒泡"这条不变式在类型层面成立。
3. **`ChannelErrorKind` 而非 `FeishuError`**：核心**永远看不到**渠道的错误分类；飞书 7 类错误在 `channels/feishu/errors.py` 内映射为上述通道无关词汇。

**出站基元同样禁止出现飞书特有字段名**：`open_id` / `union_id` / `chat_id` / `message_id` / `reply_message_id` / `receive_id` / `receive_id_type` / `msg_type` / `tenant_access_token` / `app_id` / `lark_*`。

**`base.py` 的依赖面约束（新增，R4）**：**零第三方依赖、零 `app.*` 依赖**（仅标准库）。原因：这是被**核心层**（`application` / `services`）允许 import 的最底层契约（architecture §2.2 R2），一旦带上第三方依赖或 `app.*` 依赖，就会把依赖图污染到核心。由 FEISHU-006 的专项依赖面断言守门。

### 4. 本 Task 只定义数据契约，不定义行为实现

入站侧的 `parse`（事件解析）**行为**留给 FEISHU-002；出站侧的 `send`（飞书发送）**行为**留给 FEISHU-005。本 Task 冻结的是**两边的类型与协议签名**——因为它们是跨 Task 的接口，必须在任何实现之前定死；而**函数体**属于各自 Task。

### 5. Tenant Token 运行时模型（`app/channels/feishu/client.py` 内私有）

| 字段 | 类型 | 说明 |
|---|---|---|
| `access_token` | str | token 值（**唯一允许存放明文的地方，且不出模块**） |
| `issued_at` | float | 获取时刻（`time.monotonic()`，不受系统时钟调整影响） |
| `expires_in` | int | 飞书返回的 `expire`（秒，通常 7200） |

派生量（不落库、不缓存在模块外）：

```text
refresh_deadline = issued_at + expires_in * refresh_ratio    # 软线：0.8 → 约 5760s
hard_deadline    = issued_at + expires_in                    # 硬线：7200s
needs_refresh(now, ratio) = now >= refresh_deadline
is_expired(now)           = now >= hard_deadline
```

### 6. 传输层契约（`client.py` 内 `Transport`）

```
Transport.post_json(url: str, body: dict, timeout: float) -> HttpResponse
HttpResponse: { status: int, json: dict | None, raw_len: int }
```

- 生产实现：`urllib.request`（`POST` + `application/json; charset=utf-8`）包 `asyncio.to_thread`；`HTTPError` → 取其 status 与 body；`URLError`/`socket.timeout`/`TimeoutError` → 归类为 timeout。
- 测试实现：`FakeTransport`，内置 `calls: list`（**请求计数与请求体**）与可编程的响应/异常序列。
- **注入接缝**：`set_transport(t)` / `reset_feishu_client()`（对齐 `llm_factory.set_llm` / `reset_llm`）。

## Interfaces

> 以下为**概念契约**（对外能力与语义），不含实现。

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 加载配置 | env / `.env` | `FeishuSettings` | 启用即校验；区间越界抛 `SettingsError` |
| 取 token | 无 | `str`（`tenant_access_token`） | **本 Task 唯一对外网络能力**；缓存命中零网络；并发单飞 |
| 取 token 图（可观测） | 无 | `TokenView` | `{has_token, needs_refresh, expires_in, age_seconds}`——**不含 token 值** |
| 清空缓存/接缝 | 无 | `None` | `reset_feishu_client()`：清 token、清锁、还回默认 transport、还回默认时钟 |
| 归类失败 | `http_status`、`feishu_code`、异常 | `FeishuError` 子类 | **全项目唯一的 HTTP→错误映射点** |
| 执行带重试调用 | 可调用对象 + `RetryPolicy` + sleep | 结果 或 `FeishuError` | 只重试可重试类；sleep 可注入 |

**禁止**：任何人（含后续 Task）在调用点写 `if status_code == 429` 之类的判断。判断只在 `errors.classify(...)` 一处。

## Processing Flow

### 取 token（正常路径）

```text
get_tenant_access_token()
        │
        ├─ settings.feishu_enabled == False ──► raise FeishuDisabledError（零网络）
        │
        ├─ 读模块级 _token
        │      └─ 命中且 not needs_refresh ──► return token.value（零网络）
        │
        ├─ 取锁（懒创建，见下）→ async with lock:
        │      ├─ double-check：再读 _token（拿锁期间可能已被他人刷新）
        │      │      └─ 命中且 not needs_refresh ──► return（零网络）
        │      ├─ 调 _fetch_tenant_token()            ← 锁内唯一必要工作
        │      │      ├─ POST {api_base}/open-apis/auth/v3/tenant_access_token/internal
        │      │      │   body: {"app_id": ..., "app_secret": ...}   timeout: feishu_timeout_seconds
        │      │      ├─ errors.classify(status, code) → 0 / 抛错
        │      │      ├─ 校验响应结构（code==0 且 token 非空且 expire>0）
        │      │      └─ 失败按 RetryPolicy 退避重试（仅可重试类）
        │      └─ _token = TenantToken(...)          ← 赋值
        │
        └─ return token.value
     （日志 / 掩码 / 异常构造全部在锁外）
```

### 取 token（刷新失败的降级路径）

```text
needs_refresh == True（软线已过，硬线未到）
        │
        ├─ 刷新成功 ──► 用新 token
        └─ 刷新失败（且旧 token is_expired == False）
                          │
                          ├─ log warning（脱敏）
                          └─ return 旧 token.value        ← 可用性优先，不让一次抖动打断服务
                             （硬线已过 + 刷新失败 → 抛 FeishuError，绝不返回过期 token）
```

### 飞书认证接口（唯一端点）

| 项 | 值 |
|---|---|
| URL | `{feishu_api_base}/open-apis/auth/v3/tenant_access_token/internal` |
| Method | `POST` |
| Headers | `Content-Type: application/json; charset=utf-8` |
| Body | `{"app_id": "<FEISHU_APP_ID>", "app_secret": "<FEISHU_APP_SECRET>"}` |
| Timeout | `feishu_timeout_seconds` |

**成功响应（HTTP 200）**

```json
{ "code": 0, "msg": "ok", "tenant_access_token": "t-xxxxxxxx", "expire": 7200 }
```

提取：`tenant_access_token` → `access_token`；`expire` → `expires_in`（秒）。

**失败响应（关键）**：飞书该端点**可能返回 HTTP 200 + 非零 `code`**（如 `app_id`/`app_secret` 非法）。因此判定顺序必须是：

```text
1. errors.classify(http_status, code)：先看 HTTP（429/5xx/4xx）
2. HTTP 2xx 时再看业务 code：code != 0 → 认证/配置类（不可重试）
3. 只有 code == 0 才进入结构校验（token 非空、expire > 0 且为数值）
```

**只看 HTTP status 会把认证失败误判为成功并缓存一个空 token。**

## State Transition

Token 生命周期（进程内，单实例）：

```text
        ┌──────────┐
        │  absent  │◀─────────────────────────────┐
        └────┬─────┘                              │
   get_token │ 未命中                             │ 刷新失败
             ▼                                    │ 且旧值已过期
      ┌─────────────┐   code==0 且结构合法        │
      │  fetching   │──────────────────────┐      │
      └─────┬───────┘                      ▼      │
            │ 失败(最终)               ┌───────────┐
            └─────────────────────────▶│   valid   │
                                      └─────┬─────┘
                                            │ now >= refresh_deadline(0.8)
                                            ▼
                                      ┌─────────────┐  code==0   ┌───────────┐
                                      │ refreshing  │──────────▶│   valid   │（新值覆盖）
                                      └─────┬───────┘           └───────────┘
                                            │ 失败
                          ┌─────────────────┴──────────────────┐
                          ▼                                    ▼
                  ┌───────────────┐                  ┌──────────────────┐
                  │   degraded    │                  │      absent      │
                  │ 复用旧 token  │                  │  抛 FeishuError  │
                  └───────────────┘                  └──────────────────┘
                  （not is_expired）                  （is_expired）
```

| 当前 | 事件 | 目标 | 说明 |
|---|---|---|---|
| `absent` | fetch_ok | `valid` | 缓存新 token |
| `absent` | fetch_fail（终败） | `absent` | 抛错，缓存仍空 |
| `valid` | `now < refresh_deadline` | `valid` | 零网络直接返回 |
| `valid` | `now >= refresh_deadline` + fetch_ok | `valid` | 覆盖为新值 |
| `valid` | `now >= refresh_deadline` + fetch_fail + `not is_expired` | `degraded` | 保留旧值，log warning 后返回旧值 |
| `valid` | `now >= refresh_deadline` + fetch_fail + `is_expired` | `absent` | 清空并抛错 |
| `degraded` | 再次 get_token 且仍 `not is_expired` | `degraded` | 继续尝试刷新（下次仍可能成功） |

**边界规则（明确）**：比较一律用 `now >= deadline`（含等号）；`expires_in <= 0` 或缺失 → **不缓存**，按结构非法处理；`refresh_ratio` 由 validator 保证在 `(0,1)` 开区间内，因此 `refresh_deadline < hard_deadline` 恒成立（不会出现"软线越过硬线"）。

## Error Handling

### 1. 层级（`app/channels/feishu/errors.py`）

```text
FeishuError(Exception)                     # 基类：携带 operation / status / feishu_code / retryable
├── FeishuDisabledError      retryable=False  # FEISHU_ENABLED=false 时被调用
├── FeishuConfigError        retryable=False  # 配置非法 / 响应结构非法（200+无法解析/token 为空/expire<=0）
├── FeishuAuthError          retryable=False  # 401/403，或 HTTP 2xx + code=10003 等认证类业务码
├── FeishuClientError        retryable=False  # 其余 400~499（404/422 …）
├── FeishuRateLimitError     retryable=True   # 429
├── FeishuServerError        retryable=True   # 5xx
└── FeishuTimeoutError       retryable=True   # 超时 / 连接失败 / DNS 失败
```

**关键设计**：`retryable` 是**类属性**（子类覆盖），不是调用点判断。分类只发生在唯一函数：

```text
errors.classify(operation, http_status, feishu_code, exc=None) -> FeishuError
```

判定顺序（唯一事实，禁止在别处重复）：

| 输入 | 结果 |
|---|---|
| 429 | `FeishuRateLimitError`（retry） |
| 5xx（500/502/503/504…） | `FeishuServerError`（retry） |
| 超时 / 连接失败 / DNS | `FeishuTimeoutError`（retry） |
| 401 / 403 | `FeishuAuthError`（**非 retry**；凭据问题重试无意义） |
| HTTP 2xx + `feishu_code` 为认证类 | `FeishuAuthError`（非 retry） |
| HTTP 2xx + `feishu_code` 非 0（其余） | `FeishuConfigError`（非 retry） |
| 其余 4xx（400/404/422…） | `FeishuClientError`（非 retry） |
| 其它未预期 | `FeishuConfigError`（保守：非 retry，避免放大） |

### 2. 场景处理表

| 情形 | 处理 | 用户可见影响 |
|---|---|---|
| `FEISHU_ENABLED=false` 时调用取 token | 立即 `FeishuDisabledError`，**不构造 transport、不发请求** | 无（正常路径不会调用） |
| 启用但凭据缺失 | **启动阶段** `SettingsError`（不等第一个请求） | 无（服务起不来，配置问题暴露最早） |
| 网络超时 / 连接失败 | `FeishuTimeoutError` → 退避重试至上限 → 终败抛错 | 无（本 Task 无对外接口） |
| 429 | `FeishuRateLimitError` → 退避重试 | 无 |
| 5xx | `FeishuServerError` → 退避重试 | 无 |
| 401 / 403 / code=10003 | `FeishuAuthError`，**不重试**，error 日志（脱敏） | 无 |
| 200 但结构非法（无 token / `expire<=0` / body 非 JSON） | `FeishuConfigError`，不重试，日志只记 `status`、`raw_len`、`code` | 无 |
| 软线后刷新失败但未硬过期 | log warning，**返回旧 token**（降级） | 无（可用性优先） |
| 硬过期 + 刷新失败 | 清空缓存 + 抛 `FeishuError` | 无 |
| 重试彻底失败 | 抛最后一次的错误（保留原始类型，不包装成新类型） | 无 |

**契约**：本 Task **不产生任何对外可见行为**——所有失败都只表现为"抛错 + 日志"。飞书侧用户可见的降级文案由 FEISHU-005 负责。

## Idempotency

本 Task 的"幂等"落在**并发单飞**上（它与幂等共享同一目标：同一逻辑请求只产生一次真实副作用）。

### 单飞设计（明确到可验收）

| 项 | 决定 |
|---|---|
| 同步机制 | `asyncio.Lock`（互斥）+ **double-check**（拿锁后重读缓存） |
| 锁的生命周期 | 模块级、进程内单例、懒创建（首次需要时创建），存活至 `reset_feishu_client()` |
| 临界区内容 | **仅**：① 重读 `_token`；② 一次 `_fetch_tenant_token()`（含其内部必要的退避重试）；③ 赋值 `_token` |
| 临界区**不做** | 不打日志、不做掩码、不构造异常文案、不做任何额外 IO、不访问 DB、不调用 LLM |
| 并发结果 | N 个并发调用 → 真实 HTTP 请求 **恰好 1 次**；N-1 个在锁外等待后命中 double-check 直接返回 |
| 跨进程语义 | **不做**跨进程单飞（多 worker 各自持有一份 token，飞书侧可容忍）。这是有意的范围限制 |
| 失败传播 | 锁内刷新失败 → 抛错；等待者拿锁后重新 double-check（此时缓存仍是旧值），按「Error Handling」的降级规则决定复用或抛错——**不缓存失败结果** |

> **被否决的替代方案**：用 `asyncio.Future` 做"在途共享"（followers await 同一个 future），可把锁的持有时间压到 O(1)。否决理由：token 获取频率约每 96 分钟一次，两个方案的**实际等待时长等价**（等待者本来就在等同一个 token），引入 future 的失败传播与清理语义得不偿失。符合"不引入没有必要的新抽象"。

## Transaction Boundary

**无事务、无数据库**。本 Task 零 DB 依赖：不新增迁移、不建表、不读写任何仓储、不注册 lifespan 循环（`app/main.py` **不改**）。

唯一的状态是**进程内内存**：

```text
_token: TenantToken | None        ← 模块级
_token_lock: asyncio.Lock | None  ← 模块级，懒创建
_transport: Transport | None      ← 模块级，懒创建
_clock: Callable[[], float]       ← 模块级，默认 time.monotonic
```

**重启即失效**（可接受：token 可随时重取）。因此本 Task 不涉及崩溃重放、不涉及跨进程一致性——这也是它能保持"零副作用"的原因。

## Observability

- **日志**（`logging.getLogger(__name__)`，沿用项目做法）：
  - `info`：token 获取成功 → 记 `operation`、`attempt`、`elapsed_ms`、`expires_in`（**不记 token 值**）。
  - `warning`：一次可重试失败将重试 → 记 `operation`、`attempt`、`error_type`、`status`。
  - `warning`：软线刷新失败但复用旧 token（degraded）。
  - `error`：终败 / 认证失败 / 配置非法 → 记 `operation`、`error_type`、`status`、`feishu_code`。
- **脱敏**：client 产出的每条日志与每个异常文案都必须过 `_scrub(text, settings.secret_values())`——把命中的敏感值替换为 `<redacted>`。token 值从不进入任何日志 / 异常 / trace 字段。
- **可观测视图**：`token_view() -> TokenView`（`has_token` / `needs_refresh` / `expires_in` / `age_seconds`），供后续 Task 与 debug 端点使用；**结构上不可能泄漏 token 值**。
- **trace**：本 Task **不新增 trace 步骤**（不碰 `services/trace_collector.py`、不碰 `core/constants.py` 的 `TRACE_STEP_NAMES`）。飞书链路的 trace 接入属 FEISHU-004。
- **无新增埋点、无新增持久化**。

## Testing

新增测试全部落 `tests/unit/`（marker 由 `pytest_collection_modifyitems` 自动打 `unit`，无需手写）。**零真实网络、零真实 LLM**。

| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_feishu_settings.py` | 默认值 / 启用校验 / 区间校验 / env 覆盖 |
| `tests/unit/test_feishu_errors.py` | 分类矩阵 / `retryable` 标志 / 脱敏 |
| `tests/unit/test_feishu_client.py` | token 获取 / 缓存 / 刷新 / 单飞 / 重试 / 禁用零网络 / 时钟注入 |
| `tests/unit/test_feishu_channel_base.py` | 基元字段白名单 / 不可变 / 守卫 |

### Settings（`test_feishu_settings.py`）

```text
- 默认：feishu_enabled is False；17 项默认值与 §Data Model 表格逐条相等
- 启用且完整：三项凭据齐备（env 注入假值）→ 构造成功
- 启用缺 app_id / app_secret / verification_token → 各抛 SettingsError，消息含缺失键名
- 未启用且凭据全空 → 构造成功（不得报错）
- env 全覆盖：对每个 FEISHU_* 用 monkeypatch.setenv + get_settings.cache_clear() 断言生效
  （风格对齐 test_v2_memory_settings.py）
- 区间：refresh_ratio=0 / 1.0 / 1.5 → SettingsError；timeout=0 → SettingsError；
  backoff_max < backoff → SettingsError
- api_base 尾部斜杠归一化（"https://x/" → "https://x"）；非 http(s) 前缀 → SettingsError
- 组合生效：get_settings() 上可直接访问 feishu_* 字段（证明 Settings 组合成功）
- Encrypt Key 语义（Risk #1 = 方案 A）：非空 → 正常加载；为空 → 加载成功 + 一条安全性降级 warning
  （断言 caplog 有 warning，且 warning 文案**不含密钥值**）
- crypto runtime 依赖：`uv run python -c "from cryptography.hazmat.primitives.ciphers import Cipher"` 成功
```

**关于 conftest**：`override_settings(feishu_enabled=False)` 走既有兜底分支（`feishu_enabled`.upper() → `FEISHU_ENABLED`）即可生效，**`tests/conftest.py` 无需修改**；需要重置单例时在测试文件内用**本文件 autouse fixture** 调 `reset_feishu_client()`（不新增全局夹具）。

### Token（`test_feishu_client.py`）

```text
- 首次获取：FakeTransport 返回 code=0/expire=7200 → 返回 token 值；transport.calls == 1
- cache hit：连续两次调用 → transport.calls 仍为 1
- 提前刷新：注入假时钟；把 now 推到 issued_at + 7200*0.8 + 1 → 触发第二次请求；
  推到 7200*0.8 - 1 → 不触发（**精确验证 0.8 这条线，不 sleep**）
- 未到软线不刷新 / 越过硬线：now = issued_at + 7200 + 1 → 必刷新
- 刷新失败降级：刷新失败且 now < 硬线 → 返回旧 token + warning 日志
- 硬过期 + 刷新失败 → 抛 FeishuError，且缓存被清空
- 单飞：asyncio.gather 10 个并发 get_token()（FakeTransport 内 await 一个小 sleep 以制造重叠）
  → 断言 transport.calls == 1 且 10 个返回值全等
- 禁用：feishu_enabled=False → 抛 FeishuDisabledError，且 transport.calls == 0（含未构造 transport）
- 结构非法：code=0 但缺 token / expire=0 → FeishuConfigError 且不缓存
- clock 注入：断言不依赖真实时间（测试总时长不随 TTL 增长）
```

### Retry（`test_feishu_client.py` + `test_feishu_errors.py`）

```text
- 429 / 500 / 502 / 503 → 重试；最终失败时抛对应错误类型；重试次数 == max_attempts - 1
- timeout（transport 抛超时）→ 重试
- 400 / 401 / 403 / 404 → 不重试（transport.calls == 1）
- 退避：注入记录型 fake sleep → 断言序列 [b*1, b*2, b*4 ...] 且被 backoff_max 截断
  （例如 b=0.5, max=8 → [0.5, 1.0, 2.0] 之类按 attempts 截断；**测试不真实等待**）
- max_attempts=1 → 不重试
- 重试后成功 → 返回结果，且只记 warning 不记 error
```

### Security（`test_feishu_client.py`）

```text
- 触发各类失败（含 200+code!=0）→ 断言 caplog 全部文本中不含 app_secret / encrypt_key / token 值；
  含 <redacted> 或完全不含该串
- 异常对象：str(exc) 与 exc.args 均不含密钥与 token
- token_view() 的字段集合恰好为 {has_token, needs_refresh, expires_in, age_seconds}（无 token 值字段）
```

### Disabled（`test_feishu_client.py`）

```text
- feishu_enabled=False → get_tenant_access_token() 抛 FeishuDisabledError
  且断言 transport 从未被构造 / 从未被调用（calls == 0）
```

### Base Protocol（`test_feishu_channel_base.py`）

```text
- 字段白名单（核心断言）：InboundMessage / ChannelIdentity / ChannelReply 的
  dataclass fields 名称集合恰好等于期望集合；对禁用名单
  {open_id, union_id, tenant_key, chat_id, message_id, event_id, app_id,
   tenant_access_token, encrypt_key, signature} 逐个断言"不作为字段名出现"
- 不可变：frozen dataclass 赋值抛异常
- 守卫：空 channel / 空 external_user_id / 空 text → ValueError；
  非时区感知 received_at → ValueError；超长 text 被截断并置 metadata["truncated"]=True

【出站契约（本次修订新增）】
- 字段白名单：RecipientRef / OutboundMessage / SendResult 的字段名集合恰好等于期望集合；
  对禁用名单 {open_id, union_id, chat_id, message_id, reply_message_id, receive_id,
  receive_id_type, msg_type, tenant_access_token, app_id, lark_*} 逐个断言"不作为字段名出现"
- ChannelErrorKind：值域闭集断言（恰好 9 个取值）；**不含任何飞书业务码**（如 10003 / 99991400）
- 形态语义：OutboundMessage(reply_ref=None) 表示 Proactive；reply_ref 非空表示 Reply
  （断言两个形态都能构造，且不触发任何 IO）
- Protocol：空壳 ChannelAdapter 实现 satisfies 协议（runtime_checkable 断言）；
  缺少 send 的类 **不** satisfies
- 依赖面（R4，核心断言）：AST 扫描 app/channels/base.py → 只 import 标准库；
  零第三方依赖、零 app.* 依赖（失败信息含模块名）
```

**执行级别（AGENTS.md 门槛）**：`Focused Test`（4 个测试文件）→ `Module Test`（`pytest tests/unit -m unit`）→ 因涉及 `core/settings/` 基础设施改动，补跑 `Fast Test`（`pytest -m "(unit or api) and not slow"`）。
**Windows 提示**：本机跑 pytest 需 `--basetemp=.tmp/pytest -p no:xdist`（系统 temp 目录 PermissionError），产物落 `apps/backend/.tmp/` 并随手删除。

## Acceptance Criteria

> 与 [../tasks.md](../tasks.md) FEISHU-001 的 6 条 AC 一一对应（映射见括号）。

```text
配置与组合
[ ] FEISHU_* 全部 17 项默认值（14 项与 architecture.md §5.1 一致 + 3 项重试策略增补）  (AC-3)
[ ] 全部 FEISHU_* 可通过环境变量覆盖（逐键断言）                                     (AC-3)
[ ] FEISHU_ENABLED=true 缺 app_id / app_secret / verification_token → 启动抛 SettingsError (AC-2)
[ ] FEISHU_ENABLED=false 且凭据为空 → 正常构造，不报错                               (AC-2)
[ ] 区间越界（ratio / timeout / backoff / 各 int）→ SettingsError，且报错消息不含密钥值
[ ] FeishuSettings 已组合进 Settings（get_settings() 上可访问 feishu_* 字段）
[ ] 既有测试不受影响：Settings 组合为纯加法（新字段 + 新 validator，默认关闭不触发）

认证与 token
[ ] 首次获取成功，返回非空 token，真实请求次数 == 1                                   (AC-4)
[ ] cache hit 不重复请求（连续 N 次调用，transport.calls 恒为 1）                     (AC-5)
[ ] now >= issued_at + expire*0.8 → 自动刷新；now 略小于该线 → 不刷新（假时钟验证）      (AC-6)
[ ] 10 个并发调用 → 真实请求恰好 1 次，且返回值全等                                   (AC-7)
[ ] HTTP 2xx + code != 0 → 认证类错误，不缓存空 token
[ ] 软线后刷新失败但未硬过期 → 复用旧 token（degraded）+ warning 日志
[ ] 硬过期 + 刷新失败 → 清空缓存并抛错

错误与重试
[ ] 429 / 5xx / timeout 可重试                                                        (AC-8)
[ ] 4xx（400/401/403/404）默认不重试                                                  (AC-9)
[ ] 重试退避序列 = 指数退避且被 backoff_max 截断；测试零真实等待
[ ] 所有 HTTP→错误 映射只出现在 errors.classify 一处（无散落 status_code 判断）

安全
[ ] 源码零硬编码密钥；日志 / 异常 / caplog 中不出现 APP_SECRET / ENCRYPT_KEY / token    (AC-10)
[ ] token_view() 结构上不含 token 值字段

通道协议
[ ] base.py 三个入站基元的字段名集合通过白名单断言；飞书特有名词零出现（强制字段维度）    (AC-11)
[ ] base.py 出站基元（RecipientRef / OutboundMessage / SendResult / ChannelErrorKind）字段名
    集合通过白名单断言；飞书特有名词（open_id/reply_message_id/receive_id_type/msg_type…）零出现
[ ] ChannelErrorKind 为闭集（值域断言：恰好 9 个取值，无飞书业务码）
[ ] OutboundMessage：reply_ref 为空且 idempotency_key 为空 → 构造即可（是否拒绝属 005 的调用方契约校验）
[ ] ChannelAdapter 为 runtime_checkable Protocol；空壳实现 satisfies 协议
[ ] base.py 依赖面（本次修订新增）：AST 扫描证明它只 import 标准库，
    零第三方依赖、零 app.* 依赖（R4）

边界与零回归
[ ] FEISHU_ENABLED=false → get_tenant_access_token 抛 FeishuDisabledError 且网络请求数 == 0  (AC-1)
[ ] 本 Task 未修改 Chat Pipeline（git diff 不含 application/ · api/v1/chat.py 等）      (AC-12)
[ ] 本 Task 未修改 Character / World / Memory（git diff 不含 character/ · services/ · repositories/）(AC-13)
[ ] 现有 Web 路径测试零失败（用例：focused + module + fast 三档全绿）                   (AC-14)
[ ] 既有文件改动仅 4 个：app/core/settings/__init__.py、.env.example、pyproject.toml、uv.lock（git status 可证）
[ ] **crypto runtime 依赖就位（Risk #1 = 方案 A）**：`cryptography` 在 `[project].dependencies`（非 dev 组）；
    `uv.lock` 已由 uv 同步（未手工编辑）；`uv run python -c "from cryptography.hazmat.primitives.ciphers
    import Cipher, algorithms, modes"` 成功；**`channels/base.py` 仍零第三方依赖**（R4 不破）
[ ] `FEISHU_ENCRYPT_KEY` 为空时：配置加载成功（不报错），但产生一条**安全性降级 warning**
```

## Implementation Constraints

**允许新增的文件（全部为新建）**

```text
app/core/settings/feishu.py
app/channels/__init__.py
app/channels/base.py
app/channels/feishu/__init__.py
app/channels/feishu/errors.py
app/channels/feishu/client.py
tests/unit/test_feishu_settings.py
tests/unit/test_feishu_errors.py
tests/unit/test_feishu_client.py
tests/unit/test_feishu_channel_base.py
```

**允许修改的既有文件（共 4 个）**

```text
app/core/settings/__init__.py     # +1 import +1 基类（组合 FeishuSettings）
.env.example                      # 追加 FEISHU_* 键（凭据留空值）
pyproject.toml                    # ★ Risk #1 = 方案 A：uv add cryptography（runtime 依赖）
uv.lock                           # ★ 同上，由 uv 生成（禁止手工编辑）
```

**runtime 依赖：`cryptography`（Risk #1 已决策为方案 A）**

- 加入 `[project].dependencies`（**不是** `[dependency-groups].dev`），因为生产镜像执行 `uv sync --frozen --no-dev`，dev 组依赖在生产**不存在**。
- 加入方式：`uv add cryptography`（项目既有依赖管理流程）→ 自动同步 `uv.lock`。**禁止手工编辑 lock 文件。**
- **本 Task 的边界**：只负责"**保证该依赖已存在且可导入**"（供 FEISHU-002 消费），**不实现**任何 Webhook 解密业务。
- **与 R4 无关**：`cryptography` 只在 `channels/feishu/` 内使用；`channels/base.py` **仍然零第三方依赖**（FEISHU-002 的 `events.py` 才 import 它）。

**明确禁止触碰**：`application/**`、`services/**`、`repositories/**`、`models/**`、`character/**`、`chains/**`、`world/**`、`memory/**`、`relationship/**`、`api/**`、`prompts/**`、`main.py`、`migrations/**`、`tests/conftest.py`。注意：`pyproject.toml` / `uv.lock` 不在禁止清单内，但**仅允许**由 `uv add cryptography` 产生的依赖变更——任何其他内容的手工编辑同样违规。

**硬性约束**

1. **零启动副作用**：`app/channels/__init__.py` 与 `app/channels/feishu/__init__.py` **不得 import `client`**（避免 import 即构造）；不得在 `main.py` 注册任何 lifespan / 启动钩子。唯二允许的 import 是 `__init__.py` 内的 `base` 类型 re-export（可选）与包级 docstring。
2. **懒构造**：`Transport` 与锁都在首次需要时创建；`feishu_enabled=False` 的路径必须在构造之前就抛 `FeishuDisabledError`。（与 `llm_factory` 的懒构造范式一致）
3. **`asyncio.Lock` 的事件循环绑定陷阱**：模块级 `asyncio.Lock` 在首次 `await` 后与当时的 running loop 绑定；pytest-asyncio 每个用例新建 loop，跨用例复用会抛 `RuntimeError: ... bound to a different event loop`。**因此**：`_ensure_lock()` 必须**懒创建**，且**每个测试文件必须用 autouse fixture 调 `reset_feishu_client()` 清空锁**（对齐 `post_process.reset_user_write_locks()` 的既有做法）。
4. **零硬编码阈值**：重试参数、超时、比例全部走 `FeishuSettings`；模块内不得出现裸数字参数（`_Token` 派生量除外，它们是计算式）。
5. **错误判定单点**：`client.py` 内不得出现 `if status == 429` / `if status >= 500` / `if code != 0 → 认证` 之类的判断；一律调 `errors.classify(...)`。
6. **脱敏不可绕过**：client 产出的日志与异常文案统一经 `_scrub(...)`；`secret_values()` 是唯一取值出口。
7. **`retryable` 为类属性**：不得在每个调用点重复判断可重试性。
8. **不新增抽象**：不建 `core/errors.py`、不建 `channels/feishu/retry.py`（重试策略放 `client.py`）、不引入 `SecretStr`、不引入 httpx/tenacity/backoff 等新依赖。
   - **唯一例外（Risk #1 = 方案 A，已决策）**：引入 **`cryptography`**（runtime 依赖）——因为加密事件必须做 AES-256-CBC 解密，而 Python 标准库**没有 AES 实现**，不存在 stdlib 替代方案。该依赖由本 Task 负责加入，由 FEISHU-002 消费。
   - **注意区分**：这与"HTTP 传输层不用 httpx"（见「依赖决策」）是**两件独立的事**——crypto 没有 stdlib 替代，HTTP 有（`urllib`）。
   - **修订说明（本次）**：原约束中的"不定义 `ChannelAdapter` 行为协议（留给 002/005）"**已撤销**。原因：出站契约是**跨 Task 的接口**（FEISHU-005 实现它、未来 Autonomy 消费它），必须在任何实现之前冻结，否则 005 与未来调用方会各自长出不一致的形状。**本 Task 定义协议与类型，但不写实现体**（`send` 的 Feishu 实现属 005）。
9. **`base.py` 的依赖面（新增约束）**：`app/channels/base.py` **零第三方依赖、零 `app.*` 依赖**（仅标准库）。它被核心层允许 import（architecture §2.2 R2），因此必须保持"薄契约"；任何 HTTP / 重试 / 飞书字段进入 `base.py` 都会被 FEISHU-006 的依赖面断言拦下。
10. **`channels/**` 的允许 import 白名单（本次修订）**：`app.core.*`、`app.channels.*`、`openai`（仅异常类型）、标准库。**不得** import `services.*`（除 `channel_identity_service` / `trace_collector` / `agent_service`）/ `repositories` / `models` / `chains` / `character` / `application.chat_pipeline` / `application.post_process` / **任何 Autonomy / Life Loop / Scheduler / Policy 模块**（本 Task 天然满足，FEISHU-006 会用静态断言守门）。
11. **不添加代码注释**，用命名表达意图（全局约定）。
12. **覆盖要求**：`app/channels/*` 不在 `pyproject.toml` 的 coverage omit 列表内（`branch = true`），新增分支需被测试覆盖。

## Implementation Order

```text
 0. 依赖就位（Risk #1 = 方案 A）：`uv add cryptography` → 确认进入 [project].dependencies 且 uv.lock 同步
 1. 调研现有 Settings 架构
    └─ 读 _shared.py / 一个领域模块（observability.py）/ __init__.py / llm_factory.py
       / post_process.py 的锁范式 / conftest 的 override_settings；确认本 Task 的 4 文件白名单
 2. FeishuSettings
    └─ 字段 + 区间 validator + 启用即校验 + secret_values()（先写 settings 单测，红→绿）
 3. Settings 组合
    └─ settings/__init__.py 加 import + 基类；跑既有 settings 测试确认零影响
 4. Channel Base Protocol
    └─ base.py 三个 frozen dataclass + 守卫 + __post_init__（配白名单单测）
 5. Feishu Errors
    └─ 层级 + retryable 类属性 + classify(...)（配分类矩阵单测，先于 client）
 6. Feishu HTTP Transport / Client
    └─ Transport 协议 + urllib 实现 + FakeTransport + set_transport/reset 接缝
 7. Token Cache
    └─ TenantToken + needs_refresh/is_expired + 懒 transport
 8. Single-flight
    └─ 懒锁 + double-check（配 10 并发单飞测试）
 9. Retry
    └─ RetryPolicy + _with_retry（可注入 sleep）（配重试/退避矩阵测试）
10. Unit Tests
    └─ 4 个文件补齐 + 脱敏与禁用零网络断言
11. Focused Test
    └─ pytest tests/unit/test_feishu_settings.py tests/unit/test_feishu_errors.py
       tests/unit/test_feishu_client.py tests/unit/test_feishu_channel_base.py
12. Fast Test
    └─ pytest -m "(unit or api) and not slow"（core/settings 属基础设施 → 门槛要求）
    └─ 收口：git status 无临时产物；git diff 仅允许包含 4 个既有文件：
       app/core/settings/__init__.py、.env.example、pyproject.toml、uv.lock
       （后两者仅限 uv add cryptography 产生的依赖变更）
```

## Out of Scope

以下全部**不属于 FEISHU-001**，各自归属后续 Task（或明确不做）：

| 项 | 归属 |
|---|---|
| Webhook 路由（`POST /api/v1/feishu/events`） | FEISHU-002 |
| URL Verification（`challenge` 回显） | FEISHU-002 |
| Signature Verification（`X-Lark-Signature`） | FEISHU-002 |
| Encrypt / Decrypt（AES 解密 `{"encrypt": ...}`） | FEISHU-002 |
| Event Parser（`im.message.receive_v1` 解析、文本抽取） | FEISHU-002 |
| `event_id` 去重 | FEISHU-002 |
| User / Session Mapping（`open_id → user_id/session_id`） | FEISHU-003 |
| `channel_identities` 表与迁移 `0036` | FEISHU-003 |
| Chat Pipeline 接入（`agent_service.stream_chat`） | FEISHU-004 |
| LLM 调用 / AI 回复生成 | FEISHU-004 |
| 消息发送 / 回复投递（`im/v1/messages`） | FEISHU-005 |
| 群聊处理 | 不做（架构 §3.3 / §7.2） |
| 主动消息 | **出口能力**属 FEISHU-005（本 Task 只冻结其契约）；**触发方**不做（架构 §7.2 / §2.5.6） |
| Streaming | 不做（架构 §7.2） |
| 图片 / 文件 / 语音 / Interactive Card | 不做（架构 §7.2） |
| 数据库迁移（任何 `migrations/**` 改动） | FEISHU-003 |
| 错误矩阵全量收口 / 边界静态断言 / 冒烟清单 | FEISHU-006 |

**本 Task 完成后的可验证状态**：`FeishuSettings` 已组合生效、可 env 覆盖、启用即校验；`app/channels/base.py` 提供三个通道无关基元；可在测试中用假传输拿到并缓存 `tenant_access_token`，并发只打一次真实请求，失败分类明确且可判定是否重试；`FEISHU_ENABLED=false` 时全链路零网络；**系统对外行为与接入前完全一致**。
