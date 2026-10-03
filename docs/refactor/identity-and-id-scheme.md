# 后端 ID 体系审查与雪花 ID 落地方案

> 范围：`apps/backend` 全量 ID 生成点（身份 + 55 张表主键）
> 策略基线：**直接采用雪花 ID**（不经过「自增前期」）
> 审查日期：2026-10-03 ｜ 状态：**发号模块已落地，表结构迁移待执行**

---

## 0. 结论

| 决策项 | 结论 |
|---|---|
| 生成策略 | **直接上雪花 ID**，不做自增过渡 |
| 实现方式 | **`sonyflake` 2.0.3**，禁止自研位运算 |
| epoch | **2026-01-01T00:00:00Z** |
| 位分配 | 41 时间 / 12 序列 / 10 机器，时间单位 **1ms** |
| 容量 | 4096 ID/毫秒/机器，1024 个机器位 |
| 寿命 | **可用至 2095-09-07**（69.7 年） |
| 回拨防护 | 库内单调逻辑时钟 + 跨重启水位校验 + 部署侧 NTP 约定 + DB 唯一约束兜底 |
| 列类型 | **保持 `VARCHAR`**，存雪花十进制串。**B2（翻转 `BIGINT`）经评估后决定不做**，依据见 §6.5 |
| 对外类型 | ID 一律以**字符串**出现在 JSON —— 雪花 ID 57+ 位，超出 JS 安全整数范围约 11 倍，数字形式会被前端静默截断 |

**已完成（B1）**：发号模块 `app/core/ids.py`、配置域 `app/core/settings/ids.py`、`app/main.py` 接线、
`tests/unit/test_ids.py`（22 项）；**身份域改用雪花**——`user_service` 改为凭据绑定驱动、
`channel.resolve()` 补建 `users` 行、`channel_identities` 成为全通道统一绑定表（迁移 `0004`）、
架构基线已同步（ADR-16）。
**已完成（C1）**：`car_*` / `ledger_accounts` / `ledger_categories` / `life_tasks` 的 **8 处内嵌 `user_id`
主键全部收敛为雪花**（P0-4 主体，见 §5.3；原记 9 处系计数口径误差，实测 8 处调用点）。
**已取消（B2）**：列类型翻转 `VARCHAR → BIGINT`，评估后决定不做（见 §6.5）。
**已完成（C3）**：全 app `uuid.uuid4()` 生成点 **52 处**全部收敛 `ids`（前缀裁决：**去掉**，见 §5.4）。
**已完成（C2）**：`worlds.id` 新世界发雪花、存量行保留 `home:{user_id}`，`world_id_for` 退役改查库（见 §6.5）。
**待办（D）**：5 张例外表拆分 + 2 张自增表收敛（§6.5 D）。

---

## 1. 库选型（6 个候选实测对比）

逐个下载源码审查（`uv pip install --target` + 读源码），不看文档只看实现：

| 库 | 版本 | 时钟回拨行为 | 并发锁 | 自定义 epoch | 结论 |
|---|---|---|---|---|---|
| `snowflake-id` | 1.0.2 | ❌ **静默返回 `None`** | ❌ 无 | ✅ | 否决 |
| `snowflake-py` | 1.0.0 | ❌ **完全无保护**，`_count % 4096` 会重复 | ❌ 无 | ✅ | 否决 |
| `pydantic-snowflake` | 0.1.3 | ❌ 回拨后重置序列 → 重复 | ❌ 无 | ✅ | 否决 |
| `pysnowfall` | 1.0.0 | ✅ 抛 `ErrorSettingTimestampException` | ❌ 类级全局状态，无锁 | ✅ | 否决 |
| `snowflakekit` | 0.1.1 | ✅ 抛 `RuntimeError` | ⚠️ 仅 `asyncio.Lock`；默认 `epoch=None` 会崩 | ✅ | 备选 |
| **`sonyflake`** | **2.0.3** | ✅ **单调逻辑时钟，ID 时间不回退** | ✅ `aiologic.Lock`（同步/异步通用） | ✅ | **选定** |

**为什么淘汰 `snowflake-id`**（下载量最大的那个）：它在时钟回拨时 `return None`（`snowflake/snowflake.py:126`），而不是抛异常。调用方拿到 `None` 后写进主键/传给下游，报错位置离根因极远；更糟的是它**无法区分**「回拨」和「序列耗尽」——两者都返回 `None`，外层包装无法施加不同策略。且它无锁，FastAPI 多线程下会重复。

**为什么选 `sonyflake`**：它用 `_elapsed_time` 单调递增而非直接读墙钟（见 §2），并且 `aiologic.Lock` 同时覆盖 `next_id()` 与 `next_id_async()` —— 这正是 FastAPI（async 端点 + 线程池混用）需要的。

