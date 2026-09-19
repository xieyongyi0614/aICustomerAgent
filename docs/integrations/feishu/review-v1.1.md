# 飞书接入审核与并发硬化（review v1.1）

> 审核对象：`app/api/v1/feishu.py` 及其调用链
> （`channels/feishu/{events,adapter,inbox,delivery,client}.py` → `application/observability.py` → `application/chat_pipeline.py`）
> 基线：`acceptance-report-v1.0.md`（FEISHU-001~006 已验收）
> 本次范围：**安全与健壮性修复 + 同一用户连发合并**；Web 路径（`/api/v1/chat/message`）不动
> 前置决策：目标部署形态按「预留多 worker / 多实例」设计（见 §5 硬前置）

---

## 1. 审核结论

入站链路的**骨架设计是对的**，v1.0 验收报告认定的架构结论（通道边界、身份隔离、管线复用、出站抽象、Autonomy 兼容、Web 零回归）仍然成立。但发现：

| 类别 | 数量 | 关键项 |
|---|---|---|
| P0 真实缺陷（安全 / 正确性） | 5 | 加密体重放窗口缺口、body 无上限、限流先于去重、事件循环被同步 DB 阻塞、修上一条会破坏同会话保序 |
| P1 健壮性 | 4 | 后台任务返回值与异常未观察、内存表无界增长且去重 O(n²)、429 语义与产品不一致 |
| P2 / 死代码 | 7 | 冗余外层 token 校验、死配置、2 个死字段、同值兜底文案等 |

**最需要先知道的三件事**：

1. **存在一个真实重放缺口**：加密来件不带签名头时，防重放的时间戳窗口被整段跳过。捕获一份密文、等去重 TTL（600s）过后重放，即被当作全新事件再跑一轮完整管线（真实 LLM 调用 + 落库 + 回复）。已修复。
2. **`_resolve_identity` 是同步 SQLAlchemy，直接跑在事件循环线程上**，且发生在会话锁之前。一次慢查询会卡住整个进程的所有请求。已改为线程下放——但**这同时打破了「同一用户连发保序」**，因为原保序靠的正是「同步阻塞恰好不让出事件循环」这一副作用。两者必须同批修，已同批修。
3. **去重 / 出站幂等 / 会话锁全是进程内状态**。在补齐「去重落库 + 跨进程会话锁」之前先开多 worker，会出现同一 `event_id` 被多个实例各处理一次、同一会话不再串行。这是硬前置，不能靠"预留"绕过（见 §5）。

---

## 2. 发现明细

### P0

#### F-01 加密体无签名头时，防重放时间戳窗口被一并跳过 → 密文可无限重放
- **位置**：`api/v1/feishu.py:42-55`（`if not encrypted or signature:`）+ `channels/feishu/events.py`（时间戳校验原在 `verify_signature` 内）
- **机制**：`encrypted=True` 且无 `X-Lark-Signature` 时**整段跳过 `verify_signature`**，而「请求时间戳新鲜度」（`feishu_signature_window_seconds=300`，唯一的防重放闸门）只在该函数内校验。加密来件因此仅靠「解密成功 + 内存去重」保护。
- **影响**：去重表 TTL = `feishu_dedupe_ttl_seconds=600`。捕获一份合法加密 body 后**等待 600s 重放，即被当作全新事件**，触发一轮完整管线。可长期重复，直接烧 LLM 成本。
- **修法**：把时间戳新鲜度从 `verify_signature` 拆为独立的 `verify_timestamp_freshness`；新增 `verify_encrypted_freshness(timestamp, payload)`，在「加密且无签名头」分支调用——优先请求头时间戳，**回落事件自带 `header.create_time`（毫秒）**，两者都不可得（如 URL 校验来件）时放行并记 warning。
- **取舍登记**：回落 `create_time` 比签名路径（校验的是*请求*时间）更严格——被飞书重投超过窗口的**旧消息**会被拒。窗口可通过 `FEISHU_SIGNATURE_WINDOW_SECONDS` 调整。

#### F-02 请求体无大小上限
- **位置**：`api/v1/feishu.py:24`（原 `raw = await request.body()`）
- **机制**：Starlette 全量读入内存；`main.py` 注册的中间件只对 `/api/v1/chat/message` 限流，无 body 上限。
- **影响**：公开 webhook 端点可被单个大 body 打内存。
- **修法**：新增 `feishu_max_body_bytes`（默认 262144）。`_read_body` 先校验 `Content-Length`，再**按块读取并累计**，超限即中断并返回 413（不把超大 body 读进内存）。

