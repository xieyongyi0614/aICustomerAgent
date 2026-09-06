# LIFE-004 Task Detail — Outbox 一致性（Core）

> 上游：[../tasks.md](../tasks.md) LIFE-004 ｜ [../../../architecture/data-flow.md](../../../architecture/data-flow.md) §2.1/§3 ｜ [../../../dependency-graph.md](../../../dependency-graph.md) §5 ｜ 依赖：LIFE-002, P1 MEM-002（已交付）

## Task 目标

打通 §九闭环的最后一公里：**Action → World → Event → Memory 链路不丢不重**。交付三件事：

1. `outbox_events` 表（迁移 0030）：Action 执行结果同事务落 outbox（幂等键 = action_id）；
2. 消费器（World → Event → Candidate 三段各自事务）：幂等消费 outbox，失败指数退避重试 max 5 → 死信 failed+reason；
3. Flag OFF 逐字节回 v1 直写路径（`v2_action_outbox_enabled` 子闸，总闸 `v2_life_loop_enabled`）。

「不丢」：v1 的跨域投递（world 效果落库、行动记忆直写）发生在能力执行的多个事务里，进程在任意两点之间崩溃都会留下半完成状态且无恢复线索；「不重」：重试路径（action retry loop 重执行）依赖各写入点各自的去重，没有统一的链路级幂等键。outbox 把「行动成功」与「世界知道」解耦为两个可重放的事务，是 data-flow.md §2.1 裁决的直接落地。

## 背景 / 为什么需要

v1 现状的 Action 结果投递链（`app/application/action_engine.py` `integrate_result` L130-156 四通道）：

- **world 通道**：world 效果在**能力执行期**已直写——`reminder.py` `_create` L62 直接调 `world_engine.create_event`（文件头铁律「世界写失败 = 行动失败」）、`world_action.py` create/move/use 直写 objects。行动「成功」与「世界变更」在同一个执行事务语义里，但崩溃窗口（能力返回后、action_records 终态提交前）会留下孤儿 world 事件——无 outbox 则无从发现与重放。
- **memory 通道**：`memory_bridge.deliver_action_memory`（memory_bridge.py:74-120）走 v1 直写（memory_policy R1~R8 + `memory_repository.create_memory`），且**不受 `v2_memory_enabled` 门控**——与 P1 `ingest_from_action_record` 补扫通道（post_process.py:206-208）并存，靠 evaluator 的 duplicate_exact 兜底避免双记忆（登记 README 核对记录 4）。
- **relationship 通道**：`relationship_bridge.deliver_action_signal` 直写账本。
- **失败恢复**：action retry loop（`_process_due_retries`）只重试「行动本身失败」（transient/timeout），不覆盖「行动成功但投递丢失」——后者 v1 完全无感知。