---

## 2. sonyflake 的回拨处理为什么是对的（实测证据）

核心机制（`sonyflake/sonyflake.py:325-352`）：

```
current = 当前墙钟的 elapsed
if _elapsed_time < current:      # 正常前进
    _elapsed_time = current; _sequence = 0
else:                            # 时钟停滞或回拨
    _sequence += 1
    if _sequence 溢出:            # 借位到未来并等真实时间追上
        _elapsed_time += 1
        sleep(到该逻辑时刻)
```

即 **`_elapsed_time` 只增不减**：时钟回拨时 ID 时间不跟着回退，而是靠序列号继续发号；序列耗尽则「借位」到未来并短暂 sleep。这从根本上消除了「回拨 → 时间戳重复 → ID 重复」。

实测结果（本仓库 `.venv`，monkeypatch `_utcnow` 模拟时钟）：

| 场景 | 结果 |
|---|---|
| 正常生成 1000 个 | 去重 1000，单调递增，最大位宽 57（< 63） |
| 同毫秒生成 5 个 | 5 个互异，解码时间相同，序列 1000→1004 |
| **时钟回拨 5 秒**后生成 50 个 | **无重复**，仍单调，解码时间**不回退** |
| **时钟回拨 1 小时**后生成 50 个 | **无重复**，仍单调，解码时间不回退 |
| 时钟完全冻结下生成 5000 个（容量 4096/ms） | **无重复**，借位 1ms |

---

## 3. 参数决策

```python
Sonyflake(
    start_time=datetime(2026, 1, 1, tzinfo=UTC),
    bits_sequence=12,      # 4096 ID/毫秒/机器
    bits_machine_id=10,    # 1024 台机器
    time_unit=timedelta(milliseconds=1),
    machine_id=<IDS_MACHINE_ID>,
)
```

- `time_bits = 63 - 12 - 10 = 41`（**由库计算，不是我们写死的**）。41 bits @1ms = `2199023255551` ms → epoch 2026-01-01 起 **可用至 2095-09-07**。
- 为什么时间单位用 1ms 而非库默认的 10ms：与 Twitter 雪花语义一致，ID 可直接反解到毫秒；10ms 虽然寿命 ×10，但对本应用无必要。
- 为什么 12/10 而非库默认 8/16：本应用 QPS 极低，4096 ID/ms 是天文数字般的余量；把多出来的位给机器位意义不大，而 41 bits 时间位换来的 69.7 年寿命更实际。
- ⚠️ **改 `bits_sequence` 或 `bits_machine_id` 会连带改变 `time_bits` 和寿命**，调整前必须重算。
- ⚠️ **epoch 一旦有数据落库就不能再改**（改 epoch 会让新旧 ID 的时间轴错位、并可能撞号）。当前 epoch 是**一次性决策**。

---

## 4. 时钟回拨防护（四层）

### L1 — 进程内：库已提供，零成本

sonyflake 的单调 `_elapsed_time`（§2）。覆盖所有 NTP 微调、手动小幅调整场景。**已实测验证。**

### L2 — 跨进程重启：本项目实现（库管不了）

`sonyflake` 的状态全在内存，**进程重启后 `_elapsed_time` 归零**，会重新从墙钟取值。若重启时墙钟已被回拨（虚拟机快照恢复、手动改时间、容器迁移到时间偏慢的宿主机），就会在「过去的时刻」重新发号 → 与历史 ID 撞号。

实现（`app/core/ids.py`）：

1. 内存维护 `_high_water_ms` = 已发放 ID 的最大**逻辑**时间（由 `decompose(value).time` 反解，不是墙钟）。
2. 周期性（`IDS_HIGH_WATER_FLUSH_SECONDS`，默认 5s）与进程正常关停时，把水位写入 Redis（key = `ids:high_water_ms:{machine_id}`，**按机器隔离**）。
3. 启动时 `startup_guard()`：读回水位，若 `now_ms < 水位 - tolerance` → **抛 `ClockRollbackError` 拒绝启动**，而不是静默发号。
4. 写入用「只增不减」语义（先读再比大小），避免并发/乱序覆盖把水位写小。
5. Redis 未配置或读写失败时**降级为跳过校验并告警**，不阻塞启动（与项目对 Redis 的既有定位一致）。

