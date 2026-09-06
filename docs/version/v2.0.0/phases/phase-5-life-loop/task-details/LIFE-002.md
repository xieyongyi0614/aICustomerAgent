# LIFE-002 Task Detail — Life Loop Controller（Core）

> 上游：[../tasks.md](../tasks.md) LIFE-002 ｜ [../../../architecture/character-runtime.md](../../../architecture/character-runtime.md) §2.2 ｜ [../../../architecture/overview.md](../../../architecture/overview.md) §1 LL 节点 ｜ 依赖：LIFE-001（本 Phase 内）

## Task 目标

统一周期编排控制器：把 v1 三个各自为政的常驻循环（autonomy tick / world maintenance / action retry）的**调度权**归并到一个 60s 节拍的 Life Loop Controller，按 character-runtime.md §2.2 的步骤管线执行「生活时刻」：

```text
Perception → State Update → Goal Evaluation → Memory Retrieval
  → Reflection Check → Decision → Action → World Event → Experience ↺
```

具体交付三件事：

1. `app/application/life_loop.py`：run_life_loop_worker（lifespan 启动）+ run_life_loop_tick（单周期）——**只调度，不持有业务语义**；
2. `loop_runs` 表（迁移 0029）：每周期一行完整记账（步骤/时长/LLM 调用/Token/skip 原因），「为什么运行/为什么没运行/花了多少」可答；
3. 归并三个循环的调度入口（引擎函数原样复用），Flag OFF 时 v1 三循环原样。

v1 的 60s autonomy tick（trigger→decision→proactive）是本循环 Decision+Action 两步的既有实现——Controller 不重写它，复用 `autonomy_engine.tick`；新增的是它前面的 Perception/State/Goal/Memory/Reflection 五步与后面的 World/Experience 收尾步。

## 背景 / 为什么需要

v1 审计确认（tasks.md Problem）：5 个常驻 asyncio 循环各自为政（main.py lifespan 实为 6 个 task：memory reclaim / v2 job worker / autonomy / observability retention / world maintenance / action retry，其中 reclaim 与 retention 属基础设施、v2 job worker 是 P1 底座——归并口径登记见 README 核对记录 7）。它们的问题：

- **无统一节拍与优先级**：autonomy_worker（60s 先 sleep 后 tick）、world maintenance（60s）、action retry（60s）三个 `while True + sleep` 循环独立起停、异常各自吞掉，没有共同的生命周期视图；
- **「角色持续存在」只是 60s tick**：v1 tick 只回答「要不要发主动消息」一个问题，没有感知/状态衰减/目标检查/记忆想起/反思检查——用户不说话时角色只是「定时看一眼要不要说话」，不是「在生活」；
- **不可观测**：三个循环都没有「这轮为什么跑/跑了什么/花多少」的结构化记录，消息风暴与空转成本均无从归因（R8/R9 的观测基础缺失）。