tasks.md Risk 明示：v9 action 当前默认关（`action_enabled: bool = False`，settings.py:228），outbox 的端到端灰度依赖评审通过后开启 v9（**评审项，非本 Task 改动**，登记 README 核对记录 15）；本 Task 在测试环境显式开启 action 验证链路。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| P1 MEM-002 action 摄取通道 | `ingest_from_action_record(record)`（memory2/ingest.py:167，幂等键 (source_table="action_records", source_id=record.id)） | 消费器**不自己做记忆投递**——只保证 action_records 行已终态，记忆沉淀交给既有 post_process 四源补扫（幂等键防重）；outbox 模式下 v1 直写通道被跳过，收口为单通道 |
| P1 MEM-002 world 摄取通道 | `ingest_from_world_event`（ingest.py:212，仅 status=completed） | world_events 落库后的候选生成走既有补扫（post_process.py:211-215），零改动 |
| P1 SKIP LOCKED 认领模式 | `memory2/job_worker._claim`（job_worker.py:89-107） | 消费器认领 pending outbox 行的同款模式（多执行器安全 + SQLite 方言退化已知可接受） |
| REL-001 跨域写经 ingest 先例 | Relationship 永不直写 memories 的收口模式 | 「Action 永不直接 INSERT memories」同一裁决（dependency-graph §5 合法写入路径），本 Task 是其在 action 域的落地 |
| V9 action 六态审计 | `transition_action` / 六态枚举（models/action.py:35-41）、`integrate_result`（action_engine.py:130） | outbox 写点挂在 integrate_result（三条入口路径 planning/retry/autonomy 的公共汇点，见设计 2）；六态状态机零改动 |
| V8 world 引擎 | `world_engine.create_event/create_object/move_object/cancel_events_by_type`（world_engine.py:354 等） | 消费器调**同名引擎函数**落世界效果（消费逻辑复用既有引擎，Non-Scope：不新增能力） |
| LIFE-002 Controller | 维护步骤位（kind=outbox_consume） | 消费器作为 Life Loop 维护步骤每 tick 扫描（进程重启后 pending 自然重放） |

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/application/action_engine.py` `integrate_result` L130-156 | 四通道直接投递（world effects 记账 / memory_bridge 直写 L153 / relationship_bridge L156） | Flag ON：四通道替换为「同事务 INSERT outbox_events(payload=效果描述符)」；OFF：逐字节 v1 |
| `app/services/action/capabilities/reminder.py` `_create` L62 | 能力执行期直写 `world_engine.create_event` | Flag ON：改为返回 deferred 描述符 `{"deferred_world_op": {"op": "create_event", ...params}}` 不落库（世界写移到消费器）；OFF：v1 直写。**边界认定见设计 3 与核对记录 3** |
| `app/services/action/capabilities/world_action.py` / `memory.py` / `world.py` | 同上直写点 | 同款 Flag 分叉（world_action 三 op、memory/world 能力的世界写调用点；校验与 registry 逻辑零改动） |
| `app/services/action/memory_bridge.py` `deliver_action_memory` L74 | v1 直写 | 模块保留（Flag OFF 通道）；Flag ON 不被调用（integrate_result 分叉在上游） |
| `app/services/action/relationship_bridge.py` `deliver_action_signal` | 直写账本 | 消费器调用（同函数，调用时机从执行期移到消费期） |
| `app/application/world_engine.py` | 引擎写函数 | **零改动**（消费器原样复用） |
| `app/core/db.py` | 无 outbox 模型 | 新增 `OutboxEventRow`（对齐 BackgroundJobRow 风格） |
| `migrations/versions/` | head=0029（LIFE-002） | 新增 `0030_outbox_events.py` |
| `app/application/` | 无 outbox 消费器 | 新增 `outbox_consumer.py`：`consume_pending(limit=50)` + `apply_outbox_event(row)` |
| `app/application/life_loop.py` | LIFE-002 维护步骤位 | 接线 outbox_consume 步骤（子闸开启时 work 发现含 outbox_pending） |
| `app/core/settings.py` | — | 新增 `v2_action_outbox_enabled: bool = False`、`v2_life_loop_outbox_max_attempts: int = 5`、`v2_life_loop_outbox_backoff_seconds: int = 30` |
| `app/services/trace_collector.py` TRACE_STEP_NAMES | 无 outbox 步骤名 | 追加 `outbox_consume` |
| `app/api/v1/debug.py` actions 查询 | 仅 action_records 视角 | 追加返回 outbox 状态字段（一条 join 查询 extend，观测验收「outbox 状态可查」） |
| `tests/v9/test_action_*` | v1 直写路径回归 | 保持全绿（OFF 路径）；新增 `tests/v2/test_life004_outbox.py` |

## 设计方案

1. **表结构（迁移 0030）**：

   ```text
   outbox_events
     id              varchar PK
     event_type      varchar NOT NULL default 'action_result'   -- P5 仅一种；列预留扩展
     payload         JSON NOT NULL   -- {action_id, user_id, effects:[...], world_ops:[...],
                                     --  memory_op:{...}|null, relationship_op:{...}|null}
     idempotency_key varchar NOT NULL UNIQUE   -- = action_id（tasks.md 幂等键口径）
     status          varchar NOT NULL CHECK in ('pending','consumed','failed')
     attempts        int NOT NULL default 0
     next_retry_at   timestamptz NULL
     last_error      varchar NULL
     created_at / updated_at timestamptz
     索引：(status, next_retry_at)
   ```

2. **写点（同事务，唯一汇点）**：`integrate_result` 是三条入口（chat_pipeline action_detect → run_action_planning；autonomy `_produce_autonomy_action`；action retry loop）执行成功后的公共汇点（action_engine.py:205 经 execute_plan→integrate_result；:269 retry 路径同）。Flag ON 时该函数替换为：

   ```text
   同一事务:
     action_records 终态迁移（既有）
     INSERT outbox_events(event_type='action_result', idempotency_key=action_id,
                          payload={world_ops, memory_op, relationship_op, effects})
   ```

   IntegrityError（同 action_id 重放）→ 视为已登记，幂等吞掉。v1 四通道的其余部分（effects 记账进 record.result）保持——payload 是 record.result 的有界投影。

3. **能力执行期世界写的延迟化（关键裁决，边界认定见核对记录 3）**：tasks.md 红线「Action/World 引擎本体零改动（version-boundary Extend→Replace 仅限执行器编排）」。本 Task 的 Flag 分叉点认定：
   - **不改动**：六态状态机、六闸门（planner）、CapabilityExecutor 超时与失败分类、能力校验/registry/参数 schema、world_engine 全部函数、AutonomyPolicy。
   - **Flag 分叉（Replace）**：能力函数内「跨域写调用点」——`reminder._create` / `world_action._*` / `memory` / `world` 能力中直接调 world_engine 写函数的语句。Flag ON 时这些调用点改为构造 `world_ops` 描述符（op 名 + 参数原样）返回，落库延迟到消费器调**同名引擎函数**完成。这是「执行器编排」的 Replace：改的是写调用发生的位置与时机，不是任何引擎逻辑。
   - **语义变化（必须登记）**：v1「世界写失败 = 行动失败」（reminder.py 文件头铁律）在 outbox 模式下变为**最终一致**——容量上限等世界侧失败从「行动 failed」变为「outbox 重试 → max5 死信 failed(reason) + trace 可查」。行动本身仍失败（行动检定/能力校验失败语义不变）；行动成功但世界落库失败不再回滚行动，而是链路级补偿。缓解：死信在 debug/actions 可查 + E-LIFE-04 审计规则（LIFE-006）捕获滞留死信。Flag OFF 保留 v1 语义逐字节。

4. **消费器（三段各自事务，data-flow.md §2.1 ②③）**：

   ```text
   consume_pending(limit=50):                     -- Life Loop 维护步骤每 tick；进程重启自然重放
     SELECT pending AND next_retry_at<=DB now ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT n
     逐行:
       ① world 段: 逐 world_op 调引擎函数（create_event/create_object/move_object/...）
          幂等护栏: payload.global_dedupe = action_id → 先查 world_events.payload.outbox_action_id
          或 world 实体指纹已存在 → 跳过该 op（重放不二次落库）
       ② event 段: world 变更即 world_events 行（引擎函数内部既有语义）
       ③ candidate 段: 不在此投递——action_records 已终态 + world_events 已落库，
          既有 post_process 四源补扫（ingest_from_action_record / ingest_from_world_event，
          幂等键 (source_table, source_id)）自然收敛为 Candidate
       ④ CAS: status pending→consumed（同事务 with ③ 检查；WHERE status='pending' 防并发双消费）
     失败: attempts+1，next_retry_at = now + backoff×2^attempts；attempts≥max5 → failed 死信(last_error)
     relationship_op: relationship_bridge.deliver_action_signal（既有函数，自带效果幂等）
   ```

   ③ 的裁决：消费器**不做**记忆候选投递——P1 补扫通道已存在且幂等（跨轮收敛是 Phase 1 既定语义），消费器只负责把 world/event 段落库到位；这是「三段各自事务，禁止跨域直写」的最小实现（tasks.md Domain Boundary）。E-LIFE-04「candidate 恒为 1」由 P1 幂等键保证，测试中端到端断言。

5. **重放与恢复**：
   - 进程重启：pending 行（含 next_retry_at 已到期的）被下一 tick 维护步骤扫到——无特殊启动逻辑。
   - 同一 Action 结果重放三次（测试注入）：idempotency_key 唯一 → outbox 行恒 1；world_op 指纹护栏 → world_event 恒 1；P1 补扫幂等键 → candidate 恒 1（E-LIFE-04 验收）。
   - 消费中途崩溃（world 写后 CAS 前）：重启重放 → 指纹护栏跳过已落库 op → CAS 完成 → 最终一致。
   - 死信处理：status=failed 留痕，不自动重放（运维决策；对账工具/手工重置归 ops 范畴，本 Task 仅保证可查）。

6. **观测**：`outbox_consume` trace 步骤（每行：action_id / op 结果 / skip 原因 / 重试次数）；debug actions 视图附 outbox 状态；链路 trace 贯穿 `action_execute`（既有）→ `outbox_consume`（新增）→ `memory_ingest`（既有）。

## 数据模型 / 状态变化

- 新表 `outbox_events`（迁移 0030）：状态机 `pending→consumed|failed`（failed 死信终态；重放=手工重置 pending，ops 决策）。
- world_events / world 实体行新增 payload 约定键 `outbox_action_id`（消费器写入，供指纹幂等；不改表结构）。
- 新增 settings 三项（见涉及位置表）。
- 零业务域表结构变更；action_records 六态语义不变（outbox 写点在终态迁移事务内追加 INSERT）。

## 核心处理流程

```text
Flag OFF（现状逐字节）:
  能力执行期直写 world → integrate_result 四通道直投（memory_bridge 直写/relationship 直写）
  失败恢复仅 action retry（行动级），投递丢失无感知