**残余风险（必须知道）**：水位是「已发放最大值」的**下界**，写入间隔内的增量尚未持久化。若「进程崩溃 + 立刻重启 + 时钟回拨」同时发生，且回拨幅度**小于写入间隔（5s）**，校验可能漏过。缓解手段：
- 把 `IDS_HIGH_WATER_FLUSH_SECONDS` 调到 `1`（代价：Redis 写入频率上升）；
- **最终兜底是 DB 主键唯一约束**（见 L4）——真撞号会 `IntegrityError` 而非静默写坏数据。

### L3 — 部署侧约定（运维）

- 容器与宿主机**必须启用 NTP**（`chrony` / `systemd-timesyncd`），并**只允许 slew 平滑调整，禁止 `ntpdate` 式跳变**。
- **禁止**用「暂停/恢复虚拟机快照」的方式回滚生产实例。
- 多实例扩容时 `IDS_MACHINE_ID` 必须**互不相同**（0~1023），且**同一个 machine_id 不得同时被两个实例使用**——这是雪花 ID 唯一的正确性前提。机号分配约定：**0 = 默认应用实例；1023 = 迁移回填专用（保留）；1~1022 = 扩容可用**。
- 监控项：`ids:high_water_ms:{machine_id}` 与墙钟的差值，出现「水位 > 墙钟」即告警。

### L4 — 双保险：DB 唯一约束

主键本身就是最后一道防线。**禁止**在 ID 冲突时静默重试或忽略——那会掩盖时钟问题，必须让 `IntegrityError` 暴露出来。

---

## 5. 已落地实现

### 5.1 发号与防护（B1-a）

| 文件 | 内容 |
|---|---|
| `app/core/settings/ids.py` | `IdsSettings`：`ids_epoch_date` / `ids_machine_id` / `ids_high_water_key` / `ids_high_water_flush_seconds` / `ids_clock_rollback_tolerance_ms` + 校验（epoch 不得未来化、machine_id ∈ [0,1023]） |
| `app/core/ids.py` | `new_id()` / `new_id_async()` / `startup_guard()` / `flush_high_water()` / `run_high_water_flusher()` / `ClockRollbackError` |
| `app/main.py` | lifespan 启动时 `await id_service.startup_guard()`；起 `run_high_water_flusher()` 后台任务；关停时 cancel + `flush_high_water()` |
| `tests/unit/test_ids.py` | 22 项：位分配 / epoch / 唯一性 / 单调性 / int64 位宽 / 同步异步共序列 / 进程内回拨 / 逻辑时间不回退 / 序列耗尽借位 / 水位单调 / 启动守卫拒绝与放行 / 水位持久化 / 机器隔离 / 设置校验 |

### 5.2 身份域改造（B1-b）

| 文件 | 内容 |
|---|---|
| `app/services/identity/user_service.py` | 删除凭据派生（`email_user_id` → 更名 `legacy_email_user_id`，仅供旧库迁移脚本复现）；`find_or_create_by_email` 改为**绑定驱动**：先查 `channel_identities(channel='email')`，命中即返回其 `user_id`，未命中才建 `users` 行（雪花 id）+ 写绑定行；新增 `create_user()` 供通道侧补建用户；**修复「绑定行存在但 users 行缺失」的悬空绑定**（改走 `update_identity` 回填） |
| `app/services/identity/channel.py` | 删除 `build_internal_user_id`（`feishu:{open_id}` 派生）；`resolve()` 改为「先查绑定 → 未命中则建 `users` 行 + 建绑定」，`internal_user_id` 返回真实 `users.id`；`build_session_id`（`{channel}:{external_id}`）保留给**会话**，语义不变 |
| `app/repositories/user_repository.py` | 新增 `create()`（无邮箱的通道用户） |
| `app/repositories/channel_identity_repository.py` | `get_or_create` 的 `session_id` 改为可选 |
| `app/core/db/identity.py`（db 已拆包，原 `db.py`）+ 迁移 `0004` | `channel_identities.session_id` 改为可空（邮箱绑定行无会话概念）。迁移用 `batch_alter_table` 以兼容 SQLite（其不支持 `ALTER COLUMN ... DROP NOT NULL`） |
| `tests/` | `test_channel_identity.py`（+3 项：resolve 建用户行、改绑邮箱不换人、跨通道共享同一 user）、`test_feishu_identity.py`、`test_email_login.py`、飞书四个集成测试文件全部改为按解析结果断言 |

**B1 实际达成的能力**（对应 §1 的四类问题）：