v2 裁决（overview.md §1）：autonomy_engine 归并入 Life Loop Controller 节点；domain-boundaries.md §1 将 Autonomy/Life Loop 定为 Service 编排域——「调用所有域，不被业务域调用，不持有业务语义，只决定何时跑、跑什么、跑多少」。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| LIFE-001 trigger_registry | `claim_due` / `has_due` / `recover_stale`（trigger_registry_repository） | due 扫描（has_due 只读判定 + tick 内部经 trigger_evaluator 表通道领取）；对账步骤接线 recover_stale |
| P1 MEM-009 background_jobs 协议 | `memory2/job_worker.py`（tick hook / SKIP LOCKED 认领 / 僵尸回收） | **模式复用**：Controller 的单步执行异常隔离、timeout 参数取值（v2_job_running_timeout）对齐该协议；Controller 不走 background_jobs（周期编排有自己的 run 账本） |
| P1 per-user 写锁 | `get_user_write_lock`（post_process.py:383-388） | Controller 单用户周期全程持用户写锁（与 post_process 互斥，防「生活时刻」与前台后半段并发写同用户状态） |
| P2 REF-003 tick hook 模式 | `reflection.triggers.register_with_job_worker`（triggers.py:45-49） | 反思触发已挂 job_worker tick；Controller 的 reflection_check 步骤是**调用方**（LIFE-005），本 Task 只留步骤位与 skip 条件 |
| P3 DEV-003 行为调制（间接） | `goal_service.select(..., development_weights=...)` 接线已在 chat_pipeline.py:160 / autonomy_engine `_snapshot_for`:125 | Goal Check / Decision 步骤经既有 select 路径自动获得 P3 调制，零额外接线 |
| P4 REL-003 patterns（间接） | `_snapshot_for` L142-149 已组装 `PolicySnapshot.relationship_patterns` | Decision 步骤经 autonomy_engine 既有组装自动获得，零额外接线 |
| V7 autonomy 引擎 | `autonomy_engine.tick(user_ids, llm, now)`（autonomy_engine.py:378） | **原样复用**：Decision+Action 两步 = `tick(user_ids=[user_id])`（信号轮询经 LIFE-001 表通道） |
| V8 world 引擎 | `world_engine.run_maintenance(user_id=None)`（world_engine.py:659）/ `collect_facts`（:627） | Perception 步骤读 facts（原样复用）；维护步骤调 run_maintenance（原样复用） |
| V9 action 引擎 | `action_engine._process_due_retries`（:269）/ `_expire_planned`（:291） | 维护步骤原样复用（私有函数升为可导入调用，不改函数体） |
| V1 状态引擎 | `state_service.load_states`（state_service.py:98-108，内含 apply_idle_recovery + apply_emotion_decay 纯规则） | State Update 步骤原样复用（读即衰减，无需新衰减代码） |
| V6 goal 引擎 | `goal_service.review` 到期规则（goal_service.py:187-190）/ `goal_repository.expire_goal` | Goal Check 步骤复用到期规则语义（补扫口径，见设计 3 与 README 核对记录 2） |

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/main.py` L52-55 / L60-63 / L64-67 | autonomy / world / action 三循环各自 create_task | Flag ON：三处改为启动 `life_loop.run_life_loop_worker()`（单 task）；OFF：三循环原样 |
| `app/application/autonomy_worker.py` | v1 tick 循环 | **零改动**（Flag OFF 专用路径保留；删除属 3.0 清理决策） |
| `app/application/autonomy_engine.py` | tick / _process_user 决策管线 | **零改动**（被 Controller 以 `tick(user_ids=[user_id])` 原样调用） |
| `app/application/world_engine.py` / `action_engine.py` | 引擎函数 | **零改动**（run_maintenance / _process_due_retries / _expire_planned 原样复用） |
| `app/application/` | 无 life_loop 模块 | 新增 `life_loop.py`（worker / tick / 步骤管线 / run 记账） |
| `app/repositories/` | 无 loop_run 仓储 | 新增 `loop_run_repository.py`（create/mark_step/finish/list_recent） |
| `app/core/db.py` | 无 loop_runs 模型 | 新增 `LoopRunRow`（含 LIFE-003 记账列，一次到位，见 README 核对记录 9） |
| `migrations/versions/` | head=0028（LIFE-001） | 新增 `0029_loop_runs.py` |
| `app/core/settings.py` | — | 新增 `v2_life_loop_tick_seconds: int = 60`（复用既有 world_maintenance_interval_seconds / action_maintenance_interval_seconds 作维护节拍） |
| `app/services/trace_collector.py` TRACE_STEP_NAMES | 无 life_loop 步骤名 | 追加 `life_loop_run` / `life_loop_perception` / `life_loop_state_update` / `life_loop_goal_check`（memory/reflection/budget 步骤名由 LIFE-003/005 各自追加） |
| `tests/integration/test_autonomy_matrix.py` 等 V7 回归 | v1 管线回归 | 保持全绿；新增 `tests/v2/test_life002_controller.py` |

## 设计方案

1. **节拍与工作发现（纯 SQL，0 LLM）**：每 `v2_life_loop_tick_seconds`（默认 60s）执行一次：
   ```text
   work = has_due_trigger()                      -- trigger_registry 只读 EXISTS（LIFE-001）
        ∨ goal_catchup_due()                     -- goal 到期补扫目标存在（只读）
        ∨ outbox_pending() > 0                   -- LIFE-004 子闸开启时
        ∨ world_maintenance_due()                -- 距上次维护 ≥ world_maintenance_interval_seconds
        ∨ action_retry_due()                     -- 距上次 ≥ action_maintenance_interval_seconds
   无 work → Idle 本轮（LIFE-003 细化）：不建 run、不调 LLM、仅进入下一轮时钟等待
   ```
   维护间隔判定用进程内上次执行时间戳（内存态，重启即重新计时——维护是幂等扫表，漏拍无损失）。

2. **用户周期步骤管线**：有 due trigger 的用户进入单用户周期（每用户持 `get_user_write_lock`），按序执行，每步前置条件检查 + 条件跳过（skip 也是记账）：

   | # | 步骤 | 实现（全部原样复用） | skip 条件 |
   |---|---|---|---|
   | 1 | perception | `world_engine.collect_facts(user_id)` + 未读 due world events 计数（只读） | 无 |
   | 2 | state_update | `state_service.load_states(user_id)`（读即 idle_recovery+emotion_decay） | 无 |
   | 3 | goal_check | 到期补扫（设计 3） | 无 active goal |
   | 4 | memory_retrieval | LIFE-005 交付 | v2_memory_enabled OFF / LIFE-005 未启用 |
   | 5 | reflection_check | LIFE-005 交付 | v2_reflection_enabled OFF / 频控未到 |
   | 6 | decision | `autonomy_engine.tick(user_ids=[user_id])`（信号领取→Policy→入队→执行一气呵成） | 该用户无 claimed signal（tick 内部自行判定，天然 skip） |
   | 7 | world_event / experience | `world_engine.run_maintenance(user_id)` + outbox 消费（LIFE-004）+ 四源补扫语义（经既有 post_process 摄取面） | world_enabled OFF 时跳过维护部分 |

   步骤 6 是 LLM 唯一可能发生的步骤（proactive 命中时，经既有 proactive_chain）——Controller 自身 0 LLM（tasks.md LLM Usage 口径）。

3. **Goal Check 的补扫口径**：v1 goal 到期是 turn 基准（`current_turn > expires_at_turn → expire_goal`，goal_service.py:187-190，无时间列）。用户不在场时 turn 不前进，「到期 goal」在生活时刻的诚实语义是**补扫**——上次对话结束时已应到期但未及处理的 goal（`goal_repository.list_active` 逐条比对最新会话 current_turn）在本步补记 expired。time-based goal 到期（due_at 语义）是 P6 AUT-001 的存储扩展，本 Phase 不提前设计（登记 README 核对记录 2）。Goal 驱动决策的路径不变：expired 后 `goal_service.select` 的下一次快照自动反映（goal_degraded / 换选），经步骤 6 既有管线生效。

4. **维护步骤（无用户维度）**：work 发现命中维护条件时，在用户周期之外执行引擎函数并落 `kind` 区分的 run 行：
   ```text
   world_maintenance  → world_engine.run_maintenance()        （kind=world_maintenance, user_id=NULL）
   action_retry       → _process_due_retries() + _expire_planned()（kind=action_retry）
   outbox_consume     → outbox_consumer.consume_pending()      （kind=outbox_consume，LIFE-004）
   trigger_reconcile  → trigger_registry_repository.recover_stale()（kind=trigger_reconcile，可并入 world_maintenance 拍）
   ```
   全部是幂等扫表 + 引擎函数原样调用；Controller 不实现任何 world/action 业务逻辑。

5. **loop_runs 记账**：
   ```text
   loop_runs（迁移 0029，LIFE-003 记账列一次到位）
     id / user_id NULL / kind (autonomy|world_maintenance|action_retry|outbox_consume|trigger_reconcile)
     trigger_id (trigger_key) NULL / trigger_type NULL / reason（本轮为何运行：due_trigger:{key} / goal_catchup / maintenance / outbox）
     status (running|done|aborted) / current_step
     steps JSON   -- [{step, status(ok|skipped|error), duration_ms, skip_reason, llm_calls, error}]
     llm_call_count int / token_total int / budget_state JSON   -- LIFE-003 消费，建表即含
     started_at / finished_at / created_at
     索引：(status, started_at)、(user_id, started_at)
   ```
   run 状态机沿 tasks.md：`running → (perception→…逐步推进 current_step) → done | aborted(步骤异常/预算熔断)`；步骤级 skip 合法（记 skipped+reason）。llm 计数来源：步骤 6 结束后从本轮 TurnTraceSession 的 llm 步骤聚合（trace 已记 llm 调用时长/token 摘要，observability 既有口径）。

6. **幂等与并发**：
   - run_id 每周期唯一（uuid）；同 trigger 不重复入 run——由 LIFE-001 claim 原子性保证（trigger 被领取后转 due，下轮 has_due 不再计它）。
   - 单用户写锁使生活时刻与前台 post_process 串行（防并发写 character_state / 关系数值）；锁获取失败（前台持有中）→ 本轮 skip 该用户 + reason=user_busy，下轮重试（trigger 已 claim，不丢——done 判定在步骤 6，skip 发生在更早步骤时 trigger 留在 due 态由 recover_stale 兜底）。
   - **skip 语义与 trigger 生命周期的衔接（关键裁决）**：步骤 1~5 的 skip/error **不消耗** trigger（其 claim 发生在步骤 6 内部的 tick 信号轮询中，天然只在 decision 实际运行时领取）；步骤 6 内部异常 → tick 内部已有 per-user try/except（autonomy_engine.py:382-387）+ LIFE-001 重试边兜底。Controller 不重复实现 trigger 状态推进。

7. **lifespan 归并**：`v2_life_loop_enabled=True` 时 main.py 只启动 `_life_loop_task`，不再启动 autonomy/world/action 三 task（三循环的调度入口归并；引擎函数本体零改动）；OFF 时三 task 原样启动、life_loop 不启动。shutdown 统一 cancel（沿既有模式 main.py:69-82）。

## 数据模型 / 状态变化

- 新表 `loop_runs`（迁移 0029）；run 五 kind × 三态（running/done/aborted），步骤级状态记录在 steps JSON（无独立表——run 是账不是业务状态，重算无意义故不设投影）。
- 维护时间戳（上次 world/action/outbox 维护时刻）为进程内存态，不落表（幂等扫表使丢态无害；若未来 Worker 抽离需跨进程协调，届时升级为表列——登记 README 核对记录 10）。
- 零业务域表变更；trigger_registry 由 LIFE-001 持有，本 Task 只读扫描 + 消费其生命周期接口。
- 新增 settings：`v2_life_loop_tick_seconds`。

## 核心处理流程

```text
Flag OFF: main.py 三循环各自起（v1 逐字节），life_loop 不存在

