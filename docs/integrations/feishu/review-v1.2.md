# 飞书渠道深度审查（review v1.2）—— 去重、时钟与限流正确性

> 审核对象：`app/api/v1/feishu.py`、`app/channels/feishu/{events,delivery,adapter,inbox}.py`
> 基线：`review-v1.1.md`（F-01~F-16 已修复或登记）、`acceptance-report-v1.0.md`
> 本次范围：**对「进程内状态 / 时钟依赖 / 去重表实现」三类问题的复核 + 全链路补充审查**
> 方法：静态审查 + e2e 探针实测（探针文件用后即删，未进仓库）
> 结论：**新增 10 项发现，其中 2 项 P0 真实缺陷**；原 v1.1 的两处「已修复」经复核仍留有缺口

---

## 1. 结论摘要

### 1.1 对你提出的三点判断的裁决

| # | 你的判断 | 裁决 | 说明 |
|---|---|---|---|
| 1 | `_seen_events` 单机局限，多实例各自去重 → 同一事件被接受 N 次 | **成立** | 但范围被低估：进程内状态共 **5 处**，换 Redis 只解决 1 处。方案本身有 4 个坑（见 §2.1） |
| 2 | `next(iter(_seen_events))` + while 逐个删，极端情况拖慢单次调用 | **不成立** | `next(iter(od))` 是 O(1)，清理摊还 O(1)；`OrderedDict` 本身即「dict + deque」的合体。改成 deque+dict 复杂度不变、内存翻倍（见 §2.2） |
| 3 | `_now()` 依赖系统时钟，回拨导致 TTL 判断异常 | **成立，且影响面比去重更大** | 同一 `_now` 还驱动限流窗口与新鲜度校验；后者的失效模式是**整个 webhook 停摆**（见 §2.3） |

### 1.2 本次新发现

| ID | 级别 | 位置 | 一句话 |
|---|---|---|---|
| N-01 | **P0** | `api/v1/feishu.py:96-101` | 限流 429 后飞书重投被去重表静默吞掉 → **消息永久丢失且无留痕** |
| N-02 | **P0** | `api/v1/feishu.py:37-49` + `events.py:90-95` | 明文 + 空 `FEISHU_ENCRYPT_KEY` 时**完全无防重放**（v1.1 F-01 的修复未覆盖该路径） |
| N-03 | P1 | `delivery.py:117-136,164-178` | 出站幂等「检查-后-动作」非原子 → 并发下重复投递（实测 2 次） |
| N-04 | P2 | `events.py:160-166` | 超长时间戳头 → 未捕获 `OverflowError` → 500（实测） |
| N-05 | P1 | `adapter.py:323-337` | 并发闸门是进程内的，多实例下「≤ DB 连接池」校验失效 |
| N-06 | P2 | `api/v1/feishu.py:71-80` | 加密体缺内层 token 时 token 校验被整段跳过 |
| N-07 | P2 | `events.py:74-80` | 配置缺失与鉴权失败不可区分（都记 401 + 「mismatch」） |
| N-08 | P2 | `events.py:219-226` | 非文本 / 空白消息静默丢弃 → 机器人表现为「没反应」 |
| N-09 | P2 | `events.py:326` | 限流阈值与 Web 路径共用 `chat_rate_limit_per_minute`，但失败后果不同 |
| N-10 | P2 | `delivery.py:165,178` | 出站幂等 TTL 复用入站去重 TTL，且无时钟注入点 |

**最需要先知道的两件事**：

1. **`review-v1.1` 的 F-03 修复引入了一个新缺陷**。F-03 把去重提到限流之前（「重投不得消耗配额」），方向没错；但叠加 F-09（429 会触发飞书重投）后产生新语义：**被限流的那条消息，其重投会命中去重表 → 返回 200 → 既不处理也不回复**。用户消息静默消失，日志里只有一条 429 warning。已实测复现（§3.1）。
2. **`review-v1.1` 的 F-01 修复有路径遗漏**。F-01 修的是「加密体无签名头 → 防重放窗口被跳过」，修法是新增 `verify_encrypted_freshness` 并在加密分支调用。但**明文路径的新鲜度校验原本就只挂在 `verify_signature` 内部**，而该函数在 `encrypt_key` 为空时直接 `return`。于是「明文 + 空 key」组合下新鲜度检查一次都不执行，重放窗口完全敞开。已实测复现（§3.2）。

---

## 2. 对三点判断的逐条裁决

### 2.1 判断 1：多实例去重 —— 成立，但方案建议修正

**确认部分**：`events._seen_events` 是模块级 `OrderedDict` + `threading.Lock`，纯进程内。3 个实例 = 3 份独立去重表，同一 `event_id` 会被 3 个实例各接受一次（重复 LLM 调用 + 重复回复）。这一点在 `review-v1.1` §5.1 已登记为「多实例硬前置」。

**范围被低估**：进程内状态不止去重表，共 5 处：

| 状态 | 位置 | 多实例后果 |
|---|---|---|
| `_seen_events` | `events.py:38` | 同一事件被 N 个实例各处理一次 |
| `_delivered` | `delivery.py:28` | 同一逻辑回复被重复投递 |
| `_session_locks` / `_session_refs` | `adapter.py:52-53` | 同一会话不再串行（并发写同一会话） |
| `_turn_semaphore` | `adapter.py:54` | 全局并发上限变成 N × limit（见 N-05） |
| `inbox._sessions` | `inbox.py:42` | 连发合并窗口失效、批次链断裂 |

所以「换成 Redis 去重」只解决 1/5。

**你提的 Redis `SETNX + EXPIRE` 方案本身的 4 个坑**：

1. **两条命令不是原子的**。`SETNX` 成功后进程被 kill / Redis 抖动，`EXPIRE` 未执行 → 该 key **永久无 TTL** → 该 `event_id` 永远被视为「已处理」→ 对应消息永久丢失。必须用单命令 `SET key val NX EX <ttl>`（Redis ≥ 2.6.12）或 Lua 脚本。这是该方案最常见的落地事故。
2. **Redis 默认不持久**。未开 AOF 时一次重启就清空去重表 → 攻击者只要等（或促成）一次 Redis 重启，就能重放此前捕获的全部事件。去重表承载的是**安全语义**，建议落在有 WAL 的存储上。
3. **淘汰策略会静默失效**。若 Redis 配了 `maxmemory-policy allkeys-lru`，去重键可能被驱逐 → 重放窗口无声重开。要么独立实例 + `noeviction`，要么显式接受该风险。
4. **失败语义必须先定义**。Redis 不可用时：去重应 **fail-open**（放行，代价是重复 LLM 调用）还是 **fail-closed**（拒绝，代价是丢消息）？限流则应相反（fail-closed 以保护 LLM）。不定清楚，Redis 抖动就是一次事故。

**推荐选型**：

| 维度 | Redis `SET NX EX` | PG 唯一约束 |
|---|---|---|
| 新基础设施 | 需引入（当前栈只有 PG） | 无 |
| 原子性 | 需单命令 / Lua | `INSERT ... ON CONFLICT DO NOTHING` 天然原子 |
| 持久性 | 默认不持久，重启丢表 → 重放窗口重开 | WAL 持久 |
| 淘汰风险 | LRU 可静默驱逐 | 无 |
| 可覆盖范围 | 去重 + 限流 + 会话锁 + 合并窗口（4 项） | 去重 + 会话锁（2 项） |
| 性能 | 微秒级 | 单次往返 + 写 WAL |

- **只解决去重** → 用 PG。`feishu_dedupe_ledger(event_id PK)` + `INSERT ... ON CONFLICT DO NOTHING` 返回 rowcount 判定，与 `review-v1.1` §5.1 的既有方案一致（迁移 `0044`，链尾需对齐当前 `0049`），且复用已有依赖、不引入新运维面。
- **要做全套（跨实例限流 + 跨实例合并 + 跨实例会话锁）** → Redis 才有独立价值；即便如此，**去重仍建议留 PG**（因为需要 durable）。
- 跨实例会话串行：PG advisory lock（`pg_try_advisory_lock(hashtext(session_id))`）或会话行 `SELECT ... FOR UPDATE`。
- 实施提醒：新增仓储必须注册进 `tests/conftest.py` 的 `_REPO_MODULES` / `_SERVICE_DB_MODULES`（含顶部 import），否则测试会绕过内存库补丁、连真实 PG 而挂起。

### 2.2 判断 2：OrderedDict 遍历效率 —— 不成立，不建议改

**先纠正两个前提**：

1. `next(iter(od))` 取首元素是 **O(1)**，不是 O(N) 扫描 —— 这点你的描述是对的。
2. `OrderedDict` 的内部实现**就是**「哈希表 + 双向链表」，即你提出的「dict + deque」的合体。改成两个独立容器不是优化，是**退化**：同一份数据存两处、需手工维护一致性（删除时两边同步）、内存接近翻倍，还失去 `popitem(last=False)` 的单次原子操作。