| 原问题 | B1 后的状态 |
|---|---|
| P0-1 改绑邮箱即换人 | ✅ **已修**：`user_id` 不由凭据派生，改绑 = 更新绑定行（测试 `test_email_rebind_keeps_user_id`） |
| P0-2 跨通道无法归一 | ✅ **基础设施已就位**：飞书身份现在有真实 `users` 行，同一人可挂多行绑定（测试 `test_cross_channel_binding_shares_one_user`）。**显式「绑定账号」入口尚未实现**——不自动按邮箱合并（那会变成凭邮箱猜测身份的越权口子） |
| P0-3 `user_id` 可反推 | ✅ **已修**：雪花 ID 不可由邮箱反推（但引入可枚举性，见 §7） |
| P0-4 业务主键内嵌 `user_id` | ⚠️ **未动**：`car_profile_{user_id}` / `task_{user_id}_{ms}` / `worlds.id = home:{user_id}` 仍在（B2 一并处理） |

新增配置项（环境变量名 = 字段名大写，无 alias 层，符合 `AGENTS.md`）：

```
IDS_EPOCH_DATE=2026-01-01
IDS_MACHINE_ID=0
IDS_HIGH_WATER_KEY=ids:high_water_ms
IDS_HIGH_WATER_FLUSH_SECONDS=5
IDS_CLOCK_ROLLBACK_TOLERANCE_MS=0
```

验证结果：`tests/unit` 1551 项、`tests/e2e` 179 项全绿。

### 5.3 实体主键去内嵌 user_id（C1，P0-4 主体）

| 文件 | 改动 |
|---|---|
| `app/core/ids.py` | 新增 `new_id_str()`：`VARCHAR` 列与 API 出参用的字符串出口 |
| `app/repositories/car_repository.py` | `_new_id(prefix, user_id)` → `_new_id()`（无参）；`car_profiles.id` / `car_loans.id` / `car_service_records.id` / `car_mileage_logs.id` 共 4 处改雪花；移除不再使用的 `from uuid import uuid4` |
| `app/repositories/ledger_repository.py` | `ledger_accounts.id`（含 `cash_default` 种子账户）/ `ledger_categories.id` 共 3 处改雪花 |
| `app/repositories/life_task_repository.py` | `life_tasks.id` 改雪花 |
| `tests/v24/tool011_security.py` | `EXPECTED_TASK_GLOBALS` / `EXPECTED_CREATE_TASK_COUNT` 登记新增的 `_ids_watermark_task`（4→5），附理由 |
| `tests/v24/tool012_support.py` | `INCREMENTAL_MIGRATION_FILES` 补 `0004`；`SCHEMA_COLUMNS_DIGEST_BASELINE` 更新并登记为**基线表的有意演进**（迁移 `0004` 放开 `channel_identities.session_id` 可空） |
| `tests/v51/test_car_schema.py` | `test_migration_chain_head_is_still_0003` → `test_migration_chain_head_matches_pin`，改走 `MIGRATION_HEAD` / `MIGRATION_HEAD_PARENT` 常量（去掉过期版本字面量） |

**验证**：全量 `pytest tests` = **7312 passed / 15 failed**，其中 15 项与 pre-B1 基线（17 项）**同类**，均为既有失败
（含 3 个按耗时预算的 flaky 用例，逐次运行有出入）。**本次改动零新增失败。**

> ⚠️ **回归口径教训（重要）**：本仓 `pyproject.toml` 的 `testpaths = ["tests"]`（7329 项），
> 而 `tests/v*`（约 5100 项）**不在** `tests/unit|integration|e2e` 这三个**目录**之内。
> `tests/conftest.py::pytest_collection_modifyitems` 的自动打标规则里，未命中 unit/integration
> 目录且无 `db_session_factory` / `asgi_transport` 的用例会落到 **`integration` marker** ——
> 所以正确的层级命令是**按 marker** 的 `pytest -m integration`，而**不是按路径**的
> `pytest tests/unit tests/integration tests/e2e`。
> B1 提交时误用了后者，漏掉 4 个回归（`v24` tool011/tool012、`v51` car_schema），后于 C1 一并修复。
> **改 DB / 迁移 / 跨模块时一律用 `pytest -m integration`；阶段完成用 `pytest`。**

---

## 5.4 残余 uuid4 生成点收敛（C3）

| 文件 | 改动 |
|---|---|
| `app/models/*.py`、`app/application/*.py`、`app/services/**`、`app/repositories/*.py`、`app/api/v1/chat.py` | `uuid.uuid4()` 默认主键/记录 id → `ids.new_id_str()` 共 **52 处**。生成点分布实测与原估相反：仓储层早已无 uuid4，**大头在 models 的 pydantic 默认值与应用服务层**（原估「约 23 处仓储级」落空） |
| `app/services/observability/collector.py` | `begin_trace` 的内存 pending key 一并收敛（非主键、不落库，按验收口径 2 本可豁免；归一后全 app 无 uuid4） |
| `tests/v24/test_tool010_e2e.py` | `chat_pipeline.py` 冻结哈希再冻结，注明 ADR-16 C3 有意改脏 |
| `tests/e2e/test_trace_collector.py`、`tests/e2e/test_debug_correlation.py` | request_id 断言 `len == 32` → 雪花数字串（`isdigit()`） |
| `tests/v26/test_acceptance.py`、`tests/unit/test_character_action_models.py` 等 | 前缀/长度断言改数字串口径（`startswith("act_")` → `isdigit()`） |