#### F-03 限流先于去重 → 重投消耗配额、正常消息被误 429
- **位置**：`api/v1/feishu.py:91-96`
- **机制**：`allow_rate` 无条件记账，而它排在 `accept_event` 之前；飞书在非 2xx 时会重投。
- **影响**：用户可能被自己的重投挤到 429，429 又触发飞书再重投 → 放大；配额被最终会被丢弃的事件白白消耗。
- **修法**：交换顺序（`accept_event` 前置）。去重无副作用，先做不误伤。

#### F-04 同步 DB 调用阻塞事件循环
- **位置**：`channels/feishu/adapter.py`（原 `_resolve_identity` 直接在协程内调用同步 `SessionLocal`）
- **影响**：所有并发用户的身份解析互相排队；一次慢查询会卡住整个进程的所有请求，包括 webhook 的快速 ack 与其它 API。
- **修法**：`await asyncio.to_thread(_resolve_identity, ...)`。

#### F-05 同会话「保序」是 F-04 的副作用 —— 修 F-04 会打破它
- **机制**：三条连发消息被 `create_task` 后，各自先**同步跑完** `_resolve_identity`（不让出事件循环），再依次 `await lock`，于是"到达锁的顺序"恰好等于"到达顺序"。`asyncio.Lock` 的 FIFO 只保证**等待者**顺序，不保证**到达锁**顺序。
- **影响**：F-04 一旦改为 `to_thread`，三个任务会在 `await` 处交错，用户连发"你好"→"在吗"可能被**反序处理**。
- **修法**：引入 `channels/feishu/inbox.py` 的 **per-session FIFO 批次链**——`offer()` 同步入缓冲（无 `await`），flush 时把批次压入该会话的 FIFO 队列，由**唯一**的 per-session worker 顺序消费。顺序由「入队顺序」显式决定，不再依赖调度巧合。

### P1

#### F-06 `spawn_background` 返回值被忽略
- **位置**：`api/v1/feishu.py`（原 `observability.spawn_background(...)` 丢弃返回值）
- **机制**：无可用 loop 时 `spawn_background` 会 `coro.close()` 并返回 `False`。
- **影响**：该情形下用户消息被**静默吞掉**（既无回复也无日志）。
- **修法**：检查返回值，`False` 时 `logger.error("feishu event dropped: no dispatchable event loop ...")`。

#### F-07 后台任务的异常不被观察
- **位置**：`application/observability.py`
- **机制**：`create_task` 后只挂 `background_tasks.discard` 回调，无异常回调；`run_coroutine_threadsafe` 返回的 future 未保存。
- **影响**：逃逸异常只在 GC 时以 `Task exception was never retrieved` 形式出现，排障困难。
- **修法**：新增 `_log_task_exception` / `_log_future_exception` done-callback。

#### F-08 内存表无界增长 + 去重 O(n²)
- **位置**：`events._seen_events`、`events._rate_windows`、`adapter._session_locks`、`delivery._delivered`
- **机制**：`accept_event` / `_already_delivered` 每次**全量扫描**整表剔除过期项（O(N)）；`_rate_windows` 的 key 永删；`_session_locks` 每见一个新用户永久留一个对象。
- **影响**：N 个事件 → 总开销 O(N²)；长期运行是内存与 CPU 双泄漏。
- **修法**：去重表与出站幂等表改 `OrderedDict`（插入序即时间序），从头部批量摘除，清理 O(过期数)；限流表加摊还 sweep（每 `RATE_SWEEP_EVERY=256` 次调用清理一次已过窗条目）；会话锁改为引用计数回收（`_session_refs` 归零且无人等待时移除）。

#### F-09 429 语义与产品不一致（**本次不改，登记**）
- 同一种"发太快"，adapter 层是**回兜底文案**（`FALLBACK_TEXTS["overloaded"]`），API 层是**HTTP 429**；429 会触发飞书重投 → 放大。
- 改 429→200 属产品行为变更，会破坏既有 e2e 断言。**保留现状，登记为待决取舍。**

### P2 / 死代码