Flag ON（单 task，60s 节拍）:
  tick 开始（0 LLM）
    ├─ work 发现（纯 SQL EXISTS ×5）
    ├─ 无 work → Idle 返回（下一轮）
    └─ 有 work →
        ├─ due trigger 用户 → 单用户周期（持用户写锁）：
        │    perception → state_update → goal_check → memory_retrieval(L5)
        │    → reflection_check(L5) → decision: autonomy_engine.tick([user])
        │    → world/experience: run_maintenance(user)+outbox 消费(L4)
        │    每步：前置检查 → 执行 | skip(reason) → 记 steps JSON + duration
        │    全程 → loop_runs 一行（running→done|aborted）
        └─ 维护到期 → run_maintenance() / _process_due_retries()+_expire_planned()
             / outbox consume / trigger reconcile → loop_runs 一行（kind 区分）
  异常：单用户 run aborted+原因，其余用户/维护照常；单步 error 不中断后续步骤
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：memory_retrieval 步骤是 P1 检索的调用方（LIFE-005 细化）；experience 收尾步经既有摄取面（post_process 四源补扫语义）让本轮 world/action 变化沉淀为 Candidate——闭环 `World Event → Experience` 落点。Controller 不直写任何 Memory 表。
- **Reflection**：reflection_check 步骤是 REF-003 触发器的调用方（LIFE-005 细化）；反思产出（Insight）经 DEV/REL 既有监听器链扩散，与本 Task 无耦合。
- **Development**：无直接交互——DevPolicy 调制经 `goal_service.select(development_weights)` 与 BehaviorEngine 既有接线在步骤 6 内自动生效（P3 已交付的调制点，Controller 零接线）。
- **Relationship**：无直接交互——关系闸门（亲密度/信任/冲突）经 `PolicySnapshot` 既有组装在步骤 6 内自动生效（V8.5 R1~R5 + P4 patterns 参考，全部零改动）；关系数值写入只发生在既有 post_process/state_service 路径，Controller 不触碰。