**过程教训（重要）**：本批次的批量替换曾把 `from app.core import ids` 错插进**多行 import 括号内**，
10 个文件语法损坏、pytest collection 直接失败。已修复（移出至该 import 块闭合后）。
**教训：机械批量加 import 必须以 AST / 全量语法检查收尾，且全量回归结果要读日志本体，不能信管道 exit code。**

**验证**：全量 `pytest` = **7312 passed / 15 failed**，失败清单与 C1 基线**逐项同类**
（tool009 ×6 / v25 ×3 / v30 / aut005 / life002 / agent008 / http_lifecycle / 耗时 flaky），**零新增失败**。

---

## 6. 剩余迁移（表结构）

### 6.1 55 张表的主键形态分布（实测）

| 类别 | 数量 | 说明 |
|---|---|---|
| 代理主键 `id`，**String** | **45** | 迁移主体 |
| 代理主键 `id`，int 自增 | 2 | `messages`、`emotion_history`（**需一并改为雪花**，否则两套 ID 语义并存；归入阶段 D） |
| 自然主键（非 `id`） | 7 | `user_id` × 3、`session_id`、`event_id`、`idempotency_key` |
| 复合主键 | 1 | `channel_identities (channel, external_id)` |

> **B1 后的现状**：`users.id` 与 37 张表的 `user_id` 列**仍是 `VARCHAR`**，值为雪花十进制串；
> `users` 表本身不在上表的 45 张里（它是「自然主键」类之外的独立一项，见基线 §6.1）。
> 列类型翻转属 B2。

### 6.2 不能直接换成雪花的 5 张表

它们的主键语义是「幂等键 / 外部 ID / 派生查找键」，必须**拆成「雪花 ID + 业务唯一键」两列**。列类型一律维持 `VARCHAR` 存雪花十进制串（B2 取消裁决的延伸：这些表都承载历史非数字数据，翻 `BIGINT` 需重映射，且会牵连 FK 列类型连锁翻转）：

| 表 | 现主键 | 处理 |
|---|---|---|
| `feishu_dedupe_ledger` | `event_id`（外部事件 ID） | 加雪花 `id` 作主键，`event_id` 转业务唯一键；存量行由迁移回填 |
| `feishu_deliveries` | `idempotency_key` | 同上 |
| `conversations` | `id` = `session_id`（**客户端传入**） | 新增 `session_id` 列（存量回填 = 旧 id）+ UNIQUE；**存量行 id 保留旧会话串**（与 users 存量保留同构，避免 FK 重映射手术），新会话 `id` = 雪花、查找按 `session_id` 业务键 |
| `worlds` | `id` = `home:{user_id}` | 新世界 `id` = 雪花，查找一律按 `user_id`（表**无 `kind` 列**、`user_id` 已 UNIQUE——原方案写 `UNIQUE(user_id, kind)` 系笔误）；**存量行 id 保留**，子表隐式引用不受影响 |
| `ledger_categories` | 种子 `cat_seed_{user_id}_{name}` | 加 `seed_key` 列（播种原始名，业务唯一键）+ 雪花 id（含种子行）；`get_category(seed_id)` 改按 `seed_key` 查 |

### 6.3 隐式引用列（无 FK 约束但需同步改类型）

约 10 个：`goal_id`、`request_id`、`action_id`、`memory_id`、`related_memory_id`、`insight_id`、`source_insight_id`、`subject_id`、`account_id`、`record_id` / `target_record_id`。
全仓仅 6 处显式 `ForeignKey`（3 处指向 `conversations.id`，3 处在 `ledger_*` 内部）。### 6.4 列类型写法

```python
id: Mapped[int] = mapped_column(
    BigInteger().with_variant(Integer, "sqlite"),
    primary_key=True,
)
```

**不需要 `Identity` / `autoincrement`** —— 雪花值由应用层生成后显式写入。
但 SQLite 变体**必须保留**：本项目用 SQLite 跑迁移钉测，而 SQLite 只把声明类型恰为 `INTEGER` 的主键当 rowid 别名，`BIGINT` 不行（实测：`BigInteger()` 建表能成功，插入时报 `NOT NULL constraint failed`，属「测试绿、生产红」型陷阱）。