Flag ON:
  行动执行成功
    → 同事务(action_records 终态 + outbox_events INSERT, 幂等键=action_id)
    → [行动结果已持久化，跨域投递异步化]
  Life Loop 维护步骤（每 tick，纯 SQL 扫描）
    → claim pending（SKIP LOCKED）
    → world_op 幂等护栏检查 → 调既有引擎函数落世界效果（world_events 行产生）
    → CAS pending→consumed
    → 既有 post_process 补扫：action_records + world_events → memory_candidates（P1 幂等）
  失败 → 指数退避重试 ×≤5 → failed 死信（reason + trace）

崩溃恢复: 任意点 kill -9 → 重启 → pending 重放 → 指纹护栏/CAS/摄取幂等键 → 不丢不重
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：链路终点——候选生成完全经 P1 摄取通道（`ingest_from_action_record` / `ingest_from_world_event`），Action 域零直写 memories（dependency-graph §5 合法路径第 1 条的完整落地）；v1 直写通道（memory_bridge.deliver_action_memory）在 Flag ON 下不再被调用，双通道收口（对齐 REL-001 旁路关停先例；v1 直写在 v2_memory_enabled 下的全局去留建议评审另行裁决——核对记录 4）。
- **Reflection**：无直接交互（候选经评估转正后的记忆进入 REF-002 证据窗口是既有链路）。
- **Development**：无直接交互。
- **Relationship**：relationship_op 经既有 `deliver_action_signal` 写账本（函数零改动，调用时机移到消费器）；账本行后续经 REL-001 摄取通道转写叙事记忆——Action→Relationship→Memory 全链无直写。