## 异常与边界情况

- **单用户周期步骤异常**：记 error + 继续（单步失败不阻塞其他步骤）；run 整体 aborted 当且仅当步骤 6（decision）失败——此时 trigger 经 LIFE-001 重试边恢复。
- **用户写锁被前台持有**：skip 本轮（reason=user_busy），不等待（生活时刻不阻塞前台是第一优先级）；trigger 留 due 态，recover_stale 超时重置后下轮重来。
- **某用户有 due trigger 但其会话不存在**（新用户无对话）：tick 内部既有 `conversation is None → return None`（autonomy_engine.py:240-242）天然 skip；trigger 判定不行动 → done。
- **维护步骤异常**：记 run aborted，下轮间隔到期重试（幂等扫表，无状态损伤）。
- **Flag ON 但 LIFE-001 表为空/未迁移**：has_due 异常 → 按「无 work」Idle 处理 + 启动告警（宁可不跑，对齐 LIFE-003 判定异常默认 Idle 口径）。
- **节拍重叠**（上轮 tick 未完下轮到点）：worker 循环串行执行（`while True: await tick(); await sleep`），不并发叠轮；单轮超长（卡死）由步骤内既有 timeout（capability 10s / reflection 10min / job 600s）与 asyncio 任务取消兜底。
- **多进程部署**：P0 单进程假设（R14：日活>100 才抽离 Worker）；trigger claim 与 outbox 消费的 SKIP LOCKED 已为多执行器预留正确性，维护时间戳内存态在多进程下可能重复执行维护（幂等，无害）——登记 README 核对记录 10。
- **Flag 热切换**：无热切换——lifespan 起停决定走哪套循环；运行中改 Flag 需重启（与 P1~P4 各 Flag 口径一致）。