### 6.5 执行顺序

| 阶段 | 内容 | 风险 |
|---|---|---|
| **A（已完成）** | 发号模块 + 配置 + 接线 + 单测 | 零 |
| **B1（已完成）** | 身份域改用雪花：`user_service` 绑定驱动、`channel.resolve()` 补建 `users` 行、`channel_identities` 统一绑定表、迁移 `0004`、基线 ADR-16 | 低（`user_id` 的 Python/API 类型未变 → **无 token 失效**） |
| **B2（评估后不做）** | 列类型翻转 `VARCHAR → BIGINT` + Python 类型翻转。**结论：收益不抵成本**，详见下方 |
| **C1（已完成）** | **P0-4 主体**：`car_*`（4 处）/ `ledger_accounts`（2 处）/ `ledger_categories`（1 处）/ `life_tasks`（1 处）共 **9 处内嵌 `user_id` 的主键**收敛为雪花；`ids.new_id_str()` 为 `VARCHAR` 列/API 提供字符串出口 | 低（**测试侧零字面量依赖**，已实测） |
| **C2（已完成）** | `worlds.id`：新世界发雪花，**存量行 id 保留 `home:{user_id}`**（零数据迁移、零子表重映射）。`world_id_for` 纯函数退役改查库：被 3 个读路径调用（`memory/sources`、`relationship/shared`、`world_engine`）+ 仓储内 3 处，世界未建立返回 `None`（读路径空返回语义不变）；测试侧 35 处 `world_id_for` 引用同步改写（其中 `v50` 迁移脚本测试保留 `home:` 字面量——脚本只改写存量格式）。无 schema 迁移（`user_id` 已 UNIQUE）；基线已先行更新；tool007 冻结哈希再登记 | 中 |
| **C3** | 全 app `uuid.uuid4()` 生成点 → 雪花。**实测 52 处**（原估「约 23 处仓储级」严重偏低：生成点跨 models/application/services/repositories/api，不止仓储层）。前缀裁决：**去掉**（与 `user_id` 一致）；测试侧格式断言同步改（`startswith("act_")` → `isdigit()`、`len == 32` → `isdigit()`）；`collector` 内存 trace key 一并收敛 | 低 |
| **D** | §6.2 五张例外表拆分（雪花 ID + 业务唯一键）+ `messages` / `emotion_history` 两张 int 自增表改雪花（`BigInteger().with_variant(Integer, "sqlite")` + 显式 `autoincrement=False`，防 BIGSERIAL 渲染坑）。迁移内回填发号用**保留机号 1023** 的独立 Sonyflake 实例，不与应用实例撞号 | 中 |

> **C1 的一处例外**：`ledger_categories` 的**种子** id 保留确定性（`cat_seed_{user_id}_{原始名}`），未随 C1 改雪花。
> 原因：该 id 承担**跨重命名的稳定身份**——用户把「餐饮」改成「吃饭」后重跑播种，不能把原分类复活
> （`tests/v40/test_ledger_repository.py::test_seed_does_not_overwrite_user_renamed_category` 即此契约）。
> 直接换成随机雪花会破坏它；正确解法是引入 `seed_key` 列（雪花 id + 业务唯一键），归入阶段 D。
> 该处已加代码注释说明，避免后人误改。

#### B2 为什么不做（2026-10-03 评估，含实测）

原方案把「列类型翻 `BIGINT`」列为待办。动手实现后（`SnowflakeId` 类型装饰器 + 迁移 `0005` + 38 列改写）实测，发现**收益远小于预期**：

| 维度 | 结论 |
|---|---|
| 存储 | `VARCHAR(19)` vs `BIGINT(8)` 单行差 11 字节；`users` 规模 ~10¹~10² 行 → **总差异 < 2KB**，可忽略 |
| 索引性能 | 本项目 QPS 与行数下无实测差异 |
| **对外契约** | **两种方案完全一致** —— ID 都必须以字符串出 JSON（JS 精度），无任何差异 |
| 唯一真实收益 | 数据库在**类型层强制「ID 必须是数字」** |

成本侧（实测）：