## 异常与边界情况

- **世界容量上限**（world op 消费期失败）：重试 ×5 → 死信 + debug 可查；行动已成功不回滚（最终一致语义，核对记录 3）。
- **world op 部分成功**（多 op 中途失败）：payload 逐 op 护栏，重放从失败 op 继续（已成功 op 被指纹跳过）。
- **同 action 并发重试**（action retry loop 与 outbox 消费同时触碰）：outbox INSERT 幂等键吞重；CAS WHERE status='pending' 防双消费；action retry 重执行在 Flag ON 下不再重复直投（integrate_result 幂等登记）。
- **消费器异常**：单行失败不影响批内其他行（逐行 try/except，对齐 job_worker 模式）；批消费超时由 tick 周期兜底（limit=50 小批量）。
- **Flag ON 但 outbox 表未迁移**：INSERT 失败 → 行动终态已提交、outbox 缺失 → 启动校验器告警（对齐 LIFE-001 模式）+ debug actions 可见 outbox 缺失；Enablement 串行链保证灰度不出现该组合。
- **proactive 消息不在 outbox 范围**：proactive_actions 表（深度 1 队列）保持原样——outbox 只覆盖 v9 Action 结果链（核对记录 16）。
- **action_enabled=False（当前默认）**：无 action 产生即无 outbox 行——链路空转，消费器 0 扫描成本；灰度前置条件登记核对记录 15。