## 测试要求

- Unit：work 发现五种条件的真值表；步骤管线顺序与 skip 条件（每步可独立 skip 且记账）；run 状态推进（running→done/aborted）；维护间隔判定。
- Integration：①空转演练——无任何 work 时连续 N 轮 tick：0 loop_runs 行、0 LLM；②端到端——构造 due trigger + 到期 goal，单周期内两步均完成、loop_runs 完整（E-LIFE-02）；③归并等价性——Flag ON 下同一输入（due followup）产出与 Flag OFF 相同的 proactive 行为（V7 checklist 重跑通过 = 引擎零改动证明）；④维护步骤——world 过期事件被清理、action 到期重试被执行、run 记账正确。
- Regression：**V7 autonomy regression-checklist 全量**（每 Task 合入硬门）+ V8 world checklist 维护语义 + V9 action retry 语义 + Flag OFF golden。
- 性能：单轮 tick 无 work 时 <50ms（纯 SQL EXISTS）；有 work 单用户周期内 LLM ≤ 步骤预算（LIFE-003 断言）。

## 验收标准

- 给定 due trigger + 到期 goal，当周期执行，那么两步均完成且 loop_runs 完整（步骤/时长/LLM 用量齐全）。
- 给定引擎函数（autonomy_engine.tick / world_engine.run_maintenance / action_engine._process_due_retries），当 Controller 调用，那么与 v1 输出一致（零改动——输入输出快照断言测试）。
- 给定无任何工作的一轮，那么 Idle 短路：0 loop_runs 行、0 LLM 调用。
- 给定步骤异常，那么 run aborted 带原因、其他用户与其他步骤不受阻、下轮恢复。
- 给定 Flag OFF，那么 main.py 启动 v1 三循环且行为逐字节一致。
- 「为什么运行/为什么没运行」对任意一轮均可用 loop_runs.reason + steps[].skip_reason 回答（六问 trace 抽查通过，E-LIFE-02）。

