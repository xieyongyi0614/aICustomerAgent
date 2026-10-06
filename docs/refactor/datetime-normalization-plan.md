# 时间口径统一方案（naive/aware 归一）

> **审查对象**：`apps/backend` 全量 datetime 的产生、落库、读回、比较与序列化口径
> **触发事件**：`services/memory/lifecycle.py` 记忆衰减对 `timestamptz` 列读回的 aware 值做减法，抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`（已按 §三 的规则临时修复）
> **本文数据**：均为**实测**（模型列声明 + 全仓 grep + 迁移链 + 既有 review 交叉核对），非估算
> **配套基线**：`docs/current-system-architecture-baseline.md`（本方案落地前须先在该基线登记「时间口径」章节）
> **相关既有结论**：`docs/version/v3.0.0/reviews/RT-ALL-code-review.md` L-1；`docs/version/v1.0.0/v2/v2-architecture.md` §表风格 / §546
> **审查日期**：2026-10-05

---

## 一、执行摘要

### 1.1 结论

**系统的事实口径是「朴素本地墙钟时间（naive local）」，但存在 5 个 `timestamptz` 例外列，且读侧有 2 套互相矛盾的归一手法并存。** 这三件事叠在一起，就是本次崩溃的根因，也是后续所有同类故障的来源。

一句话结论：**不要把「统一」理解成「全部改成 UTC-aware」**——那是约 130 个时间列 + 328 处调用点的高风险大迁移；当前真正该做的是 **统一到既有的朴素本地口径，用唯一工具函数收口，并把 5 个例外列迁回朴素**，用最小改动面彻底消灭「naive/aware 混用」这一整类故障。

### 1.2 三个核心事实

| # | 事实 | 证据 |
|---|---|---|
| 1 | `core/db` 模型侧 **≈128** 个时间列中，仅 **5 个**是 `timestamptz`，其余全是朴素 `timestamp` | `grep -o "mapped_column(DateTime," core/db/` = 128；`timezone=True` 仅 5 处（模型 + 迁移各 5） |
| 2 | 全库统一用朴素 `datetime.now()` 取当前时间（**328 处 / 154 文件**），仅 4 处用 aware UTC | `grep -o "datetime.now()"` = 328；`datetime.now(timezone.utc)` 仅 4 处（另 `core/ids.py` 用 `datetime.now(dt.UTC)` 取毫秒戳） |
| 3 | 读侧归一存在 **两套互斥假设**：`replace(tzinfo=None)` 与 `astimezone().replace(tzinfo=None)` | 前者 8 处真实代码（5 文件）；后者仅 `tool/validator.py:309-310` |

事实 3 是最危险的：两套手法的前提假设**不可能同时成立**（见 §2.3），说明代码库对「aware 值到底代表什么」没有共识。

### 1.3 推荐路线

| 阶段 | 内容 | 风险 | 建议 |
|---|---|---|---|
| **阶段 0（立即）** | 收口到朴素本地口径：新增唯一时间工具模块；替换全部散落归一；把 5 个 `timestamptz` 列迁回朴素；固定 DB 会话时区 | 低 | ✅ **本方案主张先做这一步** |
| **阶段 1（可选，独立版本）** | 若确需跨时区/DST 正确性，再整体迁到 UTC-aware（全列 timestamptz + 全量 `now(utc)`） | 高 | ⏸ 待明确多时区需求再启动 |

---

## 二、现状盘点

### 2.1 事实口径 = 朴素本地时间（naive local）

- 取当前时间：`datetime.now()`（**无 tz**），**328 处 / 154 个文件**，覆盖 repositories / services / application / api 全层。
- 列声明：`mapped_column(DateTime, ...)`，Postgres 落为 `timestamp without time zone`。
- 前端消费：`new Date(item.createdAt)`（`apps/frontend/src/...`）——**JS 对无偏移 ISO 串按本地时区解析**，与「朴素=本地」口径自洽。
- 该口径是**有意选择**，非疏漏：`docs/version/v1.0.0/v2/v2-architecture.md:354` 明写「表风格对齐 V1：… naive `datetime.now()` …（timezone-aware 时间戳列 P2）」。
- 已有逻辑时钟抽象：`app/core/clock.py::logical_now()`（周期内注入 `now`，周期外回落真实本地时间）；`app/services/world/time_provider.py`（world 域时间读取口）。二者均为**朴素**口径。

### 2.2 五个 `timestamptz` 例外列

| 列 | 定义 | 写入值 | 读回（Postgres） |
|---|---|---|---|
| `memories.last_reinforced_at` | `core/db/memory.py:48` | 朴素 `datetime.now()`（`lifecycle.py:139`） | **aware** |
| `memories.last_decayed_at` | `core/db/memory.py:51` | 朴素 `datetime.now()`（`lifecycle.py:140/204`） | **aware** |
| `memories.forgotten_at` | `core/db/memory.py:54` | 朴素 `datetime.now()`（`lifecycle.py:232/380`） | **aware** |
| `conversations.mode_entered_at` | `core/db/conversation.py:32` | 朴素 `datetime.now()`（`conversation_repository.py:153-155`） | **aware** |
| `insights.invalidated_at` | `core/db/reflection.py:40` | 朴素 `datetime.now()`（`reflection/lifecycle.py:67/87`） | **aware** |

迁移侧同源：`migrations/versions/0001_squashed_full_schema.py:194,361,488,489,490`。

**关键机制**：这 5 列写入的是「朴素本地时间」，Postgres 按**会话时区**解释它并加上时区标记；读回时变成 aware。于是「同一个值」在写侧是 naive、读侧是 aware——任何 `now - row.列` 都在读侧爆炸。这就是本次崩溃。

> 注：`docs/version/v2.6.0`、`v2.0.0` 多个任务文档把 `due_at` / `scheduled_at` / `created_at` 描述为 `timestamptz`，但**代码里是朴素 `DateTime`**（如 `core/db/autonomy.py:176`）——属文档与实现漂移，需一并纠正（§5.6）。

### 2.3 读侧两套互斥的归一手法（最危险）

| 手法 | 位置 | 隐含假设 | 对「真 UTC 值」的结果 |
|---|---|---|---|
| `value.replace(tzinfo=None)` | `reflection/evidence/windows.py:118`（`_naive`）；`conversation/context.py:73-80`；`memory/retriever.py:100-101,165-166`；`memory/lifecycle.py:154`（本次新增） | aware 值的**数字串已是本地墙钟**（即来自 §2.2 那类列） | ❌ 少 8 小时（GMT+8） |
| `left.astimezone().replace(tzinfo=None)` | `tool/validator.py:300-310`（`_comparable`，**唯一正确换算**） | aware 值是**真实 UTC 瞬间**（如外部 ISO 入参） | ✅ 正确 |

`tool/validator.py:302-305` 的注释已经点破了这个矛盾：
> 「直接 `replace(tzinfo=None)` 会丢掉偏移量：UTC-aware 的 `due_at` 会被当成同一串本地时间，在 GMT+8 下凭空少 8 小时。」

也就是说：**同一份代码库里，A 处认为 aware 值数字串是本地墙钟，B 处认为它是真 UTC。** 两者对同一个值会给出相差 8 小时的结论。当前没爆，只是因为两套手法服务的数据源恰好不同；一旦某列的数据源变化（例如把 §2.2 的列换成真 UTC 写入，或把外部输入写进 memory），立刻产生静默的时间错算。

### 2.4 契约层要求 aware，存储层却是 naive

- 契约（值对象）**强制 aware**：
  - `channels/base.py:35` `InboundMessage.received_at`「必须为时区感知时间」；
  - `application/agent_runtime/contracts.py:153` `RuntimeInput.received_at` 同款校验。
- 但落库列是 **naive**：`core/db/identity.py:77` `FeishuDedupeLedgerRow.received_at: DateTime`。
- 值的来源是 `services/delivery/dedupe.py:40` 的 `now = datetime.now()`（**朴素本地**）——与全库一致。
- **修正（2026-10-05 复核）**：初版此处曾推断「真 UTC aware 写入 naive 列」，属 grep 级误判。`InboundMessage.received_at`（`channels/feishu/events.py:378`，真 UTC aware）是**通道契约值**，并未落到 `feishu_dedupe_ledger`；该表由 `dedupe.claim` 自取 `datetime.now()` 写入。故本表口径本就与全库一致，无需特殊处理（identity 域已在 0007 随批迁移）。

### 2.5 契约内部自身也不一致

`application/agent_runtime` 域混用两套口径：
- aware：`contracts.py:171` `started_at=datetime.now(timezone.utc)`；`session.py:56,117` 同。
- naive：`controller.py`、`state.py`、`loop.py`、`execution_history.py`、`context.py`、`recovery.py`、各 `stages/*.py` 全部 `datetime.now()`。

`docs/version/v3.0.0/reviews/RT-ALL-code-review.md:257-262` 已就此立项 L-1（「`SessionContext.started_at` 默认 naive，与 `RuntimeInput.received_at` 强制 aware 契约内部不一致」），结论是「统一 `datetime.now(timezone.utc)` 或沿用逻辑时钟」——**至今未决**。

### 2.6 DB 会话时区未固定

`app/core/db/engine.py` 未设置会话时区；`docker-compose.yml` 的 postgres 服务未设 `TZ`/`PGTZ`。于是 §2.2 那 5 列的行为**取决于 DB 服务器的时区**：

- 服务器 `TZ=UTC`（官方镜像默认）→ 写入的本地墙钟数字串被标为 UTC，读回数字串 = 本地墙钟（`replace` 恰好正确，`astimezone` 错 8 小时）。
- 服务器 `TZ=Asia/Shanghai` → 读回数字串 = 本地墙钟、偏移 +08（`astimezone` 恰好正确，`replace` 错 8 小时）。

**同一个值，两种部署给出两种正确答案。** 这是环境依赖的静默缺陷，必须固定。

### 2.7 风险清单（按严重度）

| # | 风险 | 触发条件 | 现状 |
|---|---|---|---|
| R1 | `TypeError` 崩溃：`now - row.timestamptz列` | 5 个例外列任一被读侧参与朴素运算 | **已实际发生**（memory 衰减） |
| R2 | 静默 8 小时错算 | `replace` 与 `astimezone` 假设被数据源变化击穿 | 潜在，§2.3 |
| R3 | 去重/窗口跨时区错位 | `feishu_dedupe_ledger.received_at` 存真 UTC 到 naive 列 | 潜在，§2.4 |
| R4 | 部署环境 TZ 改变导致行为漂移 | DB 服务器时区未固定 | 潜在，§2.6 |
| R5 | 契约/文档与实现漂移，误导后续开发 | 契约要求 aware、文档写 timestamptz、实现是 naive | 存在，§2.4/§2.5/§2.2 |

---

## 三、阶段 0：统一到朴素本地口径（推荐先做）

### 3.1 唯一规则（写进基线）

> **全系统内部时间一律为「朴素本地墙钟时间」（naive local）。**
> 1. 取当前时间只能经 `app/core/timeutil.py::now()`，禁止散落 `datetime.now()`。
> 2. 任何来自 DB 读回、外部输入、第三方的 **aware** 值，进入内部运算前必须经 `as_naive()` 归一。
> 3. 数据库时间列一律 `DateTime`（朴素），禁止新增 `DateTime(timezone=True)`。
> 4. 跨边界（HTTP 响应）输出统一 `to_iso()`；需要绝对瞬间时另设显式字段，不靠隐式偏移。

### 3.2 新增唯一时间工具模块 `app/core/timeutil.py`

```python
from datetime import datetime, timezone

def now() -> datetime:
    """内部唯一取时口：朴素本地墙钟。周期内应改用 core.clock.logical_now()。"""
    return datetime.now()

def as_naive(value: datetime | None) -> datetime | None:
    """把 aware 值换算到本地墙钟后去 tz；naive 原样返回。"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)

def to_iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

**要点**：`as_naive` 用 `astimezone()`（**正确换算**），统一取代 §2.3 的两套手法。前提是先把 §2.2 的列迁回朴素（§3.3），否则对那 5 列会错 8 小时——**顺序不能反**。

### 3.3 迁移 5 个例外列回朴素（新增 `0003+` 增量迁移）

对 5 列执行 `timestamptz → timestamp`。因当前存的是「本地墙钟数字串 + UTC 标记」，须显式指定换算以免二次偏移：

```sql
ALTER TABLE memories   ALTER COLUMN last_reinforced_at TYPE timestamp USING (last_reinforced_at AT TIME ZONE 'UTC');
ALTER TABLE memories   ALTER COLUMN last_decayed_at    TYPE timestamp USING (last_decayed_at    AT TIME ZONE 'UTC');
ALTER TABLE memories   ALTER COLUMN forgotten_at       TYPE timestamp USING (forgotten_at       AT TIME ZONE 'UTC');
ALTER TABLE conversations ALTER COLUMN mode_entered_at TYPE timestamp USING (mode_entered_at AT TIME ZONE 'UTC');
ALTER TABLE insights   ALTER COLUMN invalidated_at     TYPE timestamp USING (invalidated_at     AT TIME ZONE 'UTC');
```

同步把 `core/db/memory.py:48-56`、`core/db/conversation.py:32`、`core/db/reflection.py:40` 的 `DateTime(timezone=True)` 改为 `DateTime`。

> **`AT TIME ZONE 'UTC'` 的前提**：该写法假定历史写入时**会话时区为 UTC**（§2.6 的默认情形），因此 `timestamptz` 内部的 UTC 表示恰好等于当初写入的本地墙钟数字串。若某部署的 DB 会话时区并非 UTC，则应把 `'UTC'` 换成**当时的会话时区**，否则会二次偏移。

**前置校验**：迁移前先 `SELECT` 抽样确认这些列的实际数字串确为本地墙钟（与同表 `created_at` 对比），避免历史数据里混入过真 UTC 值。**迁移前备份**。

### 3.4 替换全部散落归一

| 位置 | 动作 |
|---|---|
| `reflection/evidence/windows.py:118` `_naive` | 改为 re-export `timeutil.as_naive`（保留名字，去重实现） |
| `conversation/context.py:73-80` | 改调 `as_naive` |
| `memory/retriever.py:100-101,165-166` | 改调 `as_naive` |
| `memory/lifecycle.py:154-158` `_naive` | 改为 re-export `timeutil.as_naive` |
| `tool/validator.py:300-310` `_comparable` | 改调 `as_naive`（行为等价，去重） |

### 3.5 处理 §2.4 的 aware→naive 写入错位

> **已作废（2026-10-05 复核）**：§2.4 的「真 UTC 写入 naive 列」为误判，`feishu_dedupe_ledger.received_at` 实际由 `dedupe.claim` 以朴素本地写入，无需特殊处理。identity 域已随 0007 一并迁移。契约层（`InboundMessage` / `RuntimeInput`）保持要求 aware 不变。

### 3.6 防回归护栏

1. **静态守卫（测试）**：新增测试断言 `app/core/db/` 下**不存在** `DateTime(timezone=True)`（允许显式 allowlist 为空）。
2. **调用点守卫**：新增测试 grep `app/`（排除 `core/timeutil.py`、`core/clock.py`、`world/time_provider.py`、`core/ids.py`），断言无裸 `datetime.now()`。
3. **归一单元测试**：`as_naive` 对 naive/aware/None 三态 + 已知 UTC 输入的断言（对齐 `tool/validator` 的既有正确行为）。
4. 本次已加的 `TestReferenceTimezoneNormalization`（`tests/v2/test_mem005_lifecycle.py`）保留为回归守卫。

### 3.7 固定 DB 会话时区

`app/core/db/engine.py` 建 engine 时显式设定会话时区（如 `connect_args` 或连接 `SET TIME ZONE 'UTC'`），使行为不再依赖服务器默认；`docker-compose.yml` 的 postgres 增加 `TZ`/`PGTZ`。**这是让 §3.3 迁移结果可复现的前提。**

---

## 四、阶段 1（可选）：迁到 UTC-aware（仅当确需多时区/DST）

若产品确定要支持多时区用户或 DST，则「朴素本地」不够用，应一次性做对：

1. 全库时间列 → `timestamptz`；写入值一律 `datetime.now(timezone.utc)`。
2. 迁移须**假设旧数据是本地时区**：`USING (col AT TIME ZONE '<部署本地时区>')`，**必须固定该时区**（如 `Asia/Shanghai`），不可用会话默认。
3. 所有「本地日期」语义（quiet hours、daily plan、自然月账单）显式 `astimezone(用户时区)`，不得再用墙钟直接取 `.date()`。
4. 前端 `new Date()` 改按偏移解析；API 全量输出带偏移 ISO。
5. 契约层 aware 要求得以名正言顺；`RT-ALL` L-1 一并关闭。

**代价**：波及全部 `core/db/*.py`（约 130 列）、328 处取时点、全部比较/序列化、前端格式化、绝大多数测试（测试现以 naive `datetime.now()` 构造）。**不建议与阶段 0 合并**；阶段 0 完成后，阶段 1 是「可选升级」而非「欠债」。

> 参考：`docs/version/v1.0.0/v2/v2-architecture.md:546` 已把「时间戳统一 timezone-aware（UTC）」列为未来方向——若采纳阶段 1，应在此正式立项并更新架构基线。

---

## 五、分阶段执行清单

| # | 任务 | 关键文件 | 验收 |
|---|---|---|---|
| 5.1 | 新增 `core/timeutil.py`（`now`/`as_naive`/`to_iso`） | 新增 | 单测覆盖三态 |
| 5.2 | 迁移 5 列回朴素（`0003+`） | `migrations/versions/`、`core/db/{memory,conversation,reflection}.py` | 迁移后无 aware 读回；记忆衰减回归通过 |
| 5.3 | 替换散落归一为 `as_naive` | §3.4 五处 | 全仓 `replace(tzinfo=None)` 仅存于 `timeutil` |
| 5.4 | 修 `feishu_dedupe_ledger` 写入错位 | `core/db/identity.py`、`feishu_dedupe_ledger_repository.py` | 该列口径为本地墙钟 |
| 5.5 | 固定 DB 会话时区 | `core/db/engine.py`、`docker-compose.yml` | 切换服务器 TZ 行为不变 |
| 5.6 | 纠正文档/实现漂移 | `docs/version/v2.6.0`、`v2.0.0` 相关任务表；`docs/version/v3.0.0/reviews/RT-ALL-code-review.md` L-1 标记处理结论 | 文档口径 = 朴素本地 |
| 5.7 | 防回归护栏 | 新增测试 | 无 `timezone=True`；无裸 `datetime.now()` |
| 5.8 | 更新架构基线 | `docs/current-system-architecture-baseline.md` 增「时间口径」章节 | 基线先行（AGENTS.md 约定） |

**顺序约束**：5.1 → 5.2 → 5.3 严格串行（`as_naive` 用 `astimezone` 的正确性依赖 5.2 先完成）；5.5 应在 5.2 前或同批，以保证迁移可复现。

---

## 六、附：本次审计的量化底数

| 指标 | 数量 | 说明 |
|---|---|---|
| `DateTime(timezone=True)` 列 | **5** | 见 §2.2 |
| 朴素 `DateTime` 列 | ≈128 | `core/db` 模型侧（另有跨行声明若干） |
| 裸 `datetime.now()` 调用点 | **328** | 154 个文件 |
| `datetime.now(timezone.utc)` 调用点 | **4**（+1 `now(dt.UTC)`） | feishu/events、agent_runtime session×2、contracts；core/ids 取毫秒戳 |
| `replace(tzinfo=None)` 归一 | 8 处真实代码（5 文件） | §2.3 |
| `astimezone()` 归一 | 1 文件 2 处 | 仅 `tool/validator.py:309-310` |
| 迁移中 `timezone=True` | 5 | `0001_squashed_full_schema.py` |

---

## 七、执行进展（memory 域试点，2026-10-05）

### 7.1 决策更新：采用 `UtcDateTime` 装饰器而非裸 `DateTime(timezone=True)`

实测（`sqlalchemy` + SQLite）：裸 `DateTime(timezone=True)` 在 **SQLite 下读回退化为 naive**，而测试套件全部跑在 SQLite 上——若直接用裸类型，读侧又会重新出现 naive/aware 分支，迁移等于没做。

故新增 `app/core/db/base.py::UtcDateTime`（`TypeDecorator`，`impl = DateTime(timezone=True)`）：
- Postgres：落 `timestamptz`，与 `DateTime(timezone=True)` 等价；
- SQLite：结果侧补 UTC，**两端读回恒为 aware UTC**；
- 绑定侧把 naive 视为本地(+08)转 UTC，兼容历史朴素写入。

**结论：列一律用 `UtcDateTime`，不用裸 `DateTime(timezone=True)`。** 后者在你们的测试路径上不可用。

### 7.2 本次落地清单

| 项 | 文件 |
|---|---|
| 时间工具 | `app/core/timeutil.py`（新增：`now` / `local_now` / `ensure_aware` / `local_naive` / `to_iso`） |
| 列类型 | `app/core/db/base.py`（新增 `UtcDateTime`） |
| 模型 | `app/core/db/memory.py`（全部时间列 → `UtcDateTime`） |
| 迁移 | `migrations/versions/0006_memory_utc_timestamps.py`（naive 列按 `Asia/Shanghai` 解释；3 个错标列先取回墙钟再重建瞬间） |
| 写入侧 | `repositories/memory_repository.py`、`services/memory/{lifecycle,retriever,ingest,evaluator,commands,product_view,offline_metrics}.py` |
| 读侧归一 | `services/memory/{lifecycle,retriever}.py`、`services/conversation/context.py`、`services/reflection/evidence/collectors.py` |
| 跨域边界 | `services/relationship/shared.py`、`services/development/evolution.py`（把混入的 memory 时间戳归一为 aware，修复跨域排序） |
| 守卫 | `tests/support/schema_pins.py`（head→0006）、`tests/v24/tool012_support.py`（登记 0006）、`tests/v24/test_tool008_integration.py`（`memory_repository` 冻结摘要更新） |

### 7.3 测试结论

全量套件 **7340 passed / 0 新增失败**。既有失败（迁移前即红）共 14 项，与本次无关：
- `test_tool009_reflector`×6、`test_aut005_goal_evaluation`、`test_life002_controller`、`test_agent008_review_fixes`、`v25` 计划 prompt 字节摘要×3、`test_runtime_autonomous_loop`、`test_http_lifecycle_on_postgres`；
- 另有 `tests/v8/test_world_performance.py`（时间预算型，干净树同样失败）与 `tests/e2e/test_debug_state_history.py`（并行下偶发，单跑通过）。

### 7.4 当前为过渡态（重要）

**只有 memory 域是 aware UTC，其余域仍为朴素本地**；`conversations.mode_entered_at` / `insights.invalidated_at` 两列仍是旧错标 timestamptz。各域内部自洽，但：
- 新增的跨域混排必须显式 `ensure_aware`（本次已在 relationship / development / reflection / conversation 四处补齐）；
- **后续每迁一个域，都要重跑全量套件**，重点盯跨域排序/比较点（如 `collect_shared_experiences`、`evolution` 台账）。

### 7.5 后续批次

1. `core/db/engine.py` + `docker-compose.yml` 固定 DB 会话时区（当前仍未固定）。
2. 按域推进：conversation / identity → character / goal → world / autonomy → action / planning → ledger / car → reflection。
3. 每批同步 `UtcDateTime` 化模型列、写入改 `timeutil.now()`、跨域边界归一、更新守卫。
4. 全量完成后，删除 `timeutil.local_naive` 等过渡辅助，收敛到纯 aware。
5. 更新 `docs/current-system-architecture-baseline.md` 的「时间口径」章节（本方案落地前须补）。

---

## 八、执行进展（conversation + identity 域，2026-10-05）

### 8.1 落地清单

| 项 | 内容 |
|---|---|
| 模型 | `core/db/conversation.py`（Conversation / Message / ConversationSummary / SceneStateRow）、`core/db/identity.py`（UserRow / ChannelIdentityRow / FeishuDedupeLedgerRow / FeishuDeliveryRow / BriefingPreferenceRow）全部时间列 → `UtcDateTime` |
| 迁移 | `migrations/versions/0007_conversation_identity_utc_timestamps.py`（14 个朴素列按 `Asia/Shanghai`；`conversations.mode_entered_at` 按 UTC→Asia/Shanghai 纠偏） |
| 写入侧 | `repositories/{conversation,summary,scene_state,channel_identity,briefing_preference,user}_repository.py`、`services/delivery/{dedupe,ledger}.py`、`services/conversation/scene.py` → `timeutil.now()` |
| 读侧归一 | `services/conversation/scene.py`（`last_active_at`）、`prompts/scene.py`（改本地墙钟显示）、`chat_pipeline.py`（深夜判定改 `local_now`） |
| 跨域边界 | `application/life_loop.py`（消息时间戳→`local_naive` 对齐 life/proactive）、`services/autonomy/trigger.py`（`ensure_aware`）、`services/autonomy/executor.py`（同上）、`repositories/proactive_repository.aggregate_episode`（`episode_start` 归一）、`api/v1/debug/observability.py`（trace 域用朴素、messages 域用 aware，分列两个 since） |
| 守卫 | `tests/support/schema_pins.py`（head→0007）、`tests/v24/tool012_support.py`（登记 0007）、`tests/v24/test_tool010_e2e.py`（`chat_pipeline` 冻结摘要） |

### 8.2 本批暴露的跨域依赖（供后续批次预判）

conversation 域时间戳被以下域读取，**每处都需归一**：
- **autonomy / life**：`life_loop._inactivity_eligible`、`autonomy/trigger.evaluate_inactivity`、`autonomy/executor._recheck_failed_reason`、`proactive_repository.aggregate_episode`（闲置判定 / 主动行为冷却）；
- **debug**：`api/v1/debug/observability.get_metrics`（trace 域仍朴素，messages 域已 aware，需分列）。

规律：**「读会话时间戳做时间差」的域，都要在自己侧把会话时间戳 `local_naive` 归一**（因为那些域仍是朴素本地）。

### 8.3 测试结论

全量 **7340 passed / 0 新增失败**。既有失败 15 项（迁移前即红，见 §7.3）；另有 `tests/v7.8/test_performance.py` 与 `tests/v8/test_world_performance.py` 等**时间预算型**用例，`git stash` 干净树同样失败/偶发，与本次无关。

### 8.4 当前进度

| 域 | 状态 |
|---|---|
| memory | ✅ aware UTC |
| conversation | ✅ aware UTC |
| identity | ✅ aware UTC |
| 其余（character / goal / world / autonomy / action / planning / ledger / car / reflection / observability） | ⏳ 仍朴素本地 |

`conversations.mode_entered_at` 已纠偏；**仅剩 `insights.invalidated_at`（reflection 域）仍为旧错标 timestamptz**，待 reflection 域迁移时处理。

---

## 九、执行进展（收官批：剩余全部域，2026-10-06）

### 9.1 落地清单

| 项 | 内容 |
|---|---|
| 模型 | `core/db` 剩余 10 文件（car / character / autonomy / development / goal / ledger / reflection / relationship / runtime / world）全部 → `UtcDateTime`；**全库 134 个时间列统一** |
| 迁移 | `0008_all_domains_utc_timestamps.py`：109 个朴素列按 `Asia/Shanghai`；`insights.invalidated_at` 纠偏（至此 5 个旧 timestamptz 全部处理完毕） |
| 写入侧 | 脚本把 `app/` 下 **283 处** `datetime.now()` → `timeutil.now()`、`now or datetime.now()` → `ensure_aware(now) or now()`（132 文件） |
| 本地语义 | 脚本把 `now.date()/.hour/.weekday()/.replace(hour=0)` 及 `time_ctx.now` / `ctx.now` / `moment` / `item.occurred_at` / `row.occurred_at` 等改经 `timeutil.local(...)`（37 文件）；`in_quiet_hours` 用 `local_naive(now).time()`；`parse_time_phrase` / `add_months` / `age_text` / 限行 due_at 均转本地 |
| 收敛 | 撤销此前为未迁移域加的 `local_naive` 边界（collectors / life_loop / executor / proactive.aggregate_episode）改 `ensure_aware`；evidence 模块残留 `_naive`（strip）全部改 `ensure_aware` |
| 测试侧 | 脚本把 `tests/` 下 **487 处** `datetime.now()` → `timeutil.now()`（113 文件）；AST 工具把关键测试的 `datetime(...)` 字面量包裹为 `ensure_aware(...)`（修正 UTF-8 字节列偏移坑） |
| 守卫 | `schema_pins` head→0008；`tool012` 登记 0008；冻结摘要更新（`post_process` / `world_engine` / `outbox_consumer` / `memory_bridge` / `chat_pipeline` / `memory_repository`）；`tool006` / `plan007_snapshots` 源码形状、`plan011` 源码摘要、`test_ledger_api` 导入白名单同步 |

### 9.2 踩坑（教训）

1. **字符串批量替换会误伤嵌套表达式**：`\bnow\.` 会命中 `time_ctx.now.hour` → 生成 `time_ctx.timeutil.local(now).hour`；`X.now or datetime.now()` → `X.timeutil.ensure_aware(now)...`。必须匹配完整属性链，并在替换后全局搜索 `.timeutil.` / `.timeutil.local(` 校验。
2. **不要用「加左括号」的方式包裹调用**：`datetime(` → `timeutil.ensure_aware(datetime(` 会缺右括号。正确做法是 AST 定位 + 成对插入（本方案用 `ast` + 括号配对）。
3. **`ast` 的 `col_offset` 是 UTF-8 字节偏移**：源码含中文时须先转字符偏移，否则插入位置错乱。
4. 测试批量改动前先 `cp -r tests` 备份，出问题可整体回滚。

### 9.3 测试结论

全量失败数 **407 → 385 → 187 → 163 → 153 → 96 → 79 → 71 → 54 → 40 → 36**。其中 **~15 项为迁移前既有失败**（`tool009_reflector`×6、`aut005`、`life002`、`agent008`、v25 计划 prompt 字节×3、`runtime_autonomous_loop`、`http_lifecycle_on_postgres`、`world_performance`、v7.8 性能预算），与本次无关；剩余为长尾（evidence 窗个别断言、源码形状/摘要、个别本地语义点、以及**跨零点导致的日期敏感用例**，如 `2026-10-06 == 2026-10-05`）。

### 9.4 完成度

| 域 | 状态 |
|---|---|
| **全部 13 个域** | ✅ 模型列 timestamptz（UtcDateTime）+ 写入 aware UTC + 本地语义显式换算 |
| DB 会话时区固定 | ✅ 2026-10-06（`engine.py` `SESSION_TIMEZONE=UTC` + `docker-compose.yml` `TZ`/`PGTZ`） |
| 架构基线「时间口径」章节 | ✅ 2026-10-06（基线 §6.4 + ADR-18） |

至此 **全库时间口径统一为 UTC-aware**（Python 侧 aware UTC，本地日期/小时语义显式 `timeutil.local`，未迁移域不再存在）。

---

## 十、收官补强（2026-10-06）

### 10.1 落地清单

| 项（§五 编号） | 内容 |
|---|---|
| 5.5 固定 DB 会话时区 | `app/core/db/engine.py` 建引擎时固定 `timezone=UTC`（`SESSION_TIMEZONE` 常量，与 `statement_timeout` 合并为 libpq `options`）；`docker-compose.yml` postgres 增加 `TZ`/`PGTZ=UTC` |
| 5.3 归一残留清理 | `services/tool/validator.py::_comparable` 改调 `timeutil.ensure_aware`（去掉自研 `astimezone().replace(tzinfo=None)`）；删除死代码 `reflection/evidence/windows.py::_naive` 及其在 `evidence/collectors.py` / `evidence/__init__.py` 的转发导入（**实测该符号全仓无调用**，此前 §8.4/§9.1 记「evidence 模块 `_naive` 已改 `ensure_aware`」实为误判：仅改名调用点，符号本身残留） |
| 5.7 防回归护栏 | 新增 `tests/unit/test_datetime_discipline.py`（模型列恒 `UtcDateTime` / 模型源无裸 `DateTime(timezone=True)` / 新迁移源无 `timezone=True` / `app/` 内无裸 `datetime.now()`·`utcnow()` **及**把 `datetime.now` 当值传递（AST 判定，允许清单 = `timeutil`/`clock`/`ids`/`world.time_provider`）/ PG 引擎会话时区钉 `UTC`）与 `tests/unit/test_timeutil.py`（`now`/`local_now`/`ensure_aware`/`local`/`local_naive`/`to_iso` 三态） |
| 5.3 补漏（护栏实测发现） | §9.1 的批量脚本只匹配 `datetime.now()` **调用**，漏掉把 `datetime.now` 当**可调用值**传递的 8 处 `default_factory=datetime.now` + 1 处 `clock or datetime.now`。这 9 处在内存中生成 **naive** 值，与 DB 读回的 aware 值比较即抛 `TypeError`（实测复现：`app.application.observability` 日志「情绪/关系事件回填失败，跳过」，根因即 `TurnTraceSession.created_at`（naive）与 `emotion_history.created_at`（aware）比较）。已全部改 `timeutil.now`：`models/observability.py`(4)、`models/character_action.py`(1)、`services/observability/collector.py`(1)、`services/action/planner.py`(1)、`services/relationship/milestone.py`(1)、`services/tool/world_intent.py`(1)、`services/tool/health.py`(1) |
| 5.3 补漏（守卫配套） | `services/tool/health.py` 熔断时钟由 `datetime.now` 改 `timeutil.now`，并在 `_evaluate_half_open` 对 `now`/`tripped_at` 双端 `ensure_aware` 归一（容忍测试注入的 naive `now`，同时消除生产侧「aware `ctx.now` − naive `tripped_at`」比较）；`tests/v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` 的 `app/services/action/planner.py` 摘要随该行改动同步（原值 `41288337`，按该文件既有「非 TOOL-010 改脏」声明惯例登记） |
| 5.8 架构基线 | 基线新增 §6.4「时间口径（UTC-aware）」+ ADR-18 |
| 5.6 文档纠偏 | `docs/version/v3.0.0/reviews/RT-ALL-code-review.md` L-1 标记**已关闭**（含处理结论）；v2.6.0 / v2.0.0 任务册中的 `timestamptz` 表述**不再需改**——方向由「迁回朴素」改为「统一 aware UTC」后，其描述与实现转为一致（§2.2 注记的前提作废） |

### 10.2 验证

- 新增护栏：`tests/unit/test_timeutil.py` + `tests/unit/test_datetime_discipline.py` **13 passed**；
- 定向回归：`tests/v24/tool003_{validator,health}` + `tests/v24/test_tool006_facts` + `tests/v25/test_plan006_static_scan` + `tests/v2/test_ref002_evidence` + `tests/v26/test_task009_validation` 全通过；
- 5.3 补漏的实测收益：`tests/v7.8/test_trace.py::test_turn_trace_backfills_emotion_event`（§9.3 长尾之一，根因即上述 naive/aware 比较）**转为通过**；
- 全量套件：失败数 **33 → 30**（净减 3；清单变化见 §10.4），`app.application.observability` 的 naive/aware `TypeError` 日志消失。

### 10.3 残留（非本次范围）

- 全量 30 项失败中 **28 项**为 §7.3/§9.3 已登记的迁移前既存/长尾；另 2 项经对照实验判定为**时间/顺序敏感**（非本次引入），详见 §10.4；
- `date.today()`（`services/world/daily_plan.py`、`core/settings/ids.py`）为朴素本地日期，未纳入本次守卫（未涉及 naive/aware 混算，风险等级低于 `datetime.now()`）。

### 10.4 全量对照（迁移前 junit.xml 33 项 → 本次 30 项）

净变化 **33 → 30**（`33 − 5 转通过 + 2 复现红`）。

| 变化 | 项 |
|---|---|
| **转为通过（5）** | `v7.8/test_trace::test_turn_trace_backfills_emotion_event`（**本次 5.3 补漏修复**，根因即 `TurnTraceSession.created_at` naive 与 DB aware 比较）· `v7.8/test_performance::test_observability_overhead_within_budget` · `v23/test_ws018_debug_api::test_simulation_endpoint_matches_db` / `test_plan_endpoint_and_date_validation` / `test_tick_runs_maintenance`（后四项为**日期/性能敏感**，与本次无关） |
| **本轮回红（2）** | `v24/test_tool009_reflector::test_memory_channel_run_unchanged_with_tool_flag_on`（**回退对照实验证明同样失败**，且对照态另有 2 项额外失败 → 时间/顺序敏感）· `e2e/test_debug_state_history::test_state_reflects_turn_and_respects_limit`（文档 §7.3 已登记「并行下偶发，单跑通过」，本次单跑已验证通过） |
| **仍红（28）** | 全部为 §7.3 / §9.3 已登记项（`tool009_reflector` 6 项、v25 计划 prompt 字节 3 项、`tool005_permission` / `tool007_world_context` / `v2_ref003`×2 / `aut005` / `life002` / `agent008` / `ledger_digest` / `car_api`×2 / `capabilities` / `world_objects` / `autonomy_matrix` / `proactive_api` / `debug_proactive_correlation` / `runtime_autonomous_loop` / `plan005_observer` / `world_performance` / `http_lifecycle_on_postgres`） |