## 测试要求

- Unit：outbox 状态机（pending→consumed/failed、非法迁移拒绝）；退避计算；payload 序列化/还原；指纹护栏判定。
- Integration：①幂等重放——同一 Action 结果重放 3 次 → outbox/world_event/candidate 各恒为 1（E-LIFE-04）；②故障注入——world 写后 CAS 前 kill（连接中断模拟）→ 重启续走最终一致；③退避死信——连续失败 5 次 → failed+reason、不再重试；④端到端——Flag ON 下 create_reminder 行动：outbox → world 事件落库 → 到期触发（LIFE-001 action_due）→ 汇报 → 记忆候选，全链 trace 完整；⑤debug actions 显示 outbox 状态。
- Regression：**Flag OFF golden**（capabilities/execute/integrate 逐字节）；V9 action checklist 全量（outbox 改造不破坏 action 语义）；V8 world checklist（消费复用引擎）；P1~P4 Eval Gate 上游不回退。
- 性能：消费批 50 行 < 1s（无 LLM）；空表扫描 <10ms。

## 验收标准

- 给定同一 Action 结果重放三次，那么 world_event 与 candidate 各恒为 1。
- 给定消费中途崩溃，那么重启后链路续走且最终一致（pending 重放 → consumed）。
- 给定世界侧持续失败，那么 5 次退避后死信留痕且可查，行动审计不受损。
- 给定 Flag OFF，那么 Action→World→Memory 行为与 v1 逐字节一致（V9/V8 checklist 全绿）。
- 给定任一行动，当查询 debug，那么 action 状态、outbox 状态、产生的 world 事件与记忆候选可互相溯源（链路 trace 贯穿）。

## Implementation Constraints

- **红线**：六态状态机、六闸门、CapabilityExecutor、world_engine 函数体、AutonomyPolicy 全部零改动；Flag 分叉仅限 integrate_result 投递编排与能力函数内跨域写调用点（Extend→Replace 边界认定，核对记录 3——实施前评审确认该认定）。
- 消费器只调既有引擎函数，不新增世界/记忆/关系写入逻辑；「禁止跨域直写」三段事务边界（data-flow.md §2.1）逐条落实。
- 幂等键 = action_id 唯一约束是防重基石，禁止在无幂等护栏的情况下放宽重试。
- v1 直写代码路径全量保留（Flag OFF 回退面 + 历史可读性）；删除属 3.0 清理决策。
- LLM Usage = NONE（全程规则与 SQL）。
- 时间基准用数据库时间（next_retry_at 比较在 SQL 内）。
- `action_enabled` 默认值不改（False）；outbox 端到端灰度依赖 v9 默认启用评审（核对记录 15），本 Task 测试以显式开启 action 的环境执行。
- 不提前设计 Phase 6：event_type 扩展（goal 事件等）仅列保留，不实现。