- **584 处**非数字 `user_id` 字面量分布在 **180 个测试文件**（191 个不同字面量：`"u1"` 203 处、`"u"` 46 处、`"default-user"` 29 处…）。`TEST_USER_ID = "default-user"` 是 conftest 里**刻意保留的历史字面量**（注释明确说明是为免改 ~300 处世界域夹具），翻转后必须全部改成数字，**测试可读性显著下降**。
- 历史口径 `email-<sha256[:16]>` / `feishu:{open_id}` 非数字、无法 `CAST`，翻转要求**删库重建** —— 而 B1 刚建立的「存量用户下次登录自动回填绑定」自愈路径会被这条前提作废，两者自相矛盾。
- 实现过程中还踩到两个坑（已记录，供未来重启该议题时参考）：① `BigInteger` 单列主键会被 SQLAlchemy 渲染成 **`BIGSERIAL`**（凭空造序列），必须显式 `autoincrement=False` —— `users.id` 与 `briefing_preferences` / `character_state` / `relationship_state` 三张「`user_id` 即主键」的表都会中招；② 36 个 `user_id` 列里有 1 个是 `Mapped[str | None]`（`loop_runs.user_id`），按 `Mapped[str]` 批量替换会漏掉。

**决策**：保留 `VARCHAR`。若将来确实需要「ID 必须是数字」的强约束，**应加在应用边界而非列类型**（写入前校验 + 一条拒绝非数字 ID 的测试），成本从 584 处降到 1 处。若未来要重启列翻转（例如阶段 C 之后表结构本就大改），上述两个坑与清单可直接复用。

> 阶段 C / D 会新建或重建主键，届时若那些表**只存雪花 ID、无历史非数字数据**，可以按表就地用 `BIGINT`（不受本决策约束）—— 本决策只针对**已承载历史口径**的 38 个身份列。

每阶段固定动作：
1. 写增量迁移 `0004+`（Schema 唯一真相 = Alembic 迁移链，基线 `0001` 已折叠）。
2. 迁移脚本沿用 `scripts/migrate_owner_id_to_email.py` 范式（dry-run 默认 / `--apply` 单事务 / 幂等）。
   ⚠️ 该脚本目前按字符串**等值** `UPDATE`，整数 ID 下必须改为**映射表驱动**（旧串 → 新整数）。
3. bump `tests/support/schema_pins.py` 的 `MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`。
4. **先更新 `docs/current-system-architecture-baseline.md`，再动代码。**

### 6.6 令牌失效：本次改造不触发

令牌是无状态 HMAC，载荷 `f"{user_id}.{device_id}.{exp}"`（`api/v1/auth.py:81`）。

- **B1 不触发**：存量用户的 `user_id`（`email-<hash>`）原样保留，只有新用户拿到雪花 id；类型仍是字符串，令牌载荷不变。
- **B2 已取消**（§6.5），故整条改造链**不需要任何强制重登**。

存量用户在下次登录时由 `find_or_create_by_email` 自动回填绑定行（`create_with_email` 撞唯一索引 → 返回既有行 → 补写绑定），无需数据迁移脚本 —— 该路径已有测试（`test_find_or_create_by_email_backfills_binding_for_legacy_user`）。

---

## 7. 必须处理的风险：雪花 ID 可枚举

雪花 ID 的**高位是时间戳**，因此「按时间递增、可推测」。当前 `user_id = email-<sha256(email)[:16]>` 不可枚举；换雪花后，攻击者能推算出「某时刻注册的用户 ID 落在某个区间」。

产品面靠 `require_user` 从 token 解析 `user_id`，只要**产品端点不接受显式 `user_id` 参数**就没有越权。但基线已登记：

> 调试台面端点（`/debug/*`、`/state`、action）`user_id` 省略时取 token 身份，**可显式传入覆盖** —— 调试面无多用户隔离（P2）

三个必须同时做的动作：
1. 调试面加**环境门禁**（仅 `dev` / 白名单 IP）。
2. 加测试：产品端点传入 `user_id` 参数时必须被忽略（`require_user` 优先）。
3. 对外接口**不把裸 ID 当业务引用**（客户端引用用户一律用 token 内身份）。若必须暴露，加一层不透明映射。

---

## 8. 验收口径

1. 全仓无自研雪花位运算；`sonyflake` 是唯一生成来源。
2. `app/core/ids.py` 是所有新实体 ID 的唯一入口；无 `uuid4()` 直接生成主键的残留。
3. `grep -rn "ORDER BY .*\.id" app/` 无业务时序用途命中（雪花虽趋势递增，但排序语义仍应交给 `created_at`）。
4. （B2 已取消，不适用）主键列类型统一 `BIGINT`；§6.2 五张表已拆分为「雪花 ID + 业务唯一键」。
5. 同一邮箱重复登录 → 同一 `user_id`；改绑邮箱后 `user_id` **不变**；同人邮箱 + 飞书 → **同一 `user_id`，两行 binding**。
6. 迁移脚本重跑幂等（第二次返回 `noop`）。
7. `schema_pins.py` 三常量已 bump。
8. 启动时时钟早于水位 → 进程拒绝启动并给出可读错误。
9. 产品端点传入 `user_id` 参数被忽略；调试面非 `dev` 返回 404/403。
10. 全部 ID 以字符串出现在 JSON 响应中（前端 JS 精度安全）。