**「while 逐个删除拖慢单次调用」的摊还分析**：每个条目一生只被 `del` 一次，因此 N 次 `accept_event` 调用的总删除次数 ≤ N，**摊还 O(1)/次**。某一次调用可能删除 k 个过期条目（O(k)），但那 k 个条目在此之前从未被记过账。这是标准的摊还记账，不是最坏情况的性能问题。且过期项必然连续位于头部（插入序 = 时间序），循环不会「跳过未过期项再回头」，不存在退化场景。

**真正值得改的两点**（都不是性能）：

1. 用 `popitem(last=False)` 替代 `next(iter(...))` + `del` —— 更短、语义更明确，性能差异可忽略。
2. **加容量上界**（如 `feishu_dedupe_max_entries`）。这不是为性能，而是为 §2.3 的时钟回拨提供硬边界：当前表大小只受「流量 × TTL」约束，**没有任何上界**；一旦时钟回拨导致永不淘汰，表只增不减。

### 2.3 判断 3：时钟依赖 —— 成立，且影响面大于去重

**确认**：`events.py:36` 的 `_now = time.time` 是 wall clock。`time.time()` 会**回拨**：NTP step 校正、手动改钟、VM 快照恢复、容器宿主迁移、闰秒处理差异。Python 有 `time.monotonic()`，但**同一份 `_now` 被三个语义完全不同的地方消费**，各自的失效模式不同：

| 消费点 | 回拨 | 前拨 |
|---|---|---|
| 去重 TTL（`accept_event`） | `now - t` 变负 → 头部判据恒真 → **不淘汰任何条目**，表只增不减（去重窗口被动延长至无限） | 全部条目瞬间过期 → **去重窗口塌缩，重放窗口打开** |
| 限流窗口（`allow_rate`） | `now - window[0] > 60` 恒假 → 窗口永不排空 → **该用户被永久 429** | 窗口瞬间排空 → **限流被绕过** |
| 新鲜度（`_assert_within_window`） | 见下 | 见下 |

**第三个消费点最危险，且与去重无关**：`_assert_within_window` 用 `abs(_now() - value) > window` 判断。`abs` 让快慢对称，所以**只要服务器时钟与飞书相差超过 `feishu_signature_window_seconds`（默认 300s），无论快还是慢，所有事件一律 403** —— 这是一次完整的 webhook 停摆，而日志只会输出 `request timestamp out of window`，运维很难第一眼联想到 NTP。建议：

- 把偏差量记进日志（`skew=%.1fs`），并区分「落后」与「超前」的措辞；
- 启动期做一次时钟健康检查或在首个 403 时打印明确提示。

**修法**：**时长判断用单调钟，绝对时间比较才用 wall clock**。

- `accept_event` 的 TTL 与 `allow_rate` 的滑窗 → 改 `time.monotonic()`；
- `_assert_within_window` → 保留 wall clock（需与飞书外部时间戳比较），但显式记录偏差；
- 保留可注入钩子：`events._now` 当前被测试 monkeypatch（`test_accept_event_ttl_expiry_with_injected_clock` 等至少 4 个用例），拆分成 `_now` / `_mono` 两个钩子时须同步改测试，否则会连带打挂这批用例。

---

## 3. 新发现明细（含实测证据）

### 3.1 N-01（P0）限流 429 后重投被去重静默吞掉 → 消息永久丢失

**位置**：`api/v1/feishu.py:96-101`

```python
if not events.accept_event(parsed.event_id):   # 先落账并返回 True
    return JSONResponse(content={})
if not events.allow_rate(parsed.open_id):      # 再判限流
    return _reject(429, "too many requests")
```

**机制**：`accept_event` 已把 `event_id` 写入 `_seen_events` 并返回 `True`；紧接着 `allow_rate` 返回 `False` → 429。飞书在非 2xx 时**重投同一个 `event_id`**（v1.1 F-09 已确认此行为），此时 `accept_event` 返回 `False` → 返回 200 `{}`。**既不派发管线，也不回复用户，且没有任何错误留痕**（只有最初那条 429 warning）。

**实测**（e2e，`chat_rate_limit_per_minute=1`）：

```text
第 1 条 event_id=evt-rl-1 → 200
第 2 条 event_id=evt-rl-2 → 429
第 2 条重投（同 evt-rl-2）→ 200，dispatched 总数 = 1
```

即 3 次请求只派发 1 条，第 2 条消息**永久丢失**。用户在快速连发时会被静默吞掉消息。

**这是 v1.1 F-03 引入的新缺陷**：F-03（去重前置）与 F-09（429 触发重投）单看都合理，叠加后才出问题。

**修法 A（推荐）**：限流命中时**不返回 429**，改为把 `InboundMessage` 交给 adapter 的「仅回兜底文案」路径（复用 `FALLBACK_TEXTS["overloaded"]` 与 `_deliver_outcome`，不跑管线），仍返回 200。收益：消息不丢、用户有感知（收到「你发得太快了」）、飞书不重投（消除放大），并顺带落地 v1.1 登记未做的 F-09。代价：需同批改写约 4 处 429 断言（`test_feishu_error_matrix.py:330`、`test_feishu_webhook.py:375-381`、`471-478`）。

**修法 B（不推荐）**：`accept_event` 改为「先探测、限流通过后再落账」。会重新引入 F-03（重投吃配额），需配「限流只对未在去重表中的事件记账」的复杂判定。

### 3.2 N-02（P0）明文 + 空 `FEISHU_ENCRYPT_KEY` 时完全没有防重放

**位置**：`api/v1/feishu.py:37-49` + `events.py:90-95`

**机制**：`verify_signature` 在 `encrypt_key` 为空时直接 `return`（v1.1 F-15 登记的既有决策）：

```python
if not encrypt_key:
    if not signature:
        logger.warning("FEISHU_ENCRYPT_KEY 为空: 无法校验请求签名，安全性降级")
    return        # ← 提前返回，时间戳新鲜度校验一并被跳过
```

而新鲜度校验原本**只在该函数内部**调用；v1.1 F-01 新增的 `verify_encrypted_freshness` 又**只在 `encrypted` 分支**调用。于是：**明文来件 + 空 `encrypt_key` ⇒ 新鲜度检查一次都不执行**。

**实测**（e2e，`feishu_encrypt_key=""`，即 e2e 夹具的默认配置）：

```text
PROBE1  时间戳头 = now - 100000s（约 27 小时前）→ 200，且成功派发
PROBE2  同一 body，去重 TTL(600s) 过期后重放 → 200，第二次仍派发（dispatched = 2）
```

**影响**：捕获一份合法明文 body，等 600s，即可**无限重放**，每次都跑完整管线（真实 LLM 调用 + 落库 + 回复）。这正是 v1.1 F-01 声称已修复的「可无限重放」，只是换到了明文路径上仍然存在。

**关键事实**：空 `encrypt_key` 是**被支持的部署形态**，不是异常配置 ——

- `settings/feishu.py:27-29` 的 `_REQUIRED_CREDENTIALS` 只有 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_VERIFICATION_TOKEN`，`encrypt_key` 缺失**仅记 warning**（`feishu.py:91-94`）；
- `tests/e2e/test_feishu_webhook.py` 的 `APP_SETTINGS` 用的就是 `feishu_encrypt_key: ""`。

也就是说，**当前 e2e 主配置正是这个有洞的配置**，而测试没有覆盖「明文 + 旧时间戳」这一组合。

**附带的严重性**：该配置下 verification token 是唯一凭据。它既不提供重放保护，也**不绑定来源身份** —— 任何人拿到该静态 token 就能以**任意 `open_id`** 伪造消息（冒充用户、烧 LLM 额度、污染记忆与库表）。且 `verify_token` 在 token 未配置时抛的是 `FeishuAuthError`（见 N-07），使「没配 token」与「token 被攻击」在日志上不可区分。

**修法**：把新鲜度校验从签名分支中解耦出来，对**所有**请求统一执行。明文路径优先请求头时间戳，回落顶层 `header.create_time`（明文 payload 的 header 就在顶层，可直接读）：

```python
# 明文：verify_signature 空 key 早退后，仍须独立校验新鲜度
if not encrypted:
    events.verify_encrypted_freshness(
        request.headers.get("x-lark-request-timestamp"), payload
    )