| ID | 位置 | 结论与处置 |
|---|---|---|
| F-10 | `feishu.py` 外层 vs 内层 token 校验 | **冗余，已删**：`_verification_token` 读同一个 `payload`。未加密时 payload 不重新赋值 → 内外层读到同一 token，重复校验；加密时外层 body 只有 `{"encrypt":...}`，`outer_token` 恒为 `None`，该分支**永不触发**。内层校验是唯一有效点。 |
| F-11 | `feishu_max_concurrent_turns` | **死配置，本次已激活**（见 §4 A8）：原全仓零消费点，现由 `adapter._get_turn_gate()` 的进程内 `Semaphore` 消费；并在首次创建时校验「并发上限 ≤ DB 连接池容量（`db_pool_size + db_max_overflow`）」，超出记 warning。 |
| F-12 | `ParsedMessageEvent.app_id` / `.event_type` | **死字段，已删**：赋值后从未被读取（`event_type` 改用局部变量做过滤）。 |
| F-13 | `feishu.py` 的 `header` 预检 | **保留**：`parse_message_event` 已校验 header，此处仅把响应从 200 改成 400；删除会破坏 `test_missing_event_header_400`，且有排障价值。 |
| F-14 | `FALLBACK_TEXTS["identity_error"]` 与 `["pipeline_error"]` | **复核后修正结论**：两者文案相同但服务于**不同的 `error_kind`**（可观测性分类），合并会丢失分类。已提取共享常量 `_INTERNAL_ERROR_TEXT` 消除重复字面量，**保留两个 key**。 |
| F-15 | `verify_signature` 空 `encrypt_key` 静默降级 | FEISHU-002 的明确决策，非缺陷；但叠加 F-01 后空 key 部署下「零防重放」。F-01 的修法已覆盖（时间戳/`create_time` 校验独立于签名）。 |
| F-16 | `client.py` 的 `UrllibTransport` | 用 `urlopen` + `to_thread`，**无连接池**，每次回复/刷新都做完整 TLS 握手，并占用 asyncio 默认线程池。属「完整优化」，登记不实施。 |

---

## 3. 并发处理方法

### 3.1 多人同时使用机器人

| 层面 | 处理方式 | 本次状态 |
|---|---|---|
| 会话隔离 | `session_id = internal_user_id = feishu:{open_id}`，per-user 串行 | 保持（原已正确） |
| 全局并发上限 | 进程内 `asyncio.Semaphore(feishu_max_concurrent_turns)`，超限**排队等待**而非丢弃 | **已落地**（激活 F-11 死配置） |
| 任务扇出 | 闸门置于 adapter 层即可收敛，无需改 `observability` 的 fire-and-forget 语义 | 已落地 |
| DB 连接池 | 并发轮次上限必须 ≤ `db_pool_size + db_max_overflow`（默认 15），否则 `QueuePool` 超时 | 已加启动期一致性 warning |
| 事件循环 | 身份解析下放线程，不再阻塞 | 已落地（F-04） |
| 入站限流 | per-`open_id` 60s 滑窗；去重前置避免重投吃配额 | 已落地（F-03） |
| 多实例 | 去重/幂等/锁须外置 | **未落地，硬前置**（§5） |

### 3.2 同一用户连发多条消息 —— 采用「合并」

**目标语义**：短窗口内同一 `open_id` 的连续消息合并为一轮，按到达顺序拼接后送管线。

- **合并键**：`inbound.external_user_id`（= `open_id`）。`session_id = f"feishu:{open_id}"` 是冻结的一一映射，按 open_id 建桶可**避免入队前做一次 DB 身份解析**。
  ⚠️ **耦合登记**：若将来做「Web ↔ 飞书账号绑定」改变派生规则，合并键必须同步改。
- **窗口**：`feishu_merge_window_ms`（默认 800）。**固定窗口**——首条到达即起计时，窗口内新消息**不重置**，避免持续打字导致永不 flush。
- **上限**：`feishu_merge_max_messages`（默认 10）/ `feishu_merge_max_chars`（默认 20000，对齐 `InboundMessage.TEXT_MAX_CHARS`）；超限**立即 flush**。
- **合并产物**：文本用 `"\n"` 顺序拼接；`reply_ref` 取**最后一条**的 `message_id`（飞书 reply 锚定最后一条，语义正确）；`received_at` 取第一条；`metadata` 取最后一条。
- **顺序与串行**：per-session FIFO 批次链 + 唯一 worker（见 F-05）。同会话至多一个在飞轮次。
- **背压**：`feishu_session_queue_limit` 语义改为「排队批次数上限」；超出时 `offer()` 返回 `False`，由 `ingest_inbound_message` 回 `overloaded` 兜底文案。
- **降级开关**：`feishu_merge_window_ms = 0` 表示关闭合并（逐条处理，仍走链保证顺序），供灰度与测试使用。
- **多实例限制**：合并窗口**只在实例内生效**。多实例下同一 `open_id` 若落到不同 worker，连发消息不会被合并（顺序仍须由跨进程锁保证）。若要求跨实例合并，需 ingress 按 `open_id` 做 sticky 路由。