**B1 已达标**：1 / 2（新代码）/ 5 / 7 / 8 / 10。
**阶段 C / D 达标**：6（迁移脚本幂等）/ 9（调试面门禁，见 §7）。

---

## 9. 附：实测证据

| 结论 | 证据 |
|---|---|
| 6 个库的回拨行为差异 | 逐个 `uv pip install --target` 下载源码审查：`snowflake-id` 回拨 `return None`（`snowflake/snowflake.py:126`）；`snowflake-py` 无时间比较仅 `_count % 4096`；`pydantic-snowflake` 回拨重置序列；`pysnowfall` 类级全局状态无锁 |
| sonyflake 单调时钟 | `sonyflake/sonyflake.py:340-352`：`_elapsed_time` 只增不减，序列溢出则 `+= 1` 并 sleep |
| 回拨实测 | 回拨 5s / 1h / 冻结时钟 5000 个，均无重复、单调、解码时间不回退 |
| 容量与寿命 | `time_bits=41` → 可用至 2095-09-07；4096 ID/ms；1024 机器 |
| SQLite 陷阱 | `BigInteger()` 在 SQLite 插入报 `NOT NULL constraint failed: x.id`；`with_variant(Integer,"sqlite")` 插入成功 `[(1,),(2,)]` |
| 已有自增先例 | `app/core/db/conversation.py:47` `messages.id = Integer, primary_key=True, autoincrement=True` |
| 45 张 String 代理主键 | 脚本按 `mapped_column(... primary_key=True)` 分类统计（§6.1） |
| 自增不适用表 | `ledger_repository.py:189` `get_category(seed_id)` 用派生 ID 当查找键；`api/v1/chat.py:52` 会话 ID 由客户端传入；`outbox_repository.py:57` 幂等键由业务计算 |
| 隐式引用列约 10 个 | `grep "_id: Mapped\[str\]" app/core/db/`（db 已拆包；排除 user_id/world_id/conversation_id/session_id） |
| 显式 FK 仅 6 处 | `grep -rc ForeignKey app/core/db/*.py` |
| 令牌载荷含 user_id | `api/v1/auth.py:81` |
| 可枚举风险已登记 | `current-system-architecture-baseline.md` 技术债表（P2） |
| 回归 | `tests/unit` 1551 passed；`tests/e2e` 179 passed |

---

## 10. 决策记录

| 项 | 结论 | 状态 |
|---|---|---|
| 生成策略 | 直接雪花，不做自增过渡 | **已定** |
| 库 | `sonyflake` 2.0.3 | **已落地** |
| epoch | 2026-01-01（**一次性决策，有数据后不可改**） | **已落地** |
| 位分配 | 41 / 12 / 10，1ms | **已落地** |
| 回拨防护 | L1 库 + L2 水位校验 + L3 部署约定 + L4 唯一约束 | **L1/L2 已落地**，L3 待运维确认 |
| 对外类型 | ID 以**字符串**出 JSON（JS 精度安全） | **已落地**（B1 保持 `str`） |
| 列类型 | **保持 `VARCHAR`**；不做 `BIGINT` 翻转 | **已定**（2026-10-03 评估后取消 B2，依据见 §6.5） |
| **已否决：B2 列类型翻转** | `VARCHAR → BIGINT` + Python 类型翻转。**否决理由**：实测收益只剩「DB 类型层强制 ID 为数字」，而成本为 584 处测试字面量（180 文件）+ 删库重建（与 B1 自愈路径矛盾）。**替代**：需要强约束时加在应用边界。**保留价值**：两个实现坑（单列主键渲染成 `BIGSERIAL` 需显式 `autoincrement=False`；`loop_runs.user_id` 是 `Mapped[str \| None]` 会漏改）已记入 §6.5，供未来重启时复用 | 已否决 |
| **已否决：自增 → 雪花** | 上一版方案（前期 BIGINT 自增、后期切雪花）。**否决理由**：既然终局是雪花，自增只换来 dev 可读性，却要多处理「5 张表例外 + 约 10 处插入前预知 ID 的重构 + 一次后期迁移」；而单机下雪花的运维成本与自增几乎相同。**保留价值**：其「SQLite `with_variant`」「5 张表例外清单」「`ids.py` 抽象层先行」三条结论已并入 §4/§6。 | 已否决 |
| **已否决：ULID** | `usr_<ulid>` 字符串方案。**否决理由**：用户选择整数 ID；且需全量改值为 String 语义，而整数路线与既有 `messages` 一致。 | 已否决 |