```

### 3.3 N-03（P1）出站幂等「检查-后-动作」非原子 → 重复投递

**位置**：`delivery.py:117-136`（调用点）、`164-178`（实现）

**机制**：`_already_delivered(key)` 与 `_mark_delivered(key)` 是**两次独立加锁**，中间夹着 `await client.reply_message(...)`（会让出事件循环）。两个并发调用者可以同时看到 `False`，各自发送一次。

**实测**：把 `client.reply_message` 换成会 `await asyncio.sleep(0)` 的桩，`asyncio.gather` 两个同 key 调用：

```python
await asyncio.gather(
    delivery._send_reply_parts("om_race", ["hello"]),
    delivery._send_reply_parts("om_race", ["hello"]),
)
# 不 sleep 时：duplicate sends = 1（顺序执行，碰不到）
# 加 sleep(0) 后：duplicate sends = 2  ← 幂等失效
```

**可达性**：单实例下 reply 路径被 per-session 锁串行化，所以平时碰不到；但 `send_proactive`（Autonomy 主动消息，共用同一个 `_delivered` 表）**没有这层串行**，多实例下两条路径都会命中。

**修法**：改为 `_claim(key) -> bool`，在**单次加锁内**完成「查 + 占位」，发送失败时 `_release(key)` 回滚。这也是把出站幂等搬去 PG 时天然要改成的形状（`INSERT ... ON CONFLICT` 的 rowcount 判定）。

### 3.4 N-04（P2）超长 `X-Lark-Request-Timestamp` → 未捕获 `OverflowError` → 500

**位置**：`events.py:160-166`

```python
def _timestamp_value(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        return float(int(timestamp))       # ← 只捕获 ValueError
    except ValueError:
        return None
```

`int("9" * 400)` 在 Python 里**能成功**（大整数无上限），但 `float(...)` 抛 `OverflowError`，未被捕获。

**实测**（加密体 + 无签名头 + 400 位时间戳头）：

```text
OverflowError: int too large to convert to float
  app/api/v1/feishu.py:64  → events.verify_encrypted_freshness
  app/channels/feishu/events.py:106 → verify_timestamp_freshness
  app/channels/feishu/events.py:164 → _timestamp_value
```

**可达性**：需要一份可解密的密文（捕获或持有 encrypt_key）；该分支的时间戳头**未经签名保护**。单次 500，非进程崩溃，但属「外部输入直达未捕获异常」。`main.py` 无兜底 `exception_handler`（grep 无命中），只能落到 Starlette 默认 500。

**修法**：`except (ValueError, OverflowError)`，并对时间戳长度加上界（如 > 20 位直接判无效）。

### 3.5 N-05（P1）并发闸门是进程内的，多实例下「≤ DB 连接池」校验失效

**位置**：`adapter.py:323-337`

```python
_turn_semaphore = asyncio.Semaphore(limit)          # 进程内
if limit > capacity:                                 # capacity = db_pool_size + db_max_overflow
    logger.warning(...)
```

`asyncio.Semaphore` 只在单进程生效。v1.1 §3.1 A8 的「并发上限必须 ≤ `db_pool_size + db_max_overflow`（默认 15）」**只在单实例成立**：3 个实例各配 4 → 聚合 12 个并发轮次，但每个实例都只看自己的 `4 ≤ 15`，**warning 不会触发**；而 DB 侧是共享的 15 连接。4 个实例就足以压满连接池触发 `QueuePool` 超时。

**修法**：要么把校验改成「`limit × 实例数 ≤ pool`」（需要实例数可配），要么在文档中明确标注「仅单实例有效」。跨实例并发闸门通常用 PG advisory lock 计数或 Redis 信号量，属多实例前置的一部分。

### 3.6 N-06（P2）加密体缺内层 token 时，token 校验被整段跳过

**位置**：`api/v1/feishu.py:71-80`

```python
inner_token = _verification_token(payload)
if inner_token is not None:
    ... 校验 ...
elif not encrypted:            # ← 加密且无 token 时，两个分支都不命中
    return _reject(401, ...)
```

加密来件若解密后不含 `token` 字段，**放行**。实际飞书事件必带 `header.token`，且伪造者需持有 `encrypt_key`（否则密文无法构造/篡改），故现实中不可达 —— 属加固项：加密体也应要求 token 存在。

### 3.7 N-07（P2）配置缺失与鉴权失败不可区分

**位置**：`events.py:74-80`

`verify_token` 在 `expected` 为空时抛 `FeishuAuthError("verification token mismatch")`，路由记 warning 后返回 401。运维看到的是「token 不匹配」，但真实原因是**根本没配 token**。建议改为 `FeishuConfigError`（`errors.py` 已有该类型）+ `logger.error`，与真实攻击区分开。

### 3.8 N-08（P2）非文本 / 空白消息静默丢弃 → 机器人表现为「没反应」

**位置**：`events.py:219-226`

以下情形一律返回 200 `{}`，不派发、不回复：

- `message_type != "text"`：表情、图片、语音、文件、富文本卡片；
- `chat_type != "p2p"`：群聊（**这是 FEISHU-002 的明确设计**，保留）；
- `text` 为空或纯空白（`_extract_text` 返回 `None`）。

群聊忽略是明确设计，但「非文本私聊消息完全不回」更像产品缺口 —— 用户侧观感是机器人死了。建议至少回一句「我目前只能读文字哦」。属产品决策，登记。

### 3.9 N-09（P2）限流阈值与 Web 路径共用 `chat_rate_limit_per_minute`

`events.allow_rate` 用 `chat_rate_limit_per_minute`（默认 30），`api/rate_limit.py` 也用它（按客户端 IP）。这是 FEISHU-002 的明确决策（「不新增配置键，避免与 001 冻结的配置集冲突」），但两者语义不同：Web 是 **per-IP**、飞书是 **per-open_id**；且**失败后果不同** —— 飞书 429 会触发 N-01 的消息丢失。建议后续拆出 `feishu_rate_limit_per_minute`。

### 3.10 N-10（P2）出站幂等 TTL 复用入站去重 TTL，且无时钟注入点

`delivery._already_delivered` 用 `feishu_dedupe_ttl_seconds`（600s）作为出站幂等窗口。两者语义不同：入站去重防的是「同一事件被处理两次」，出站幂等防的是「同一逻辑消息被投递两次」，而主动消息的重试/补发间隔可能远超 600s，窗口偏短。另外 `delivery` 直接调 `time.time()`（`delivery.py:166,178`），没有 `events._now` 那样的注入点，**测试无法冻结出站时钟** —— `test_feishu_webhook` 里靠 monkeypatch `events._now` 的用例覆盖不到出站路径。建议独立配置键 + 统一时钟钩子。

---

## 4. 已复核为「无问题」的部分（避免重复排查）

以下项本次逐一核对，结论是**不需要改动**：

- **解密实现**：`base64.b64decode(validate=True)` + 长度校验（`len(raw) >= 32` 且 `(len-16) % 16 == 0`）+ PKCS#7 严格校验（含 pad 值范围与重复字节一致性）；所有失败统一抛 `FeishuConfigError` → 400，**不返回区分性错误信息**，无 padding oracle 面。
- **验签比较**：`verify_token` 与 `verify_signature` 均用 `hmac.compare_digest` → 无时序侧信道。
- **body 限长**（v1.1 F-02）：`_read_body` 先看 `Content-Length` 再分块累计，超限即中断 → 不把超大 body 读进内存。
- **去重前置方向**（v1.1 F-03）：方向正确（重投不应消耗配额），只是与 429 组合出 N-01，问题在 429 语义而非顺序。
- **`spawn_background` 返回值检查**（F-06）与**后台异常留痕**（F-07）：已落地。
- **去重表头部批量摘除**（F-08）：摊还复杂度正确，方向无误（见 §2.2）。
- **`_rate_windows` 摊还 sweep**：每 256 次调用回收已过窗条目，避免 key 永久驻留，实现正确。
- **`feishu_enabled=false` 返回 404**：不泄露端点存在性，正确。
- **空 `encrypt_key` + 加密体**：`decrypt_bytes` 会抛 `FeishuConfigError` → 400，不会静默接受未验真的密文。安全（该配置只接受明文，问题在 N-02）。

---

## 5. 建议动作与优先级

| 优先级 | 项 | 建议 |
|---|---|---|
| **P0，建议本次就修** | N-01 | 限流 429 → 200 + `FALLBACK_TEXTS["overloaded"]`（顺带落地 F-09）。需同批改写 4 处 429 断言 |
| **P0，建议本次就修** | N-02 | 明文路径补 `verify_encrypted_freshness`（约 3 行）。补「明文 + 旧时间戳 → 403」用例 |
| P1，建议本次就修 | N-04 | `except (ValueError, OverflowError)` + 时间戳长度上界（2 行） |
| P1，建议本次就修 | N-03 | `_already_delivered` / `_mark_delivered` 合并为原子 `_claim` / `_release` |
| P1，登记 | N-05 | 并发闸门多实例失效：改校验语义或标注「仅单实例有效」 |
| P2，登记 | N-06 / N-07 / N-08 / N-09 / N-10 | 加固与配置解耦，可并入下一批 |
| 独立立项 | 判断 1（多实例） | 按 §2.1 选型；**在补齐前不得开多 worker**（v1.1 §5.1 硬前置） |
| 独立立项 | 判断 3（时钟） | 时长判断改 `time.monotonic()`；新鲜度校验记录 skew |

**实施注意**：

1. 改动前先取**测试基线**（HEAD 非全绿：约 21 failed / 6485 passed，既有失败集中在 `tests/v24` 迁移链头、frozen source 哈希、`no_new_tables` 三类）。验证自身改动时先备份文件 → `git checkout --` 还原 → 跑测试 → `cp` 回改动，避免把既存失败误判为自己引入。
2. 本仓库**禁用 `git rm`**（曾导致整个 `app/` 目录被删）。删文件用 `find <file> -delete`，操作后 `find <dir> -type f | wc -l` 复核。
3. `git commit` 在本机**无法更新分支 ref**，提交后须手动写 `.git/refs/heads/<branch>`（从 `.git/logs/HEAD` 取 hash）。

---

## 6. 复现方法

本节所述 P0/P1 结论均由 e2e 探针实测确认，探针文件用后即删（未进仓库）。复现要点：

**N-01**（需 `chat_rate_limit_per_minute=1`）：

```python
r1 = await post_event(override_settings, payload=event_payload(event_id="evt-rl-1"))  # 200
r2 = await post_event(override_settings, payload=event_payload(event_id="evt-rl-2"))  # 429
r3 = await post_event(override_settings, payload=event_payload(event_id="evt-rl-2"))  # 200，但不再派发
# 断言：len(dispatch_spy) == 1（3 次请求仅派发 1 条）
```

**N-02**（`feishu_encrypt_key=""`）：

```python
# ① 明文 + 27 小时前的时间戳头 → 实测 200 且派发（预期 403）
stale = str(int(time.time()) - 100000)
await post_event(override_settings, payload=event_payload(),
                 headers={"X-Lark-Request-Timestamp": stale})

# ② 同一 body，注入时钟跨过 TTL 后重放 → 实测两次都派发（预期第二次 403 或去重拦截）
monkeypatch.setattr(events, "_now", lambda: base)
await post_event(override_settings, raw=body)
monkeypatch.setattr(events, "_now", lambda: base + 601)
await post_event(override_settings, raw=body)
```

**N-03**：

```python
# 把 client.reply_message 换成 await asyncio.sleep(0) 的桩
await asyncio.gather(
    delivery._send_reply_parts("om_race", ["hello"]),
    delivery._send_reply_parts("om_race", ["hello"]),
)
# 断言：发送次数 == 1；实测 == 2
```

**N-04**：加密体 + 无签名头 + `X-Lark-Request-Timestamp: "9" * 400` → 实测抛 `OverflowError`。

**运行方式**（单进程，避免 xdist 干扰时钟注入用例）：

```bash
cd apps/backend
./.venv/Scripts/python.exe -m pytest tests/e2e/<probe>.py -p no:xdist -o addopts="" -s -q
```

---

## 7. 修复实施记录（2026-09-20）

已按 §5 的 P0/P1 清单实施修复：**N-01 / N-02 / N-03 / N-04 + 时钟分离（判断 3）**。
N-05~N-10 与多实例前置（判断 1）**本次未动**，仍为登记项。

### 7.1 代码改动

| 文件 | 改动 |
|---|---|
| `app/api/v1/feishu.py` | 新鲜度闸门从「仅加密分支」提升为**全路径统一**：以 `freshness_covered_by_signature = bool(encrypt_key and signature)` 判断签名路径是否已覆盖，未覆盖则独立调用 `verify_encrypted_freshness`（N-02）；限流命中改为 `200` + 派发 `adapter.reject_inbound_message`（N-01） |
| `app/channels/feishu/events.py` | 时钟职责分离：新增 `_mono = time.monotonic`，去重 TTL 与限流滑窗改用它，`_now` 只保留给新鲜度比对（判断 3）；`_assert_within_window` 记录 `skew`（判断 3）；`_timestamp_value` 加 `TIMESTAMP_MAX_ABS` 上界，杜绝 `float(int(...))` 溢出（N-04）；去重表淘汰改 `popitem(last=False)` 并抽出 `_evict_seen` |
| `app/channels/feishu/delivery.py` | `_already_delivered` + `_mark_delivered` 合并为原子 `_claim_delivery` / `_release_delivery`（N-03）；**发送抛异常时也回滚占位**（见 §7.3）；幂等窗口改走单调钟 `_mono`（与 `events` 的时钟约定一致，否则回拨会让条目永不淘汰 → 重投被静默跳过）；淘汰改 `popitem(last=False)` |
| `app/channels/feishu/adapter.py` | 新增 `reject_inbound_message`（限流专用入站入口）与共享 `_reply_overloaded`；`_get_turn_gate` docstring 标注**进程内语义**（N-05 的登记落点） |

### 7.2 测试改动

| 文件 | 改动 |
|---|---|
| `tests/unit/test_feishu_dedupe_ledger.py` | 时长类用例的注入点由 `_now` 改为 `_mono`（5 处）；`reset_event_state` 增断言 `_mono is time.monotonic`；**新增**：wall clock 回拨下去重仍淘汰 / 限流窗口仍排空、超长时间戳三种形态（含负数）不溢出、时间戳单位兼容、新鲜度拒绝时记录 skew |
| `tests/unit/test_feishu_delivery.py` | **新增**：并发同键只投递一次（用会让出事件循环的 transport 固定竞态）、失败返回时回滚占位可重试、**抛异常时回滚占位可重试**、单调钟跨过 TTL 后同键可重发 |
| `tests/e2e/test_feishu_webhook.py` | `event_payload()` 的 `create_time` 改为**当前时间**（否则明文路径开启新鲜度校验后会全线 403）；`test_rate_limit_per_open_id` 由断言 429 改为断言 200 + 兜底文案；**新增**：限流消息经重投不丢、明文陈旧 `create_time` / 陈旧时间戳头 403、明文新鲜事件仍受理、超长时间戳头不 500 |
| `tests/unit/test_feishu_error_matrix.py` | `test_row13_inbound_rate_limit_window` 的注入点改为 `_mono` |

### 7.3 实施中发现并修掉的新缺陷（**由新用例捕获**）

`_claim_delivery` 的首版实现只在「发送返回失败结果」时回滚占位，**未覆盖「发送抛异常」**。由于 `client.reply_message` 在 token 获取失败等情形下是**抛异常**而非返回失败结果，占位会泄漏 —— 结果是该 `message_ref` 的后续所有重试都被自己的幂等表判为「已投递」而**静默跳过**，比修复前更糟（修复前失败不记账）。

由既有用例 `test_send_never_raises_on_any_transport_exception` 暴露（该用例对同一 key 连续 4 次发送、每次都必须返回 `ok=False`；首版实现第 2 次起返回 `ok=True`）。修法：两条发送路径都改为

```python
try:
    result = await client.reply_message(message_ref, part)
except BaseException:
    _release_delivery(key)
    raise
```

用 `BaseException` 是为了让 `CancelledError` 也回滚占位（任务被取消时消息仍可重投）。
并补 `test_raised_send_releases_claim_and_allows_retry` 固化该路径。

### 7.4 验证

**飞书全量**（`-p no:xdist -o addopts=""`，单进程）：

| | 结果 |
|---|---|
| 改动前基线 | 265 passed, 2 skipped |
| 改动后 | **280 passed, 2 skipped**（+15 用例，零回归） |

**反向验证**（把 4 个源码文件 `git checkout --` 回退到改动前、保留新用例）：**17 failed**，确认新用例不是空过 —— 覆盖 N-01/N-02/N-03/N-04 与时钟的用例在旧代码上全部失败。回退用「备份 → `git checkout --` → 跑 → `cp` 回」流程，恢复后 md5 逐文件比对一致。

**更大范围回归**（`tests/unit + tests/integration + tests/e2e + tests/golden`）：

| | 结果 |
|---|---|
| 改动前（旧源码 + 新用例） | 21 failed, 1993 passed（其中 17 为上述新用例，另 4 为既存 flaky） |
| 改动后 | **4 failed, 2010 passed** |

改动后仅剩的 4 个失败全部落在**既存 flaky 集合**内，且成员逐轮互换：
`test_debug_state_history` / `test_chat_http_integration` / `test_memory_e2e` / `test_turn_meta_stream` / `test_v65_matrix::test_v65_008`。
单独运行这组文件时仅 3 个失败、且与批量运行的成员不一致 → 顺序/网络敏感，与本次改动无关（改动全部落在飞书模块，Web 路径零接触）。

**Windows 环境注意**：批量运行时 pytest 会在退出阶段于 `cleanup_numbered_dir` 抛 `PermissionError: [WinError 5] ...\pytest-of-31166\pytest-current`，导致**统计行被吞掉**。加 `--basetemp=<独立目录>` 可绕过；否则需把输出重定向到文件后另行解析。

### 7.5 行为变更登记（需产品/运维知晓）

1. **入站限流不再返回 429，改为 200 + 兜底文案**。这是用户可见的行为变更：用户会收到「你发得太快了，我一条条慢慢回你～」，而不是静默丢消息 + 飞书重投。同时落地了 v1.1 登记未做的 F-09。
2. **明文来件现在必须通过新鲜度校验**（此前完全不校验）。窗口 = `FEISHU_SIGNATURE_WINDOW_SECONDS`（默认 300s），回落事件 `header.create_time`。
   影响：被飞书重投超过窗口的**旧消息会被拒**（与加密路径 F-01 的既有取舍一致）。**空 `FEISHU_ENCRYPT_KEY` 部署下这一变更会立刻改变线上行为**，如需放宽请调大该配置。
3. **去重与限流的时长判断改走单调钟**：wall clock 回拨不再影响 TTL/滑窗。副作用是 `events._mono` 成为新的测试注入点（`_now` 仍用于新鲜度）。
4. `delivery` 新增 `_now` 注入钩子；`reset_delivery_state()` 会一并复位。

### 7.6 剩余项状态（截至第二批修复后）

| 项 | 状态 |
|---|---|
| N-01 / N-02 / N-03 / N-04 | ✅ 已修（第一批） |
| 判断 3（时钟分离） | ✅ 已修（第一批 + `delivery` 补齐） |
| N-05（多实例并发闸门） | ⚠️ 部分：容量校验已按 `feishu_max_concurrent_turns × feishu_instance_count` 折算，风险在启动期可见；**跨进程闸门仍未实现** |
| N-06（加密体缺内层 token） | ✅ 已修 |
| N-07（配置缺失 vs 鉴权失败） | ✅ 已修 |
| N-08（非文本消息静默丢弃） | ✅ 已修（第三批，按产品决策改为回兜底文案） |
| N-09（限流阈值共用配置键） | ✅ 已修（新增 `FEISHU_RATE_LIMIT_PER_MINUTE`，0 = 沿用共用键，**向后兼容**） |
| N-10（出站幂等 TTL 复用入站 TTL） | ✅ 已修（新增 `FEISHU_OUTBOUND_IDEMPOTENCY_TTL_SECONDS`，0 = 沿用） |
| 判断 1（多实例全套外置） | ❌ 未动。**在补齐前仍不得开多 worker**（v1.1 §5.1 硬前置） |
| 判断 2 的容量上界 | ❌ 未加。单调钟已消除「回拨导致永不淘汰」，该上界降为兜底项 |

### 7.7 文档对齐（仓库约定：架构演进须先更新基线）

改动涉及飞书域的**对外行为**（限流响应码、新鲜度覆盖范围），故按约定同步了「本域唯一架构依据」及其派生物：

| 文档 | 改动 |
|---|---|
| `docs/integrations/feishu/architecture.md` | §4.1 时序图 [2] 与 [4] 步：新鲜度改为**覆盖所有来件**、限流由 `429` 改为 `200` + 兜底文案；§4.2 新增「限流不以 4xx 拒收」「两个时钟职责分离」两条设计点，并给「全局并发闸门」补上**进程内作用域**警告；§6.2 错误矩阵 #1 / #13 / #17 同步；§6.4 结论 2 补上「空 Encrypt Key 的残余风险必须明确承认」（token 是唯一凭据、不绑定来源），结论 3 由「加密体无签名头」泛化为「签名路径未生效」，并登记**回归陷阱**（写死 `create_time` 的夹具会全线 403）与**文档/实现背离**的说明 |
| `docs/integrations/feishu/tasks.md` | 新增 **FEISHU-009** 任务条目（来源 / 状态 / 已实现 Scope / 验收条件 / 行为变更登记 / 未实现 Scope），与既有 FEISHU-007 的结构对齐 |
| `docs/integrations/feishu/regression-checklist.md` | 运维段的限流条目改为「HTTP 200 + 兜底文案」，并补两条人工回归项（明文陈旧时间戳 → 403；拒绝日志含 `skew`） |

**刻意未改**：`task-details/FEISHU-002.md` / `FEISHU-006.md` 中仍写着「入站限流 → 429」的段落。理由：本仓库**从未**对冻结的 task-details 做后续 review 的反向标注（v1.1 改了 F-02/F-03/F-10 同样未回填），保持其「当时交付内容的记录」语义；变更以 FEISHU-009 + architecture.md（活文档）+ 本报告为准。
⚠️ 但这留下一个**回归风险**：只看 FEISHU-002 规格的人可能把限流「修回」429 而重新引入 N-01。若你希望消除该风险，可在这两处加一行指向 FEISHU-009 的指针（属对冻结文档的编辑，故未擅自执行）。

### 7.8 第二批修复（N-05 / N-06 / N-07 / N-09 / N-10）

#### 代码改动

| 文件 | 改动 |
|---|---|
| `app/core/settings/feishu.py` | 新增 `feishu_rate_limit_per_minute` / `feishu_outbound_idempotency_ttl_seconds`（均允许 `0` = 沿用共用键）/ `feishu_instance_count`（须 ≥ 1），并补三条校验 |
| `.env.example` | 补三个新键占位 |
| `app/channels/feishu/events.py` | 新增 `rate_limit_per_minute()`：`feishu_rate_limit_per_minute` 为 0 时回落 `chat_rate_limit_per_minute`（N-09）；`verify_token` 在 `expected` 为空时改抛 `FeishuConfigError`（N-07） |
| `app/channels/feishu/delivery.py` | 新增 `_idempotency_ttl_seconds()`：`feishu_outbound_idempotency_ttl_seconds` 为 0 时回落 `feishu_dedupe_ttl_seconds`（N-10） |
| `app/channels/feishu/adapter.py` | 并发容量校验按 `feishu_max_concurrent_turns × feishu_instance_count` 折算，warning 文案带出折算过程（N-05） |
| `app/api/v1/feishu.py` | token 校验改为**无条件要求**（删 `elif not encrypted` 分支）；`FeishuConfigError` 与 `FeishuAuthError` 分流到 error / warning 日志，响应码统一为 `401`（N-06 / N-07） |

#### 两个刻意的设计取舍

1. **N-09 / N-10 用「0 = 沿用共用键」而非直接换新键**。若新键默认给 30 / 600 并直接取代共用键，则运维此前为 Web 侧调过的 `CHAT_RATE_LIMIT_PER_MINUTE` 会被静默忽略（飞书阈值回落到默认值）——这正是本仓库已知的 `extra="ignore"` 类静默陷阱。用 0 表示继承，**默认行为零变化**，运维想解耦再显式配置。
2. **N-05 只让风险可见，不改闸门本质**。真正的修复（跨进程信号量）属多实例前置，与 v1.1 §5.1 的两项（去重落库、跨进程会话串行）必须同批做，否则只把并发问题挪个位置。故本批只做「把 `limit × 实例数` 纳入校验」，并把这一点写进 docstring 与架构文档，避免读者误以为闸门已跨实例。

#### N-06 撞上既有契约的处理

收紧后 `test_decryptable_but_malformed_inner_200_no_dispatch` 失败：它的载荷 `{"surprise": True}` 既缺 token 又结构非法，把两个场景混在一起。处理方式是把契约拆清：

- 「**token 合法**但明文结构非法」→ `200` + 零派发（错误矩阵 2b 的原意，避免飞书无限重推）——原用例改为带上合法 token；
- 「解密后**缺 token**」→ `401` + 零派发（新增用例 `test_encrypted_without_inner_token_401`）。

**风险登记**：这是本批唯一收窄的对外契约。若飞书某类事件合法地不带 `header.token`，会从「放行」变为 `401`。判定依据是飞书 v2 事件回调恒带 `header.token`、且 e2e 夹具一直如此；属 fail-closed，出问题时日志会明确指向 `verification token missing`。

#### 验证

飞书全量（`-p no:xdist -o addopts=""`）：**292 passed, 2 skipped**（第一批结束时 281 → 新增 11 个用例，零回归）。新增用例覆盖：token 未配置抛 `FeishuConfigError`、加密体缺 token → `401`、限流阈值继承与解耦、出站幂等 TTL 继承与解耦、并发闸门按实例数折算的 warning 与其静默路径、三个新配置键的 0 值语义与边界校验。

### 7.9 第三批修复（N-08，按产品决策）

**决策依据**：N-08 严格说不是缺陷——FEISHU-002 与 architecture §7.2 把「非文本」列为第一阶段范围外，「忽略」是有意设计。但从用户视角，「发了图片没反应」与「机器人挂了」无法区分。经产品确认，改为**回一句兜底文案**，内容理解仍不做。

#### 设计要点

| 关注点 | 处理 |
|---|---|
| 判定 | 新增纯函数 `events.parse_unhandled_message(payload) -> UnhandledMessage \| None`，只覆盖「私聊 + 非文本或空白 + 回复锚点齐全」。群聊、非消息事件、缺 `message_id` / `chat_id` / `open_id` 一律返回 `None`（**不回**） |
| 闸门 | 兜底回复**走与正常消息完全相同的去重与限流**（`accept_event` → `allow_rate`）。理由：它同样是出站流量。故飞书重投不产生第二次回复；用户刷屏时连兜底也不回（再回只会放大） |
| 幂等 | 复用 `delivery` 的原子占位，键为 `reply:{message_id}:0`，与正常回复同一条路径 |
| 抽取 | 把 `parse_message_event` 的信封校验抽成共享的 `_envelope()`。**既有诊断日志一行未少**（只是位置从函数内移到 helper 内），且所有 `parse_message_event(...) is None` 断言的返回值语义逐字不变——这是能在不改 30+ 条既有断言的前提下重构的前提 |
| 边界 | 明确区分「反馈」与「支持」：`architecture.md` §7.2 补一行，防止读者把 N-08 误解为「非文本已被支持」 |

#### 验证

- 飞书全量：**309 passed, 2 skipped**（第三批新增 17 个用例，零回归）。
- **反向验证**：把 `api/v1/feishu.py` / `events.py` / `adapter.py` 三个文件 `git checkout --` 回退到 HEAD、只保留新用例 → **16 failed**，确认用例不是空过（`test_group_non_text_message_gets_no_reply` 在旧代码上通过，因为它是「不该回」的守卫，符合预期）。回退后按 md5 逐文件比对恢复一致。

#### 用户可见行为变更

私聊里的表情 / 图片 / 语音 / 文件 / 纯空白消息，从**完全静默**变为回一句「我目前只能读文字哦～」。群聊行为不变（仍静默）。

### 7.10 FEISHU-010 入站去重落库（多实例前置第 1/3 项）

#### 分层约束（本次最重要的发现）

`tests/unit/test_feishu_boundary.py` 的 `CHANNELS_ALLOWLIST_PREFIXES` **不含 `app.repositories`**，`CHANNELS_APP_DENY_EXACT` 含 `app.core.db` → **`app/channels/**` 不得 import `app.repositories`**（fail-closed）。而 `app/api/` 与 `app/main.py` 被**刻意排除在扫描外**（`test_direction2_api_and_main_excluded_from_scan`）——它们是组合根。

因此去重存储的**分派必须写在 `api/v1/feishu.py`**：通道层保持纯函数、不感知存储；DB 路径经 `asyncio.to_thread` 下放（同步 SQLAlchemy 不得跑在事件循环线程上）。

#### 实现

| 位置 | 内容 |
|---|---|
| `migrations/versions/0050_feishu_dedupe_ledger.py` + `core/db.py::FeishuDedupeLedgerRow` | `feishu_dedupe_ledger(event_id PK, received_at)` + `received_at` 索引 |
| `repositories/feishu_dedupe_ledger_repository.py` | `claim`（先摘除同 id 的过期行再插入，`IntegrityError` 判定）/ `purge_before` / `exists` |
| `services/feishu_dedupe_service.py` | TTL 折算、**fail-open**、每 `PURGE_EVERY=256` 次成功占位摊还清理 |
| `api/v1/feishu.py` | `_claim_event()` 按 `feishu_dedupe_persistent_enabled` 分派内存表 / DB 路径 |
| `core/settings/feishu.py` + `.env.example` | `feishu_dedupe_persistent_enabled`（默认 `false`） |

**表名为何不叫 `feishu_events`**：v24 有一条架构禁令 `test_ban_no_second_event_tables_unchanged`，断言「名字含 `event` 的表恰为 `world_events` / `outbox_events` / `relationship_events`」——守卫的是「`world_events` 是唯一事件 SoT」。`feishu_events` 会撞上它。与其放宽该禁令，不如把表命名为它本来的身份：一张**去重账本**，不是事件存储。

#### 关键取舍

1. **fail-open**：存储不可用时放行并记 warning。去重的收益是省掉重复处理，fail-closed 会直接丢掉用户消息。**与限流取向相反**（限流失败应保守拒绝以保护 LLM）。
2. **TTL 语义必须与内存表对齐**：主键约束本身不知道「过期」，故 `claim` 先摘除该 `event_id` 的过期行再插入；否则过 TTL 的事件会被永久判重。
3. **默认关闭**：开启才是多实例姿态；关闭时行为与升级前完全一致。多 worker 仍需另两项前置，故不在本次默认开启。

#### 🚨 加一个迁移的真实代价：22 个跨版本钉测

用 `git worktree` 取 HEAD 干净基线实测（v24+v25+v26）：

| | 结果 |
|---|---|
| HEAD 基线 | 10 failed / 2991 passed |
| 加迁移后（未升级守卫） | **32 failed** → 我的迁移造成 **22 个新失败** |
| 升级守卫后 | **10 failed / 2991 passed**，与基线**逐条一致** |

22 个失败分布在 v25（12 文件）、v24（tool003 / tool012_support / tool007 / tool008 / tool012_bans / tool_acceptance）、v26。处理时按性质分两类：

| 类别 | 处理 | 理由 |
|---|---|---|
| **链头钉测**（`MIGRATION_HEAD`、`test_migration_chain_head_is_still_00NN`、`max(numbered) == NN`、`MIGRATION_FILE_COUNT_CURRENT`、`MIGRATION_BREAKPOINT`、`MIGRATION_ADDED_VS_BASELINE`、`MIGRATION_HEAD_PREVIOUS`） | **机械升级到 0050** | 本仓库有过 0048→0049 的同款操作先例 |
| **v24「零 schema 变更」保证**（`SCHEMA_COLUMNS_DIGEST_BASELINE`） | **引入显式例外登记** `SCHEMA_ADDED_TABLES_VS_BASELINE = ("feishu_dedupe_ledger",)` + 新增 `support.schema_columns_digest(exclude_tables=())`；断言变为「全库摘要 == `SCHEMA_COLUMNS_DIGEST`」且「排除已登记新增表后 == `SCHEMA_COLUMNS_DIGEST_BASELINE`」 | 直接改基线摘要常量等于**把断言改谎**。排除后实测精确复现 `506ee5d5cf357bdf`，证明「除已登记的新增表外基线零漂移」——保证仍在 |
| **v25 `ZeroMigration` 的 `test_no_newer_revision_after_0050`** | 改写为**不钉绝对版本号**：断言版本号连续无空洞 + 链头唯一 + 本任务未新增迁移文件 | 原断言（`max == 49`）在每次正常迁移后都会失败，且重命名后语义自相矛盾 |
| **v26 `test_v25_migration_head_0049_documented`** | 改写为「≥ 0049 且链头自洽」 | 机械改成 `_0050_` 会**事实错误**：0050 是飞书迁移，不是 v2.5 的链头 |
| **v24 `test_ban_no_second_event_tables_unchanged`** | **改表名**（`feishu_events` → `feishu_dedupe_ledger`） | 该禁令守的是「`world_events` 唯一事件 SoT」，不该为迁就命名而放宽 |

#### 未验证项与登记

- **PG 路径未验证**：本机 docker daemon 未运行、无 `docker compose`、5432 未监听 → 所有 PG 迁移测试 SKIP。**SQLite 上整链 `upgrade head` / `downgrade 0049` / 再 `upgrade` 往返已验证**（列 / PK / 索引与 ORM 逐项一致），但 PG 的 `IntegrityError` 语义与并发插入行为未实测。
- **技术债登记（新增 P1）**：迁移链头钉测散落在 15 个测试文件、每加迁移需机械升级一遍。本次已按「该钉的钉、不该钉的改写为语义断言」处理，但 `v25` 的 `ZeroMigration` 类与 `v26` 的版本号命名仍会随升级逐渐名不副实，建议后续统一改为「相对当前 head」的断言（已写入 `docs/current-system-architecture-baseline.md` 技术债表）。
- **多实例前置进度**：去重落库 ✅（本次）；跨进程会话串行 ❌、出站幂等落库 ❌ —— **三项全齐前仍不得开多 worker**。

### 7.11 FEISHU-011 方案 E：多实例启动期硬闸

**背景**：`feishu_instance_count` 此前只影响一条启动 warning（容量校验折算），语义上容易被误读为「已经支持多实例」。而三项硬前置只完成 1/3，此时开多 worker 的故障形态是**偶发**的（需同时满足同会话 + 跨实例 + 时间重叠）——回复交错、`conversations` / `memory` / `character_state` 竞态写，极难复现定位。

**改动**：`core/settings/feishu.py` 的 `validate_feishu_config` 在 `feishu_enabled` 分支内（紧随凭据校验）加硬闸——`FEISHU_INSTANCE_COUNT > 1` → 抛 `SettingsError`，错误信息列出三项前置进度并指向 `multi-instance-options.md`。未启用飞书时不拦（与凭据校验同口径：无 webhook 即无并发风险）。

**取舍登记**：
- 代价是**暂时零横向扩展能力**，只能纵向扩（单实例内调 `feishu_max_concurrent_turns` 与池容量）。
- `adapter._get_turn_gate` 里的「`limit × 实例数` 折算」**保留**：当前只是防御性校验，将来放开硬闸后即恢复为真实保护。docstring 已注明这一点。
- 错误信息**不含任何凭据明文**（已加断言）。

**验证**：
- 飞书全量 **347 passed / 2 skipped**；设置测试 +3 例。
- `tests/v24 + v25 + v26`：**10 failed / 2991 passed**，与 HEAD 基线逐条一致（E 不涉及迁移，故不触发钉测）。
- `tests/unit + integration + e2e + golden`：**3~6 failed / 2060 passed**，失败成员逐轮互换且全部落在既存 flaky 集合内（流式 SSE、日志断言、顺序敏感）。已单独复核可疑项：单独运行通过，且所在文件 0 处飞书引用。
- **反向验证**：把 `settings/feishu.py` 回退到 HEAD、只留新用例 → `test_feishu_enabled_rejects_multi_instance` **失败**（另两例是「不该拦」的守卫，新旧代码都绿，符合预期），恢复后 md5 一致。
- **连带修正**：`test_row13b_concurrency_gate_accounts_for_instance_count`（本报告 §7.8 新增）原用 `feishu_enabled=true` + `instance_count=4` 触发折算校验——被 E 的硬闸封死。已改为 `feishu_enabled=false`（折算校验在当前只走防御性路径），并在 docstring 注明「将来放开硬闸后应改回 `enabled=true` 并额外断言闸门真的生效」。

**放开硬闸的前置**：三项前置全齐，且硬闸已被替换为所选方案（A 或 C）的实现。**只放开硬闸而不落实现，等于把今天封死的故障重新放出来** —— 这一句已写进 `multi-instance-options.md` §4。

### 7.12 FEISHU-011 选定方案 C：入口按 `open_id` 粘性路由（应用侧已实现）

**决策**：从五个方案中选定 **C**。理由：一次解决两个缺口（会话串行 + 跨实例连发合并），且不需要分布式锁的一切复杂度（无租约窗口、无连接占用、无哈希碰撞、无新表新迁移）。方案 E 的闸门**形态保留、语义升级为「多实例就绪契约」**。

#### 交付边界（重要）

方案 C 天然分两半：**应用侧契约**（本仓库）与 **ingress 侧分流**（部署与运维）。本次交付前者。

| 部分 | 状态 |
|---|---|
| 分片算法 / 实例身份 / 归属校验 / 就绪契约 | ✅ 本次交付 |
| ingress 分流（C1 LB / C2 router / C3 分区队列） | ❌ 待运维落地 |

#### 应用侧实现

| 位置 | 内容 |
|---|---|
| `channels/feishu/shards.py`（新增） | `shard_of` / `owns` / `note_wrong_shard`。算法 `crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT`，用标准库 `zlib.crc32`（取值稳定、各语言都有等价实现，ingress 可复刻） |
| `core/settings/feishu.py` | 新增 `feishu_instance_index`（须 `< count`）与 `feishu_ingress_sharded_routing_enabled`；`_assert_multi_instance_ready()` 实现就绪契约 |
| `api/v1/feishu.py` | `_owns_shard()` 归属校验，**在 `accept_event` 之前**；非本分片 → `503`。非文本兜底路径同样受检 |
| `tests/unit/test_feishu_shards.py`（新增） | **golden 值锁定算法** + 分布均匀性 + 跨调用稳定 + 抽样留痕 |

#### 三处关键设计取舍

1. **非本分片返回 503 而非 200**。503 让飞书重投、有机会落到正确实例；静默丢弃（200）会让消息永久丢失且**无任何可观测信号**。若 ingress 完全没生效，503 会立刻表现为大量错误 + 重投，比「静默丢消息」容易发现得多。
2. **归属校验必须在去重之前**。否则飞书重投会被去重表静默吞掉——正是 FEISHU-009 修过的坑（N-01）。本次把它排到 `accept_event` 之前，保证重投仍有机会被正确处理。
3. **把 `FEISHU_DEDUPE_PERSISTENT_ENABLED` 纳入就绪契约**（不是可选项）。它是 ingress 配错时的**兜底**：即使同一 `event_id` 被两个实例收到，也只有一次会真正处理。所以 `count>1` 时必须同时声明「ingress 已分流」+「跨进程去重已开」。

#### 风险登记（写进文档与回归清单）

- **翻开关前必须验证 ingress 真的在分流**：否则事件大量落错分片 → 503 → 飞书重投 → 重试风暴。应用侧已抽样记 error（每 100 次一条，含期望分片与实例下标）供发现。
- **改 `FEISHU_INSTANCE_COUNT` 会改变分片映射**：`crc32 % count` 的基数变了，几乎所有会话换实例。变更时必须同步改 ingress，并预期一段「会话重新归属」窗口（跨进程去重兜底保证不重复处理）。
- **出站幂等落库仍未做**：在 C 下风险大幅降低（同会话只由一个实例处理），但 `send_proactive` 不走会话锁 → **Autonomy 接入飞书（FEISHU-008）前必须补**。

#### 验证

- 飞书全量 **368 passed / 2 skipped**（+21 用例：分片 10 + 设置 6 + webhook 路由 5）。
- **反向验证**：把 `api/v1/feishu.py` 回退到 HEAD、只留新用例 → 3 个分片用例**失败**（`503` 相关；`challenge 不受检` 与 `本分片正常` 是守卫，新旧都绿，符合预期），恢复后 md5 一致。
- **算法锁定**：`test_shard_values_are_frozen` 记录 `ou_e2e_alice` 在 2/3/4 片下的 golden 分片值（1/0/3）——**算法一改此用例即红**，这正是提醒「必须同步改 ingress」的机制。

### 7.13 FEISHU-011 形态选定 C2：内置轻量 router

**决策**：方案 C 的三形态（C1 LB 粘性 / C2 轻量 router / C3 分区队列）中选定 **C2**，并已实现内置 router 端点。C1 **排除**、C3 **登记为后续演进选项**。完整对比与排除理由见 `ingress-routing-options.md`。

#### 为什么排除 C1

三条全中：

1. **LB 必须持有 Encrypt Key 并实现 AES-256-CBC**——`open_id` 只在 body 里，而配了 Encrypt Key 时 body 是密文（外层只有 `encrypt` 一个字段）。这把 LB 从「转发组件」变成「持密钥 + 做加解密 + 实现哈希」的组件。
2. **算法漂移风险最高**——LB 默认哈希几乎都不是 CRC-32（nginx `split_clients` 用 MurmurHash2、`hash ... consistent` 用 ketama）。不一致时事件大量落错分片，表现为偶发 503 与重投风暴，**不会崩溃、只会静默错**。
3. **扩缩容需跨系统原子变更**——改 `FEISHU_INSTANCE_COUNT` 要同时改 LB 配置与所有实例配置。

#### 为什么 C3 暂不实现

C2 已解决同一问题（同会话恒落同实例）。C3 的增量收益是「重试 / 死信 / 崩溃恢复由队列承担」与「worker 可独立扩缩」，在当前规模下不构成瓶颈，却要付出改造 `SessionInbox`（合并窗口改为按入队时间戳聚合）+ ack/可见性超时/死信 + 新基础设施的代价。**启动信号**已写入文档：需要按会话量弹性扩缩 worker、飞书重投不可控成为实际痛点、或已在别处引入 MQ。

#### 实现

| 位置 | 内容 |
|---|---|
| `api/v1/feishu_ingress.py`（新增） | `POST /feishu/ingress/events`：限长读体 → 解密 → 取 `open_id` → `shards.shard_of` → 转发 → 原样回传 |
| `api/v1/feishu_http.py`（新增） | 与 webhook 共用的 `read_body_limited()` / `reject()`（`feishu.py` 改为别名导入，函数体零改动） |
| `core/settings/feishu.py` | `feishu_router_enabled` / `feishu_router_instance_urls`（个数须等于 `instance_count`）/ `feishu_router_timeout_seconds` |

#### 五条不可动摇的设计约束

1. **转发原始 body 与原始签名头**。飞书签名覆盖的是**密文 body**；转发明文会让下游验签必然失败（403）。只转发 `Content-Type` / `X-Lark-Request-Timestamp` / `X-Lark-Request-Nonce` / `X-Lark-Signature`。
2. **router 不做鉴权决策**。校验全在下游，安全闸只有一处；token 错的请求也照转，由下游拒绝。
3. **转发失败不得自行改投**。改投会破坏「同会话恒落同实例」，导致同会话并发。返回 503 让飞书重投。
4. **取不到 `open_id` 时固定 shard 0**（challenge / 结构非法 / 无 Encrypt Key）。这些请求要么无需精确路由，要么会在下游被拦下。
5. **应用侧归属校验保留**（`_owns_shard`）。router 分对是正常路径；万一配错，应用侧的 503 + 抽样 error 是最后一道可观测防线。

#### 就绪契约扩展

`FEISHU_ROUTER_ENABLED` 本身即是「ingress 已分流」的声明，无需再开 `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED`（二者任一即可）。

#### 验证

- `tests/unit/test_feishu_ingress_router.py`：**14 passed**。
- **反向验证**：把 `api/v1/feishu.py` 回退到 HEAD → 3 个分片用例失败（另 2 例是守卫，新旧都绿），恢复后 md5 一致。

---

### 7.14 FEISHU-012 出站投递幂等落库

#### 实现

| 位置 | 内容 |
|---|---|
| `migrations/versions/0051_feishu_deliveries.py` + `core/db.py::FeishuDeliveryRow` | `feishu_deliveries(idempotency_key PK, delivered_at)` + 索引 |
| `repositories/feishu_delivery_ledger_repository.py` | `claim`（先摘除该键过期行再插入）/ `release` / `purge_before` / `exists` |
| `services/feishu_delivery_ledger_service.py` | TTL 折算、**fail-open**、摊还清理；对外 **async API**（DB 经 `asyncio.to_thread` 下放） |
| `channels/feishu/delivery.py` | 新增 seam `set_persistent_idempotency()` / `clear_persistent_idempotency()`；`_claim_delivery` / `_release_delivery` 改 async 并按 hook 分派 |
| `app/main.py` | 组合根在 `feishu_enabled` 分支内按配置安装 hook |

#### 三处关键取舍

1. **注入而非直接依赖**。`app/channels/**` 的依赖 allowlist 禁止 import `app.repositories`（fail-closed），故持久化实现不能写在通道层。做法是 `delivery` 暴露一个 seam，由组合根 `app/main.py` 安装——与 FEISHU-010 的 `_claim_event` 同思路，只是那边是「按调用分派」、这边是「启动期安装」。
2. **占位入口改为 async**。原 `_claim_delivery` 是同步函数（纯内存）；改为 async 后 DB 路径才能 `asyncio.to_thread` 下放，否则**同步 SQLAlchemy 会阻塞事件循环**。6 处调用点同步改为 `await`。
3. **fail-open（放行投递）**。与入站去重同取向：fail-closed 会让用户**收不到任何回复**，而重复一条消息远比静默不回可接受。

#### 🚨 迁移 0051 的守卫升级（第二次，流程已固化）

照 FEISHU-010 §7.10 的五类处理：链头时间点钉测机械升到 0051；`SCHEMA_TABLE_COUNT` 44 → 45、两个摘要重算、`SCHEMA_ADDED_TABLES_VS_BASELINE` 追加 `feishu_deliveries`。**排除两张新增表后仍精确复现 `SCHEMA_COLUMNS_DIGEST_BASELINE = 506ee5d5cf357bdf`** —— 「基线零漂移」的保证依然成立，且没有把断言改谎。

#### 验证

- 飞书全量 **411 passed / 2 skipped**（+43 用例）。
- `tests/v24 + v25 + v26`：与 HEAD 基线（**10 failed / 2991 passed**，用 `git worktree` 实测）逐条一致。中间一次运行出现 `test_tool006_integration::test_autonomy_decision_to_world_write_through_outbox`，经「单独跑 + HEAD 对拍」确认它在 HEAD 上也失败、且属 autonomy 三账对齐的**顺序敏感 flaky 家族**（下一轮即消失），与本批无关。
- `tests/unit + integration + e2e + golden`：**4 failed / 2126 passed**，4 个全在既存 flaky 集合内。

#### 连带修正

就绪契约从两项扩为三项后，`test_feishu_webhook.py` 的 `SHARDED` 与 `test_feishu_ingress_router.py` 的 `ROUTER_SETTINGS` 都需补上 `feishu_outbound_idempotency_persistent_enabled`——否则设置构造在启动期就抛 `SettingsError`，两处共 19 个用例转红。这类失败不是回归，而是**被新不变量正确地判为「配置不完整」**。
> ⚠️ 该「三项契约」在 §7.15 已被推翻：出站幂等的开关被移除（必需能力不该有开关），契约回到两项。

---

### 7.15 移除出站幂等开关：必需能力不该有开关

**背景**：FEISHU-012 初版给了 `FEISHU_OUTBOUND_IDEMPOTENCY_PERSISTENT_ENABLED`，默认关闭，并把「开启它」写进了多实例就绪契约。**这是错的**——跨进程出站幂等不是可选优化，而是多实例下的**正确性前提**：没有它，同一逻辑消息会被每个实例各投一次（重复回复用户）。给它加开关等于给「重复回复」留了一个合法配置。

#### 改动

| 项 | 之前 | 现在 |
|---|---|---|
| 配置项 | `FEISHU_OUTBOUND_IDEMPOTENCY_PERSISTENT_ENABLED`（默认 `false`） | **删除** |
| 组合根 | `if 开关: 安装 hook` | `FEISHU_ENABLED` 时**无条件安装** |
| 存储实现 | 双路径：进程内表 / 持久化表，按开关切换 | **单路径**：只有注入的持久化实现 |
| 就绪契约 | 三项（分流 + 去重 + 出站幂等） | **两项**（分流 + 去重）——出站幂等已无条件生效，无需声明 |
| `delivery` 模块 | `_delivered` / `_mono` / `_claim_delivery_memory` / `_evict_delivered` / `_idempotency_ttl_seconds` / `reset_delivery_state` | 全部删除；只保留注入 seam |
| hook 缺失时 | 静默回落到进程内表 | 记一次 `error` 后**放行发送**（重复一条 > 用户收不到回复） |

**为什么连内存实现一起删**：留着它意味着「持久化路径可以被静默绕过」——又一个隐式开关。单一实现让「哪条路径是活的」不再需要判断；hook 缺失是**配置缺陷**，用 error 日志暴露，而不是用一条降级路径掩盖。

#### 测试侧的连带调整

- `tests/conftest.py` 新增 autouse 夹具 `_persistent_outbound_idempotency`：与生产一致地安装持久化 hook。否则测试会走「hook 未安装」的降级路径，幂等用例失去意义。
- 删除 `reset_delivery_state()` 及其 24 处调用（幂等状态现在在库里，而 conftest 的内存 SQLite **每个用例都是全新的**，不需要重置）。
- 删除 3 个只测内存实现内部结构的用例（`_mono` 注入的 TTL 过期、两处 TTL 表达式一致性）——其意图已由 `test_feishu_delivery_ledger_service.py` 覆盖。
- `test_row11_duplicate_delivery_not_doubled` 的断言从「进程内表有一条」改为「`feishu_deliveries` 里有该键，且只发出一次请求」。

#### 🚨 一个重要的测试环境陷阱：StaticPool 复现不出并发竞态

`test_concurrent_same_key_sends_once` 在改成 DB 路径后**失败**（两次都发出）。排查结论：**不是代码 bug，是测试环境**——`tests/conftest.py` 的内存 SQLite 用 `StaticPool`，**所有 session 共享同一条连接**，两个线程的 `DELETE + INSERT + COMMIT` 会在同一连接上交错，双双判为「首次」。

验证：改用**文件库 + `NullPool`**（每个 session 一条独立连接，与生产 PG 一致）后，5 次试验**全部恰一个成功**。

因此：
- `tests/unit/test_feishu_delivery_ledger_repository.py::test_concurrent_claim_arbitrated_by_unique_constraint` —— 新增跨连接并发用例（仓储层，5 轮）。
- `test_feishu_delivery.py::test_concurrent_same_key_sends_once` —— 改为用独立连接的文件库，保留端到端覆盖。

**通用教训**：凡是靠「数据库唯一约束/行锁」保证的原子性，用 `StaticPool` 的内存 SQLite 都测不出来——必须换成独立连接（文件库 + `NullPool`），否则要么假红（像本次），要么假绿。

#### 验证

- 飞书全量 **410 passed / 2 skipped**。
- `tests/unit + integration + e2e + golden`：**3 failed / 2126 passed**（3 个全在既存 flaky 流式集合内；中间一轮出现的 `test_feishu_isolation::test_two_users_six_resources_isolated` 与 `test_goal_e2e` 经「单独跑 + 复跑」确认是既存顺序敏感 flake，与本次无关）。