## Implementation Constraints

- **红线**：AutonomyPolicy 触发判定纯函数与 Action/World 引擎本体零改动（tasks.md Capability Map）；Controller 归并的仅是**执行器编排**——引擎函数以 `tick(user_ids=[user])` / `run_maintenance()` / `_process_due_retries()` 原样调用，改函数体即违规。
- Controller 不写业务域表（唯一写面 = loop_runs + trigger_registry 状态接口）；不新增 LLM 链；不持有业务状态（维护时间戳等编排态除外）。
- 单用户周期必须持 per-user 写锁且全程不释放（跨步骤一致性）；禁止在锁内做长 LLM 等待以外的无限阻塞。
- 周期任务时间基准用数据库时间（due 扫描 SQL）；维护间隔判定用单调时钟（防系统时间回拨抖动）。
- 迁移 0029 只增表（含 LIFE-003 记账列一次到位，README 核对记录 9）；downgrade drop 干净。
- LLM Usage：Controller 本体 0 LLM；周期内 LLM 仅出现于步骤 6 内部既有链（proactive 命中时），受 LIFE-003 预算约束。
- 不实现 Idle 判定细节与配额熔断（LIFE-003）、周期检索与反思检查内容（LIFE-005）、outbox 消费器本体（LIFE-004）——本 Task 交付步骤位、skip 条件与记账骨架。
- 不提前设计 Phase 6：goal 不新增 due_at/层级语义（AUT-001），decision 不接 Planning（AUT-002），goal check 不做 Sub-Goal 判据检查（AUT-003）。

## 缺口补充设计（评审决策材料，随登记缺口收口补充）

### 补 1：多进程维护协调的升级备案（核对记录 10）

R14 阈值触发（日活>100 或周期任务 P95>30s）抽离 Worker 进程时，内存维护时间戳的替换方案备案（**本期不实施**）：

- 方案 a（推荐）：维护「上次执行时刻」从内存态升级为 `loop_runs` 查询——`SELECT MAX(finished_at) FROM loop_runs WHERE kind=:kind AND status='done'`（走 (status, started_at) 索引，每 tick 一次廉价查询），零新表零新列，崩溃天然恢复；
- 方案 b：独立 `maintenance_heartbeats` 小表（kind + last_run_at，UPSERT），语义更直白但多一张表；
- 正确性前提不变：维护步骤本身幂等（扫表重入无害），多执行器下最坏重复执行一次维护，SKIP LOCKED 已覆盖 trigger/outbox 的强一致部分。