### 3.3 出站侧
`delivery` 的幂等键（Reply 用 `reply:{message_ref}:{index}`）设计正确，但同样**进程内**；多实例下同一逻辑消息可能重复投递 → 与去重表一并落库（§5）。

---

## 4. 本次实施记录

### 4.1 代码改动

| 文件 | 改动 |
|---|---|
| `app/api/v1/feishu.py` | 新增 `_read_body`（限长 + 分块读取）；加密无签名分支调用 `verify_encrypted_freshness`；删除冗余外层 token 校验；去重前置到限流之前；检查 `spawn_background` 返回值并记 error；派发入口改为 `adapter.ingest_inbound_message` |
| `app/channels/feishu/events.py` | 拆出 `verify_timestamp_freshness`；新增 `verify_event_freshness` / `verify_encrypted_freshness`；`_seen_events` 改 `OrderedDict` 头部批量摘除；`_rate_windows` 加摊还 sweep；删除 `ParsedMessageEvent.app_id` / `.event_type` |
| `app/channels/feishu/inbox.py` | **新增**：`SessionInbox`（固定窗口合并 + FIFO 批次链 + 队列背压 + `reset`） |
| `app/channels/feishu/adapter.py` | 新增 `ingest_inbound_message`（Webhook 入口）；`handle_inbound_message` 降为「跑一个批次」并保留 `TurnOutcome` 返回契约；`_resolve_identity` 改 `asyncio.to_thread`；锁在首个 `await` 前取得以保序；`_serialized` 引用计数回收会话锁；新增 `_get_turn_gate` 全局信号量；删除 `_session_load` / `_try_acquire_slot` / `_release_slot`（背压已由 inbox 承担）；`_INTERNAL_ERROR_TEXT` 常量消除重复字面量 |
| `app/channels/feishu/delivery.py` | `_delivered` 改 `OrderedDict` 头部批量摘除 |
| `app/application/observability.py` | `spawn_background` 挂 `_log_task_exception` / `_log_future_exception` |
| `app/core/settings/feishu.py` | 新增 `feishu_max_body_bytes` / `feishu_merge_window_ms` / `feishu_merge_max_messages` / `feishu_merge_max_chars`；`feishu_merge_window_ms` 允许 0（单独校验 `>= 0`） |
| `.env.example` | 补 4 个新配置项占位 |

### 4.2 设计偏差登记（相对批准计划）

| 偏差 | 原因 |
|---|---|
| 计划原文为「`handle_inbound_message` 降为入口 → `inbox.offer`」，实际新增 `ingest_inbound_message` 作为入口、`handle_inbound_message` 保留为批次执行者 | 若把入口语义塞进 `handle_inbound_message`，其 `TurnOutcome` 返回契约将无法维持（入队后立即返回，拿不到轮次结果），会导致 20+ 处 adapter 单测/集成用例被迫改写。拆成两个名字后，既有测试的**行为断言逐字保留**，只在 e2e 夹具把 monkeypatch 点从 `handle_inbound_message` 改为 `ingest_inbound_message`（2 处）。计划意图（Webhook → 合并 → 批次）完全保留。 |
| 计划 §2.2 的「FIFO 批次链」实现为「FIFO 队列 + 唯一 worker」而非「`await prev` 任务链」 | `await prev` 链会使同会话批次全部堆积在链上而不进入 `_session_load`，导致 `feishu_session_queue_limit` 背压路径**静默失效**。队列 + 唯一 worker 同时满足顺序、串行与「可计数的排队深度」。 |
| F-14 由「合并为单一 key」改为「提取共享常量、保留两个 key」 | 复核后确认两个 key 服务于不同的 `error_kind` 分类，合并会丢失可观测性分类。 |
| F-13 由「标注」明确为「保留」 | 删除会破坏既有断言 `test_missing_event_header_400`。 |

### 4.3 测试

**新增**：`tests/unit/test_feishu_inbox.py`（9 例：合并顺序、固定窗口、零窗口、两个上限、队列背压与恢复、会话隔离、reset 取消定时器、handler 异常不阻塞队列）；`tests/unit/test_observability_spawn_background.py`（5 例：无 loop 关闭协程、任务保留与释放、异常留痕、跨线程投递及其异常留痕）。
**扩充**：`test_feishu_events.py`（新鲜度边界、`create_time` 回落、去重表有界、限流表回收、去重不吃配额）；`test_feishu_webhook.py`（加密无签名 + 新鲜 `create_time` → 200；重放/过期时间戳 → 403；超长 body → 413；重复事件不吃配额；派发失败留痕）；`test_feishu_settings.py`（新字段默认值/环境覆盖/正数校验/`merge_window_ms` 边界）。
**改写**：`test_feishu_adapter_turn.py` / `test_feishu_cases.py` / `test_feishu_adapter_stream.py` / `test_feishu_error_matrix.py` 中依赖 `_session_load` 与旧 overload 路径的 5 个用例 → 改为驱动 `ingest_inbound_message` 并断言「拒绝 + 兜底文案 + 不调管线 + 恢复后按序处理」。

**结果**（`apps/backend`，`-p no:xdist -o addopts=""`，单进程）：

```text
飞书全量（unit + integration + e2e + channel_identity）：405 passed, 3 failed
```

3 条失败均为**存量/环境问题，非本次回归**（已逐条定位）：

1. `test_feishu_settings.py::test_feishu_defaults`、`::test_feishu_secret_values_only_nonempty` —— `apps/backend/.env` 已存在且含真实凭据，`FeishuSettings()` 会读取它。已实测证明：在无 `.env` 的 CWD 下 `app_id == ''`、`secret_values() == ()`。**修复建议**：这两个"默认值"用例应显式构造 `FeishuSettings(_env_file=None)`。
2. `test_channel_identity.py::test_orm_metadata_matches_migration_columns` —— `action_records` 表 ORM 与迁移列漂移（缺 `run_id` / `priority`）。已用 worktree 在 `d6a1635`（改动前）复现同样失败，**确认非本次引入**。

另：`test_feishu_isolation.py::test_two_users_six_resources_isolated` 在一次组合运行中失败、单独与复跑均通过，属既有测试基建的**顺序敏感**问题（根因与下条同源）。

---

## 5. 遗留项与硬前置

### 5.1 多实例硬前置（FEISHU-007）

**在补齐以下两项之前，不得开启多 worker / 多实例：**

1. **去重落库**：新增 `feishu_events` 表（`event_id` 唯一约束）+ 迁移 `0044`（当前链尾 `0043`），`accept_event` 改为 DB insert + `IntegrityError` 判定。
2. **跨进程会话串行**：PG advisory lock（`pg_try_advisory_lock(hashtext(session_id))`）或会话行 `SELECT ... FOR UPDATE`。

否则：同一 `event_id` 会被多个实例各处理一次（重复 LLM 调用 + 重复回复）；同一会话不再串行。出站幂等（`delivery._delivered`）同理。

⚠️ 实施注意：新增仓储必须注册进 `tests/conftest.py::_REPO_MODULES`（含文件顶部 import），否则测试会绕过内存库补丁、连真实 PG 而挂起。

### 5.2 其他登记项

| 项 | 内容 |
|---|---|
| F-09 | 429 → 200 语义统一（含用户可见的限流提示） |
| F-16 | `httpx.AsyncClient` 单例 + 连接池替换 `urllib`（消除每请求 TLS 握手与线程池争用） |
| 流式回复 | 当前整段缓冲后一次发出；可考虑打字机/分段增量 |
| 合并窗口跨实例 | 需 ingress 按 `open_id` sticky 路由 |
| `migrations/env.py` | `fileConfig(..., disable_existing_loggers=True)` 会禁用进程内全部已存在 logger，波及任何「进程内迁移 + 日志断言」组合；建议改 `disable_existing_loggers=False` |
| Web 路径 | `/api/v1/chat/message` 无 per-user 串行、共用 `default_user`，存在同类并发缺陷（本次按决策不动） |
