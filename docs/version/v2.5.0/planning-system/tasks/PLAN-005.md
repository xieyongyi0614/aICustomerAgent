# PLAN-005 Task Detail — Plan Execution Engine

> 上游：[../architecture.md](../architecture.md) §3.6（PlanScheduler）、§3.7（PlanExecutorBridge）、§3.8（PlanObserver）、§3.9（PlanRevision）、§5.3（Task 状态机）、§5.5（双层重试）、§5.6（ActionStatus 映射）、§6.4 / §6.5 / §6.6、§7.8、§8.4 / §8.5；[../tasks.md](../tasks.md) PLAN-005
> 状态：DONE（已实现，commit 0f8daa5，2026-09-16）
> 范围红线：**先搬后改**（`PlanScheduler` 搬运既有私有函数，行为零变更）；步骤执行**唯一入口**为 `action_engine.run_action_planning`；Planning 目录零直调 `ToolExecutor` / `Capability.execute`；Plan 层**零退避**；`settle` 是**唯一**改 `GoalStatus` 的入口。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-005 |
| **Task Name** | Plan Execution Engine |
| **Priority** | P0 |
| **Dependencies** | PLAN-004 |
| **Phase** | Phase 2 执行引擎 |
| **建议提交** | `feat: V2.5.0 计划调度、执行桥接、观测推进与重规划裁决` |

## 1.1 Goal

交付计划执行引擎四组件，并把**双层重试语义对齐**：

1. **`PlanScheduler`**（`app/services/planning/scheduler.py`）：就绪排序（先搬后改，行为零变更）+ 新增 `ready_steps` / `blocked_reason`。
2. **`PlanExecutorBridge`**（`app/services/planning/executor_bridge.py`）：`to_intent` / `execute_step` / `reconcile`，把一步 Task 变成一次 Action。
3. **`PlanObserver`**（`app/services/planning/observer.py`）：`collect_facts` 四源 / `observe` / `evaluate` / `settle`。
4. **`PlanRevisionPolicy`**（`app/services/planning/revision.py`）：`should_replan` / `policy_for` / `explain` 纯函数策略。

## 1.2 Scope

**包含**

- 新建 `app/services/planning/scheduler.py`：搬运 `goal_observation._execution_order` / `_current_step` / `_all_done` / `_has_executable` 为公开纯函数，**先搬后改**；新增 `ready_steps` / `blocked_reason`。
- 新建 `app/services/planning/executor_bridge.py`：`to_intent` / `execute_step` / `reconcile`；两道防御性断言（就绪复核 + 面复核）。
- 新建 `app/services/planning/observer.py`：`collect_facts`（四源，含新增 `tool` 源）/ `observe` / `evaluate` / `settle`。
- 新建 `app/services/planning/revision.py`：四个理由码判定 + 保留已完成步骤策略 + `explain` 审计。
- **B5 关闭点**：Action 层技术性重试与 Plan 层业务性放弃的双层语义对齐。
- 失败处理完整判定树（`blocked` 四类 + `failed` / `timeout` + 观测 `error`）与 `on_failure` 四值矩阵落地。
- 挂载：`life_loop._step_goal_advance` 内部改走 `PlanObserver.collect_facts` + `observe`（**不改签名**）。

**不包含（Non-Scope）**

- 工具治理链的链路断言与闸门 5/6 的工具状态用例（属 PLAN-006）。
- 世界写入路径与终态广播（属 PLAN-008）。
- 计划终态记忆（属 PLAN-009）。
- 证据窗与重规划监听器（属 PLAN-010）。
- 自治 `plan_facts`（属 PLAN-007）。
- `goal_repository` 只读扩展（属 PLAN-011）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 中的 **B1（执行层没有多步计划）**、**B5（重试语义双份且不对齐）**、**B7（判据事实源缺第四类）**、**B8（无计划可观测面）**：

| 断层 | 本任务的关闭方式 |
|---|---|
| B1 | 多步由**计划层**编排：`PlanScheduler` 决定「下一步做哪个」，`PlanExecutorBridge` 逐步映射为**单步** `ActionIntent`；`action_plan_max_steps` **保持 1**（红线 3） |
| B5 | Action 层管技术性重试（退避数学唯一一份），Plan 层管业务性放弃（`v25_plan_step_max_attempts`）；`attempt_count` 仅在 Action 终态递增 |
| B7 | `PlanObserver.collect_facts` 新增 `tool` 源；`evaluate` 委托扩展后的 `evaluate_criteria` |
| B8 | `PlanAdvance` 落 `decision_records`（复用既有 `kind='goal_lifecycle'`），计划阶段子步骤记入 `loop_runs.steps` |

**本任务最容易写错的一处**：`PlanRevisionPolicy` 的「保留已完成步骤」策略。`dedupe_key` 是 `plan:{goal_id}:{version}:{index}`，版本号变化会让所有步骤的幂等键改变——若不保留已完成步骤，重规划会把已经产生世界副作用（如已创建的提醒）的步骤**再做一遍**。这是 architecture §9.6 单列的验收 Gate `G-RETRY`。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Memory 2.0** | **不涉及写入**；`collect_facts` 的 `memory` 源复用既有活跃记忆读取 |
| **Reflection System** | **不涉及**（重规划理由码 `insight_driven` 的触发源属 PLAN-010） |
| **Autonomy 2.0** | **不涉及**（推进意图的候选面接线属 PLAN-007）；但执行经 `source="autonomy"` 因此额度不绕过 |
| **World Simulation** | 终态广播与写入路径属 PLAN-008；本任务只保证 `settle` 不直写世界 |
| **Tool System V2.4.0** | 执行经 `action_engine` 间接调用；本任务不做工具治理断言（PLAN-006） |

**关键事实（已核对真实源码）**

- `app/services/goal_observation.py` 已有四个私有函数：`_execution_order(specs)`（叶子优先）、`_current_step(specs)`、`_all_done(specs)`、`_has_executable(specs)`——**已经是一套 DAG 调度器**，只是以私有函数形态散落。另有 `_save_progress(plan_id, specs, now)` / `_record_lifecycle(record, decision, reason, goal_id)` / `_complete(goal)` / `evaluate_criteria(criteria, facts)` / `_fact_value(facts, source, path)` / `advance_goal(goal, plan, facts, now)` / `advance_user_goals(user_id, facts, now)`。
- `advance_goal` 的 `detail["outcome"]` 取值（既有）：`advanced` / `completed`（经 `_complete` 展开）/ `retrying` / `skipped`（`criteria_result is None`）/ `skipped_ahead` / `replanning` / `failed`。既有 `failure_reason` 常量：`REASON_COMPLETED="goal_completed"` / `REASON_PERIOD_EXCEEDED="exec_period_exceeded"` / `REASON_THRESHOLD_EXCEEDED="subgoal_threshold_exceeded"` / `REASON_REPLAN_EXHAUSTED="replan_exhausted"`。
- `app/services/goal_execution.py::attempt_current_step(goal, plan, now)` 已用 `dedupe_key=f"goal:{goal.id}:{plan.version}:{current.index}"` 映射为 `ActionIntent`，并受 `v2_autonomy_subgoal_execute_cooldown_minutes` 冷却与 `_in_quiet_hours` 静音时段约束；`_USER_FACING_CAPABILITIES = frozenset({"send_notification"})`；调用 `run_action_planning(goal.user_id, intent, session_id=..., goal_id=goal.id, source="autonomy")`。
- `app/application/action_engine.py::run_action_planning(user_id, intent, session_id=None, goal_id=None, source="conversation")` 已实现「门控 + 建记录 + 六闸门 + 装配 + 执行 + 整合」；`RETRYABLE_FAILURES = ("transient", "timeout")`、`ACTIVE_STATUSES = ("created", "planned", "executing")`、`_process_due_retries` 承载退避数学、`integrate_result` 四通道（world via outbox / memory / relationship / note）。
- `app/services/action/planner.py::evaluate_gates(intent, snapshot)` / `assemble_plan(intent, snapshot, now, goal_id=...)` / `_assemble_plan_via_tools`。
- `app/repositories/goal_repository.py::update_plan_progress(plan_id, sub_goals)` 落 `goal_plans`。
- `app/services/life_loop.py` 中 `_step_goal_advance(user_id, now)` 为 async 步，调 `goal_observation.advance_user_goals`。
- `app/models/observability.py::DecisionKind` 五值：`proactive_autonomy` / `turn_goal` / `turn_intention` / `turn_behavior` / `goal_lifecycle`——**本任务复用 `GOAL_LIFECYCLE`，不新增 kind**。
- 迁移链头 0046。

## 2.2 为什么需要本任务

架构 §1.1 指出：**「有执行编排，但只能走一步」**（`planner.assemble_plan` 两条分支恒产 `ActionStep(index=0, ...)`，`action_plan_max_steps` 默认 1 且全仓无消费点）。多步只能靠计划层，而计划层恰恰没有执行纪律。本任务就是给计划层装上**调度 → 执行 → 观测 → 修订**的完整纪律，同时**不放开** `action_plan_max_steps`。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 拓扑序、就绪集、当前步、终态判定（先搬后改，行为零变更） | `PlanScheduler` |
| R2 | 阻塞原因可读化（`off_surface` / 冷却中 / 前置失败） | `PlanScheduler.blocked_reason` |
| R3 | 步骤 → `ActionIntent` 的确定性映射（步级 `dedupe_key`） | `PlanExecutorBridge.to_intent` |
| R4 | 步骤执行（唯一入口 `action_engine.run_action_planning`）与结果归一 | `PlanExecutorBridge.execute_step` |
| R5 | 结果回填（`status` / `attempt_count` / `last_attempt_at` / `failure_note`） | `PlanExecutorBridge.reconcile` |
| R6 | 四源事实包（world / state / memory / **tool**） | `PlanObserver.collect_facts` |
| R7 | 推进与终态结算（唯一改 `GoalStatus` 入口） | `PlanObserver.observe` / `settle` |
| R8 | 判据求值委托与不可判定语义（绝不默认 `True`） | `PlanObserver.evaluate` |
| R9 | 四条重规划判据与保留已完成步骤策略 | `PlanRevisionPolicy` |
| R10 | 双层重试对齐与 `on_failure` 四值矩阵落地 | 跨组件 |
| R11 | 挂进 `life_loop._step_goal_advance`（不改签名） | 挂载接线 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 工具绑定与拆解 | PLAN-004 |
| N2 | 六源装配与七道闸 | PLAN-003 |
| N3 | 工具治理链路断言与闸门 5/6 的工具状态用例 | PLAN-006 |
| N4 | 世界写入路径（`deferred_world_op` → outbox）与终态广播 | PLAN-008 |
| N5 | 计划终态记忆候选与边界表 | PLAN-009 |
| N6 | 计划证据窗与 `PlanningRevisionListener` | PLAN-010 |
| N7 | `insight_driven` 的实际触发源 | PLAN-010（本任务只定义理由码与判定接口） |
| N8 | 自治 `plan_facts` 与候选面接线 | PLAN-007 |
| N9 | `goal_repository` 只读扩展与审计投影 | PLAN-011 |
| N10 | 宣布退避数学 | **永不**（退避只有一份，在 Action 层） |

## 3.3 职责边界一句话

> **`PlanScheduler` 说「下一个做哪步」；`PlanExecutorBridge` 说「这一步怎么变成一次 Action」；`PlanObserver` 说「做成了没有」；`PlanRevisionPolicy` 说「这个做法还行不行」。四者都不执行工具、都不退避、都不写世界。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/scheduler.py` | **新增（搬运 + 扩展）** | 纯函数调度：零 IO、零 LLM | → `models/goal.py`（`SubGoalSpec`）/ `models/plan.py` |
| `app/services/planning/executor_bridge.py` | **新增** | 翻译（Task → ActionIntent）+ 回收（ToolResult → PlanStepOutcome）+ 回填 | → `action_engine.run_action_planning`（**唯一执行入口**）/ `goal_repository.update_plan_progress` / `normalize_core_params` |
| `app/services/planning/observer.py` | **新增** | 事实收集 + 推进 + 终态结算 | → 既有 `goal_observation.advance_goal` / `evaluate_criteria` / `goal_repository`（唯一写面）/ `goal_arbitration.record_goal_lifecycle` / `action_repository`（只读） |
| `app/services/planning/revision.py` | **新增** | 纯函数策略：四个理由码 + 保留步 + 审计 | → `models/plan.py`（`RetryPolicy`），**零 IO** |
| `app/application/life_loop.py` | **最小接线** | `_step_goal_advance` 内部改走 `PlanObserver` | 签名不变 |

**分层纪律（静态断言强制）**
- `app/services/planning/` 零 `world_repository` 导入（G-WORLD）。
- `app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute`（G-EXEC）。
- `scheduler.py` / `revision.py` 零 IO、零 LLM（纯函数）；`observer.py` 的 `facts` 由调用方注入。

### 4.1.2 Component 划分

```text
app/services/planning/scheduler.py（纯函数、零 IO、零 LLM）
├── order(plan) -> list[int]                 # 拓扑序（叶子优先，继承 _execution_order 语义）
├── ready_steps(plan) -> list[PlanStepSpec]  # 前驱全 done 且自身 pending
├── current_step(plan) -> PlanStepSpec|None  # 下一个待执行步（继承 _current_step）
├── all_done(plan) -> bool                   # 继承 _all_done
├── has_executable(plan) -> bool             # 继承 _has_executable
└── blocked_reason(plan, ctx) -> str|None    # 新增：off_surface / cooldown / predecessor_failed

app/services/planning/executor_bridge.py
├── to_intent(goal, plan, step, ctx) -> ActionIntent
│       · action_type 由 (capability, action) 经既有映射反查
│       · params 由 step.params 规范化（normalize_core_params）
│       · dedupe_key = plan:{goal.id}:{plan.version}:{step.index}      ← 步级幂等
│       · confidence = "confident"
├── execute_step(goal, plan, step, ctx) -> PlanStepOutcome
│       · ① 就绪复核（防御）：ready_steps 不含该步 → outcome=skipped
│       · ② 面复核（防御）：tool_id ∉ 当前面 → outcome=blocked
│       · ③ 委托 action_engine.run_action_planning(..., source="autonomy")
│       · ④ 从 record.steps[0].result 读 ToolResult → 归一为 PlanStepOutcome
└── reconcile(outcome, step) -> PlanStepSpec   # 只写内存副本

app/services/planning/observer.py
├── collect_facts(user_id, ctx) -> dict        # 四源事实包（含 tool 源）
├── observe(goal, plan, facts, *, now) -> PlanAdvance   # 委托既有 advance_goal
├── evaluate(criteria, facts) -> bool | None    # 委托 evaluate_criteria（扩展事实源）
└── settle(goal, plan, advance) -> PlanOutcome  # 终态：completed / failed / blocked

app/services/planning/revision.py（纯函数）
├── should_replan(outcome, plan, ctx) -> str | None     # 返回重规划理由，None = 不重规划
├── policy_for(step) -> RetryPolicy                      # 由 step.retry_policy 声明
└── explain(plan, reason) -> dict                        # 可读裁决（进决策审计）
```

### 4.1.3 数据流一：执行链（一次步骤执行的完整路径，零新建环节）

```text
PlanScheduler.current_step(plan)
        │ PlanStepSpec
        ▼
PlanExecutorBridge.to_intent
        │ ActionIntent{action_type, params, dedupe_key=plan:{goal}:{ver}:{idx},
        │              confidence="confident", source="autonomy"}
        ▼
action_engine.run_action_planning（既有，唯一执行编排器）
        ├─ new_record（ActionRecord，status=created）
        ├─ planner.evaluate_gates（六闸门：disabled / ambiguous_params / capability_unavailable
        │                          / duplicate / quota_exceeded / effect_already_satisfied）
        ├─ planner.assemble_plan（v24 总闸 on → _assemble_plan_via_tools → ToolSurface → ToolSelector）
        ├─ action_engine.execute_plan → ToolExecutor.run（五段短路：resolve → permission
        │                                              → validate → invoke → normalize）
        └─ integrate_result（四通道：world via outbox / memory / relationship / note）
        ▼
ActionRecord{status, steps[0].result=ToolResult, attempt, next_retry_at}
        ▼
PlanExecutorBridge.reconcile ──► PlanStepSpec{status, attempt_count, failure_note}
        ▼
goal_repository.update_plan_progress(plan.id, sub_goals)   # 落 goal_plans，零新表
```

### 4.1.4 数据流二：观测推进

```text
PlanObserver.collect_facts(user_id, ctx) → facts（四源）
        │  world   ← world_engine.collect_facts / build_time_context
        │  state   ← character_state / relationship_state（既有读取）
        │  memory  ← 活跃长期记忆（既有读取）
        │  tool    ← 【新增】action_records.steps[].result（ToolResult）
        ▼
PlanObserver.observe(goal, plan, facts, now=now)
        ├─ 委托既有 goal_observation.advance_goal(goal, plan, facts, now)
        └─ 返回 PlanAdvance{decision, reason, step_index, facts_digest, at}
        ▼
PlanObserver.settle(goal, plan, advance)          # 唯一改 GoalStatus 的入口
        ├─ goal_repository.set_status / finish_goal / fail_goal   （迁移表守卫）
        ├─ goal_arbitration.record_goal_lifecycle(...)            （归因行）
        └─ PlanAdvance → decision_records（kind="goal_lifecycle"，decision=上表取值）
        ▼
goal_plans.sub_goals 回填（经 goal_repository.update_plan_progress）
```

### 4.1.5 数据流三：重规划（五步）

```text
PlanRevisionPolicy.should_replan(outcome, plan, ctx) → reason | None
        │ reason ≠ None
        ▼
① 预算检查
   plan.version < v25_plan_revision_budget ？
     ├─ 否 → 计划置 "rejected"（rejection_reason=reason）
     │        → finish_goal(failed, failure_reason="plan_exhausted")
     │        → （可选）goal_arbitration.check_abandonment 裁决放弃
     └─ 是 ↓
② 保留与丢弃
   kept_steps    = [s.index for s in plan.steps if s.status == "done"]
   dropped_steps = 其余
     · 保留步在新版本中复用同 index / 同 criteria（不重做，不重复副作用）
     · 依赖保留步的新步，其 depends_on 语义不变
        ▼
③ 新版本生成（PLAN-003 的 PlanningEngine.revise）
     · PlanContext 装配（★ evidence_refs 携带触发它的 Insight / 记忆）
     · prompt 注入历史：上一次失败步骤的 failure_note + failure_kind + 保留步清单
     · 七道闸重新过（工具面可能已变化）
        ▼
④ 落库与切换
   新 GoalPlanRecord{version=plan.version+1, revision_of=plan.version,
                     trigger="goal_replan", evidence_refs=[...]}
   旧版本 set_plan_status("superseded")
   goal_repository.update_plan_progress（保留步原样搬入）
        ▼
⑤ 审计
   decision_records{kind="goal_lifecycle", decision="plan_revised",
                    input_snapshot={from_version, to_version, reason, evidence_refs}}
```

## 4.2 Core Model

本任务**不新增持久模型**（值对象由 PLAN-002 定义）。下表为本任务的核心数据契约。

### 4.2.1 调度契约（`PlanScheduler` 的输入与输出）

| 项 | 类型 | 说明 |
|---|---|---|
| 输入 `plan` | `GoalPlanRecord` | 含 `version` / `sub_goals` / `status` |
| 输入 `ctx` | `PlanContext` | `blocked_reason` 用它读 `tool_surface` / 关系 / 时段 |
| 输出 `order` | `list[int]` | 拓扑序的步骤序号（叶子优先） |
| 输出 `ready_steps` | `list[PlanStepSpec]` | 前驱全 `done` 且自身 `pending` 的步骤 |
| 输出 `blocked_reason` | `str \| None` | `off_surface` / `cooldown` / `predecessor_failed` / `None` |

### 4.2.2 `PlanStepOutcome`（步骤结果契约，PLAN-002 定义，本任务产出）

| 字段 | 类型 | 本任务的填充来源 |
|---|---|---|
| `step_index` | int | 来自 `step.index` |
| `status` | str | `succeeded` / `failed` / `timeout` / `blocked` / `skipped` / `hold`（映射见 §4.3.4） |
| `action_id` | str \| None | `ActionRecord.id` |
| `tool_id` | str | **实际执行的工具**（从 `ActionRecord.steps[0].tool_id` 读，可能与计划绑定不同——差异回填进审计） |
| `failure_kind` | str \| None | 取值即既有 `TOOL_FAILURE_KINDS`（6 值），**不新增** |
| `attempt` | int | Action 层尝试次数（`ActionRecord.attempt`） |
| `effects` | list[dict] | `ToolResult.effects` 投影（`kind` / `ref` / `reversible`） |
| `observations` | dict | **受 `step.observation_keys` 白名单裁剪后**的键值 |
| `criteria_result` | bool \| None | 判据判定（`None` = 不可判定） |
| `duration_ms` | int \| None | 既有 usage |
| `at` | datetime | 时刻 |

**白名单裁剪是本任务的硬纪律**：`observations` 只保留 `observation_keys` 声明的键，未声明键**一律不可见**（防「偶发字段」变成隐式契约）。

### 4.2.3 `PlanAdvance`（推进裁决，PLAN-002 定义，本任务产出）

| 字段 | 类型 | 本任务填充 |
|---|---|---|
| `goal_id` / `plan_id` / `plan_version` | str / str / int | 主体 |
| `decision` | str | `advanced` / `completed` / `failed` / `replanning` / `skipped` / `hold` |
| `reason` | str | ≤ 60 字（复用既有 `REASON_*` 常量或本任务新增词条） |
| `step_index` | int \| None | 涉及的步骤 |
| `facts_digest` | dict | 判据所用事实摘要（不含敏感内容） |
| `at` | datetime | 时刻 |

### 4.2.4 四源事实包（`collect_facts` 输出）

| 源 | 内容 | 读取入口 | 是否新增 |
|---|---|---|---|
| `world` | 时间 / 时段 / 天气 / 地点 / 显著事件 | `world_engine.collect_facts` / `build_time_context` | ❌（既有） |
| `state` | `tension` / `intimacy` / `mood`（判据 `CRITERION_METRIC_PATHS` 四值所需） | 既有 Character / 关系读取 | ❌（既有） |
| `memory` | `salient_memory_count` 等 | 既有活跃长期记忆读取 | ❌（既有） |
| `tool` | `action_records.steps[].result`（`ToolResult`） | `action_repository` 只读 | **✅ 新增** |

**`tool` 源的判定语义（B7 关闭点）**

| `type` | 判定 | 数据来源 |
|---|---|---|
| `action_succeeded` | `action_records.steps[].status == "succeeded"` | 既有台账 |
| `field_equals` | `ToolResult.observations[key] == value`，`key ∈ step.observation_keys` | V2.4.0 结果契约 |
| `threshold_reached` | **不支持**（`fact_source="tool"` 下拒绝，Q4 冻结） | — |

### 4.2.5 推进结果值集（沿用既有 `advance_goal` 返回值，**不新增**）

| 结果 | 含义 | 后续 |
|---|---|---|
| `advanced` | 当前步达成，指针前移 | 下一 tick 继续 |
| `completed` | 全部步骤达成 | `finish_goal(completed)` + 终态广播（PLAN-008） |
| `retrying` | 当前步失败但未达 Plan 层尝试上限 | 等 `next_retry_at` |
| `failed` | 达上限或 `on_failure=abort` | `finish_goal(failed, failure_reason="plan_exhausted")` |
| `replanning` | 判据不可达 / 工具长期不可用 | `enqueue_planning(TRIGGER_BLOCKED)` |
| `skipped` / `skipped_ahead` | 前置失败导致跳过 | 记录 `failure_note`，不写记忆 |
| `hold` | 等冷却 / 等 `next_retry_at` | 留在计划中等待 |
| `error` | 观测自身异常 | **只 log，不改变计划状态**（与 V9「投递失败不回滚执行」同款纪律） |

> 既有 `advance_goal` 的 `detail["outcome"]` 取值为 `advanced` / `completed` / `retrying` / `skipped` / `skipped_ahead` / `replanning` / `failed`。本任务把它归一为 `PlanAdvance.decision` 的六值（`skipped_ahead` → `skipped`；新增 `hold` 对应「等冷却」这一本任务新增的可观测态，由 `PlanScheduler.blocked_reason` 提供依据）。

### 4.2.6 `RetryPolicy`（消费，PLAN-002 定义）

| `mode` | 语义 | 对应设置 |
|---|---|---|
| `none` | 不重试（业务性一次判定） | — |
| `once`（默认） | Plan 层尝试上限 = 1 次业务判定 | — |
| `until_budget` | Plan 层尝试直到上限 | `v25_plan_step_max_attempts`（默认 2，对齐 `action_retry_max_attempts`） |

### 4.2.7 重规划理由码（四个，本任务判定）

| 理由码 | 触发条件 | 理由码判定依据 |
|---|---|---|
| `step_attempt_exhausted` | 步骤达 Plan 层尝试上限且 `on_failure=replan` | `step.attempt_count ≥ v25_plan_step_max_attempts` |
| `tool_persistently_unavailable` | 工具连续 N 个 tick 始终 `off_surface` | `blocked_reason == "off_surface"` 连续计数达阈 |
| `criteria_undecidable` | `evaluate_criteria` 连续返回 `None` | `criteria_result is None` 连续计数达阈 |
| `insight_driven` | Reflection Insight 达门槛并指向该目标 | PLAN-010 `PlanningRevisionListener` 投递（本任务只定义理由码与判定入口） |

**修订预算与终止**：版本数受 `v25_plan_revision_budget`（默认 3）约束；达上限后计划置 `rejected`（`rejection_reason` 记原因），目标转 `failed`（`failure_reason="plan_exhausted"`）或交 `goal_arbitration.check_abandonment` 裁决放弃。

> **避免「无限重规划」是本模块存在的首要理由**——既有 `goal_planning._LLM_RETRY_ATTEMPTS = 2` 只管 LLM 调用失败，管不了「计划本身行不通」。

## 4.3 State Machine

### 4.3.1 Task 状态机（`SubGoalStatus` 四态，语义强化不改值集）

```text
                    ┌─────────┐
                    │ pending │◄────────────┐
                    └────┬────┘             │ 前置失败 → 重置
        ready（前驱全done）│                 │
                         ▼                 │
                  ┌─────────────┐          │
                  │ in_progress │──────────┘
                  └──────┬──────┘
        ┌────────────────┼────────────────┬──────────────┐
        │                │                │              │
   判据达成          执行失败           前置失败      计划被修订
        │           （未达上限）        （on_failure）   （被丢弃）
        ▼                ▼                ▼              ▼
   ┌──────┐     （留在 in_progress）  ┌────────┐    （不在新版中）
   │ done │       等 next_retry_at    │ failed │
   └──────┘                           └────────┘
```

| 状态 | 进就绪集 | 计 `attempt_count` | 语义 |
|---|---|---|---|
| `pending` | ✅（前驱全 `done` 时） | ❌ | 待执行 |
| `in_progress` | ✅（等冷却 / 等重试） | ✅ | 已发出 Action，等终态 |
| `done` | ❌ | ✅ | 判据达成（**唯一推进后继的状态**） |
| `failed` | ❌ | ✅ | 达 Plan 层尝试上限或 `on_failure=abort` |

### 4.3.2 `on_failure` 四值 × 后继矩阵

| `on_failure` | 本步终态 | 后继步骤 | 计划终态 |
|---|---|---|---|
| `abort` | `failed` | 全部置 `failed` | `failed`（目标 `failed`，`failure_reason="plan_exhausted"`） |
| `skip` | `failed` | **直接后继** `failed`，旁支继续 | 视剩余步骤判定 |
| `replan` | `failed` | 暂停 | 触发 `TRIGGER_REPLAN` |
| `continue` | `failed` | 全部继续（`depends_on` 语义被**显式放宽**） | 视其余步骤判定 |

### 4.3.3 Goal × Plan × Task 三者联动

```text
GoalStatus        GoalPlanStatus        SubGoalStatus         谁驱动
──────────────────────────────────────────────────────────────────────────────
active       ┌──  validated       ┌──  pending          goal_planning
             │                     │
             │    active         ◄──┘  in_progress       PlanExecutorBridge
             │      │                    │                （经 action_engine）
             │      │                    ▼
             │      │                 done ──► 后继 pending  PlanScheduler + PlanObserver
             │      │                    │
             │      └── completed ◄──────┘（全 done）       PlanObserver.settle
             │
             ├──  rejected（不改变 Goal）                    PlanningEngine 闸门
             │
             ├──  superseded（新版产生）                      PlanRevision（PLAN-003 revise）
             │
suspended  ◄─┴──  计划冻结（不推进）                          goal_arbitration
failed     ◄────  达修订预算 / on_failure=abort              PlanRevisionPolicy
abandoned  ◄────  check_abandonment 双信号                   goal_arbitration
```

### 4.3.4 `PlanStepOutcome.status` 与 V9 `ActionStatus` 映射

| `PlanStepOutcome.status` | 映射到 `ActionRecord.status` | `gate_reason` | 说明 |
|---|---|---|---|
| `succeeded` | `succeeded` | — | 一致 |
| `failed` | `failed` | — | `failure_kind=permanent` |
| `timeout` | `failed` | — | `failure_kind=timeout`（可重试） |
| `blocked` | `cancelled` | `capability_unavailable` / `permission_denied` / `invalid_params` / `pending_confirmation` | 均属「未执行」，复用 V9 cancelled 语义 |
| `skipped` | —（无 `ActionRecord`） | — | 前置失败导致，不产生行动 |
| `hold` | `planned`（等 `next_retry_at`） | — | 留在计划中等待 |

> **不新增 `ActionStatus` 值，不新增 `GATE_REASONS` 值**。V9 六态 + V2.4.0 已扩的十值 `GATE_REASONS` 已完备。

### 4.3.5 双层重试状态迁移（B5 关闭点）

```text
Step 执行失败（ActionRecord.status = failed）
        │
        ▼
① Action 层重试（既有，技术性）
   failure_kind ∈ {transient, timeout}（= RETRYABLE_FAILURES）且 attempt < action_retry_max_attempts(2)
        ├─ 是 → ActionRecord.status = executing，next_retry_at = now + 30 * 2^(attempt-1)
        │        （由 action_engine._process_due_retries 消费）
        └─ 否 → ActionRecord 终态 failed
        │
        ▼
② Plan 层裁决（本任务，业务性）
   PlanExecutorBridge.reconcile(step, action_record)
        ├─ step.attempt_count += 1（★ 仅在此刻，与 executing 中间态解耦）
        ├─ step.status = in_progress（若 attempt_count < v25_plan_step_max_attempts）
        │    或 failed（若达上限）
        └─ 达上限 → PlanRevisionPolicy.should_replan(outcome, plan, ctx)
              ├─ on_failure=replan   → TRIGGER_REPLAN（新版本）
              ├─ on_failure=skip     → 后继按 §4.3.2 矩阵处置
              ├─ on_failure=abort    → 计划 failed
              └─ on_failure=continue → 忽略本步，继续旁支
```

**双层计数的职责边界**

| 关注 | 层 | 设置 | 回答的问题 |
|---|---|---|---|
| 技术性重试 | Action | `action_retry_max_attempts=2` / `action_retry_backoff_seconds=30` | 「是不是网络抖了一下？」 |
| 业务性放弃 | Plan | `v25_plan_step_max_attempts`（默认 2） | 「这个做法是不是不行了？」 |

**退避数学只有一份**（Action 层）。Plan 层**不等待、不退避**——它只在 Action 落终态后做一次裁决。

### 4.3.6 失败处理完整判定树

```text
步骤执行返回
    │
    ├─ status = succeeded
    │     ├─ criteria 判定 = True   → step.done → 推进后继
    │     ├─ criteria 判定 = False  → step.in_progress（attempt_count+1）
    │     │      └─ 达上限 → PlanRevisionPolicy（§4.3.5 ②）
    │     └─ criteria 判定 = None   → step.in_progress，登记 criteria_undecidable
    │            └─ 连续 N 轮仍 None → 触发重规划（判据不可达）
    │
    ├─ status = blocked（未执行：denied / invalid / pending_confirmation / unavailable）
    │     ├─ permission_denied     → step.failed，on_failure 语义生效；★ 不重试（授权拒绝非瞬时）
    │     ├─ invalid_params        → step.failed（permanent），on_failure 语义生效
    │     ├─ pending_confirmation  → step.in_progress，等既有确认流（run_confirmation_round）
    │     │      · 用户批准 → action_engine 续跑 → 回 succeeded 分支
    │     │      · 用户否定 / TTL 过期 → step.failed
    │     └─ capability_unavailable → step.in_progress，等下一 tick 复面
    │            └─ 持续 off_surface → 触发重规划（换工具）
    │
    ├─ status = failed / timeout
    │     └─ 交 Action 层重试（§4.3.5 ①）→ 终态后回 Plan 层裁决（§4.3.5 ②）
    │
    └─ 观测自身 error
          → 只 log，step 状态不变（不把观测故障误判成执行故障）
```

**失败分类与处置对照**

| `failure_kind` | 是否重试 | Plan 层动作 | 记忆沉淀 |
|---|---|---|---|
| `transient` | ✅ Action 层退避重试 | 达上限后按 `on_failure` | 达上限且 `abort`/`replan` → 沉淀（未完成语义，PLAN-009） |
| `timeout` | ✅ Action 层退避重试 | 同上 | 同上 |
| `permanent` | ❌ | 直接按 `on_failure` | 仅 `abort` 时沉淀 |
| `unavailable` | ❌（等面恢复） | 持续不可用 → 重规划 | ❌ |
| `denied`（权限） | ❌ | 按 `on_failure`；**不得**自动绕过 | ❌ |
| `invalid`（参数） | ❌ | 按 `on_failure`；可重规划换参数 | ❌ |

**三条总原则（承 V9 / V2.4.0 纪律）**
1. 失败永不静默假成功——判据未达成即未达成，禁止「看起来差不多就算完成」。
2. 失败永不阻塞用户回复——计划失败不影响本轮对话质量。
3. 所有失败必有台账——落 `action_records` + `decision_records`，否则反思无从下手。

## 4.4 调度规则（确定性，可复现）

| 规则 | 说明 |
|---|---|
| 依赖优先 | `depends_on` 必须全为 `done`；前驱 `failed` 且 `on_failure=abort` → 后继标 `skipped` |
| 叶子优先 | 父步（`parent_index` 非空）不作为执行单元，只在子步全 `done` 后由 `advance_goal` 结算 |
| 结构序 | 同一层就绪步按 `index` 升序；**不按 Goal priority 重排**（PLAN-001 §4.3.4） |
| 单步并发上限 | 每 tick 每目标最多推进一步（对齐 `v2_autonomy_subgoal_execute_cooldown_minutes` / `v25_plan_step_cooldown_minutes`） |
| 面感知 | `ready` 但 `tool_id` 不在当前工具面 → 不进「可执行」，记 `blocked_reason=off_surface` |
| 幂等锚点 | 步骤幂等键沿用既有形态 `goal:{goal_id}:{plan.version}:{step.index}`（`goal_execution` 既有公式，用于 Action 层对照）；计划侧 `dedupe_key` 为 `plan:{goal_id}:{plan.version}:{step.index}` |

## 4.5 `blocked_reason` 值集（三值 + 空）

| 值 | 触发条件 | 可观测后果 |
|---|---|---|
| `off_surface` | 就绪步的 `tool_id` ∉ 当前工具面 | `hold`；连续 N tick 后触发 `tool_persistently_unavailable` 重规划 |
| `cooldown` | 距 `step.last_attempt_at` 不足 `v25_plan_step_cooldown_minutes` | `hold` |
| `predecessor_failed` | 前驱 `failed` 且本步未被 `continue` 显式放宽 | `skipped` |
| `None` | 存在可执行步 | 正常推进 |

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 谁决定「此刻做什么」 | `autonomy_policy.evaluate` + `decision_pipeline`（既有） | **不涉及** |
| `plan_facts` / 候选面 | PLAN-007 | **不涉及** |
| 额度不绕过 | 步骤执行经 `run_action_planning(source="autonomy")` | **本任务落地点**：正因走该入口，`action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` 与冷却窗口原样生效 |

**为什么本任务只落「不绕过」而不做「感知」**：计划触发的执行走既有编排器入口（`source="autonomy"`），额度与冷却天然生效——这是结构性的，不需要额外代码。「自治侧感知计划事实」（`plan_facts`）是反向的接线，属 PLAN-007。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 步骤执行 | 经 `action_engine.run_action_planning` → `assemble_plan` → `ToolSelector` → `ToolExecutor.run`（五段短路） | **唯一入口**，不直调 |
| 工具面复核 | `execute_step` 的②面复核（防御性） | **本任务实现**（防止「规划到执行之间世界 / 关系 / 时段变化」） |
| `ToolResult` 契约 | 归一为 `PlanStepOutcome` | **本任务实现** |
| `confirm_required` | 等既有确认流 | **本任务保证不自动绕过**：`pending_confirmation` → `step.in_progress`，等 `run_confirmation_round` |
| 治理链路断言 / 闸门 5/6 工具状态用例 | PLAN-006 | **本任务不做完整断言**（仅保证不绕过） |

**校验分层**：强校验（结构 + 语义）唯一权威是执行期 `ParamValidator.validate`；本任务不做参数的二次校验（避免与执行期分歧）。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `collect_facts` 的 `world` 源 | `world_engine` 只读 | **消费** |
| 计划写世界 | `deferred_world_op` → outbox → `world_engine`（由工具效果自动产生） | **不涉及实现**：本任务禁止 import `world_repository`，禁止直接创建世界副作用 |
| 终态广播 | `event_bridge.register_goal_event` | **不涉及**（PLAN-008） |
| 关系域效果 | 只经工具 `effects(kind=relationship)` → `relationship_bridge` | **不涉及实现**：本任务禁止直写 `relationship_*` |

**为什么不涉及**：本任务的 `settle` 只改 `GoalStatus`（经唯一写面）；世界写入与广播由既有 Action `integrate_result` 与 PLAN-008 的接线承担。**本任务不新增任何世界写路径。**

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `collect_facts` 的 `memory` 源 | 活跃长期记忆只读 | **消费** |
| 计划终态记忆候选 | PLAN-009 | **不涉及** |
| `memories` 写入 | 必须经 `memory_policy` R1~R8 | **本任务零写入 `memories`** |

**为什么不涉及**：`PlanObserver.settle` 只结算 `GoalStatus` 与写审计；记忆候选构造与边界表属 PLAN-009。

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 重规划理由码 `insight_driven` | 判定入口在本任务 | **定义理由码与判定接口**；实际触发源（监听器）属 PLAN-010 |
| 证据窗 / 计划证据投影 | PLAN-010 | **不涉及** |
| `PlanAdvance` 作为证据素材 | 落 `decision_records` | **本任务实现**（为 PLAN-010 的证据投影提供数据） |

**边界**：本任务**不读 Insight、不调 `notify_insight_created_listeners`**；`insight_driven` 的到达路径是「PLAN-010 的监听器 → `enqueue_planning(TRIGGER_REPLAN)` → PLAN-003 的 `revise` → 新版本」，本任务只提供 `should_replan` 的理由码枚举位。

## 5.6 与 Life Loop / Runtime

| 关注点 | 既有形态 | 本任务接线 |
|---|---|---|
| `life_loop._step_goal_advance(user_id, now)` | async 步，调 `goal_observation.advance_user_goals` | **不改签名**；内部改走 `PlanObserver.collect_facts` + `observe` |
| `life_loop._run_user_cycle` 九步序列 | 九步固定 | **序列不变** |
| `loop_runs.steps` | `mark_step` | 计划阶段以子步骤记入（`plan_execute` / `plan_observe`），受既有 `budget_state` 约束 |
| `action_engine._process_due_retries` | 既有维护步（`life_loop._run_maintenance` 的 `action_retry`） | **复用**，Plan 层不新增维护步 |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 七道闸 | 不涉及 | PLAN-003 |
| 工具绑定与拆解 | 不涉及 | PLAN-004 |
| 治理链路断言 / 闸门 5/6 用例 | 不涉及 | PLAN-006 |
| outbox / `event_bridge` | 不涉及 | PLAN-008 |
| `memories` / `memory_policy` | 不涉及 | PLAN-009 |
| `reflection/evidence.py` / 监听器 | 不涉及 | PLAN-010 |
| `PolicySnapshot` / `decision_pipeline` | 不涉及 | PLAN-007 |
| `goal_repository` 只读扩展 / 调试端点 | 不涉及 | PLAN-011 |

---

# 6. API / Interface Design

## 6.1 `PlanScheduler` 接口（纯函数、零 IO、零 LLM）

```text
interface PlanScheduler:
    order(plan: GoalPlanRecord) -> list[int]
    ready_steps(plan: GoalPlanRecord) -> list[PlanStepSpec]
    current_step(plan: GoalPlanRecord) -> PlanStepSpec | None
    all_done(plan: GoalPlanRecord) -> bool
    has_executable(plan: GoalPlanRecord) -> bool
    blocked_reason(plan: GoalPlanRecord, ctx: PlanContext) -> str | None
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 全部函数**同输入同输出**（可复现锚点，对齐 `ToolSurface.surface_hash` 工程标准） | 重复运行断言 |
| D2 | 搬运版本与 `goal_observation` 私有实现**逐条一致** | 等价性对照测试（§9.1 U1） |
| D3 | 零 IO、零 LLM、零 `get_settings()` 直调 | 静态断言 |

## 6.2 `PlanExecutorBridge` 接口

```text
interface PlanExecutorBridge:
    to_intent(goal: GoalRecord, plan: GoalPlanRecord, step: PlanStepSpec, ctx: PlanContext) -> ActionIntent
    execute_step(goal: GoalRecord, plan: GoalPlanRecord, step: PlanStepSpec, ctx: PlanContext) -> PlanStepOutcome
    reconcile(outcome: PlanStepOutcome, step: PlanStepSpec) -> PlanStepSpec
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D4 | `to_intent` 必须产出**确定性** `dedupe_key`（`plan:{goal_id}:{version}:{index}`），且不得生成空 `action_type` | 用例断言 |
| D5 | `execute_step` **只**经 `action_engine.run_action_planning` 执行，不得直接调 `Capability.execute` 或 `ToolExecutor.run` | 静态断言（G-EXEC） |
| D6 | `reconcile` 只写 `PlanStepSpec` 的**内存副本**；落库由调用方（`PlanObserver` / `life_loop` 步）统一完成 | 静态断言 `reconcile` 零仓储调用 |
| D7 | `attempt_count` 只在步骤**达到 Action 终态**（`succeeded` / `failed`）时递增 | 用例断言（中间态不递增） |
| D8 | Plan 层**零退避**（无等待、无 sleep、无 `next_retry_at` 计算） | 静态与运行时断言 |

## 6.3 防御性断言（不是第二次决策）

| # | 断言 | 触发条件 | 结果 |
|---|---|---|---|
| A1 | 就绪复核 | `PlanScheduler.ready_steps(plan)` **不**包含 `step` | `outcome.status = "skipped"`，不执行 |
| A2 | 面复核 | `step.tool_id ∉ ToolSurfaceResolver.resolve(...).tool_ids` | `outcome.status = "blocked"`（`gate_reason="capability_unavailable"`），不执行 |

**为什么是「防御性」而非「第二次决策」**：`to_intent` 不再做「要不要用这个工具」的判断——那已在规划期（闸门 5/6）与决策期（Autonomy）完成。执行期的 A1 / A2 用于防「规划到执行之间世界 / 关系 / 时段变化」，**不改变计划内容**。

## 6.4 `PlanObserver` 接口

```text
interface PlanObserver:
    collect_facts(user_id: str, ctx: PlanContext) -> dict                  # 四源事实包
    observe(goal: GoalRecord, plan: GoalPlanRecord, facts: dict, *, now: datetime) -> PlanAdvance
    evaluate(criteria: dict, facts: dict) -> bool | None                    # 委托既有 evaluate_criteria
    settle(goal: GoalRecord, plan: GoalPlanRecord, advance: PlanAdvance) -> PlanOutcome
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D9 | `observe` 的 `facts` 由**调用方注入**，组件内零 IO | 静态断言 |
| D10 | `evaluate` 对**未声明**判据或无对应事实一律返回 `None`（不可判定），**绝不默认 `True`** | 用例断言 |
| D11 | `settle` 是**唯一**改 `GoalStatus` 的入口，必经 `goal_repository.set_status` / `finish_goal` 并调 `goal_arbitration.record_goal_lifecycle` | 静态 + 运行时断言 |
| D12 | 计划推进审计落 `decision_records`，**复用既有 `kind='goal_lifecycle'` + 差异化 `decision` 值，不新增 kind** | 值集对照（`ck_decision_records_kind` 仍五值） |
| D13 | 观测自身 `error` 只 log、不改变计划状态 | 用例断言 |

## 6.5 `PlanRevisionPolicy` 接口（纯函数）

```text
interface PlanRevisionPolicy:
    should_replan(outcome: PlanStepOutcome, plan: GoalPlanRecord, ctx: PlanContext) -> str | None
    policy_for(step: PlanStepSpec) -> RetryPolicy
    explain(plan: GoalPlanRecord, reason: str) -> dict
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D14 | 不执行任何动作，只返回理由码；入队由调用方完成 | 静态断言（零 `enqueue` / 零仓储调用） |
| D15 | 修正路径必须携带 `kept_steps`（已完成步骤的 `index` 列表） | 用例断言（G-RETRY） |

## 6.6 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| `IllegalGoalTransition` | `goal_repository`（`settle` 转终态时） | 不吞；log + 不改变计划状态（与「观测 error 只 log」同款纪律） |
| 执行期异常（`run_action_planning` 内部） | Action 层 | `execute_step` 捕获 → `outcome.status = "failed"`（`failure_kind=permanent`），不向上抛 |
| `reconcile` 输入 `step` 与 `outcome.step_index` 不匹配 | 编程缺陷 | 抛（实现缺陷，非业务结果） |
| 观测自身异常 | `collect_facts` / `observe` | 只 log，计划状态不变，`advance.decision = "hold"` |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 步骤执行台账复用 `action_records.steps`；计划推进审计复用 `decision_records`；运行态序列复用 `loop_runs.steps` |
| 新列 | 无 | 步骤状态回填落 `goal_plans.sub_goals`（既有 JSON）；`PlanAdvance` 落 `decision_records.input_snapshot`（既有 JSON）；`facts_digest` 同列 |
| 新索引 | 无 | 本任务不引入新查询维度（推进候选由既有 `list_active_plans` 提供） |
| 改 CHECK | 无 | `ck_decision_records_kind` 五值不变（复用 `goal_lifecycle`）；`ck_goal_plans_status` 五值不变 |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面（全部为既有列 / 既有函数）**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| 步骤执行台账 | `action_records.steps` | `action_engine` / `action_repository.save_record`（经 `run_action_planning`） | ❌ |
| 世界副作用 | `action_records` + outbox | `action_repository.save_record_with_outbox`（经工具效果） | ❌ |
| 步骤状态回填 | `goal_plans.sub_goals` | `goal_repository.update_plan_progress` | ❌ |
| 目标终态 | `character_goals` | `goal_repository.set_status` / `finish_goal` / `fail_goal` | ❌ |
| 推进审计 | `decision_records` | 既有决策记录写入 + `goal_arbitration.record_goal_lifecycle` | ❌ |
| 运行态子步骤 | `loop_runs.steps` | `loop_run_repository.mark_step` | ❌ |
| 重规划入队 | `background_jobs` | `background_job_repository.enqueue_job`（`job_type='goal_planning'`） | ❌ |

> **零新建表的结论**：计划本体 → `goal_plans`（既有）；步骤执行台账 → `action_records.steps`（V9 既有 + V2.4.0 已扩 `tool_id` / `permission` / `validation`）；计划审计 → `decision_records`（复用 `kind='goal_lifecycle'`，`decision` 承载计划迁移名）；运行态序列 → `loop_runs.steps`（既有）。**不为计划系统新建第二张执行表，也不为它新建审计表。**

---

# 8. Implementation Plan

## Step 1 — `PlanScheduler` 搬运（先搬后改，行为零变更）

1. 把 `goal_observation._execution_order` / `_current_step` / `_all_done` / `_has_executable` 逐一搬运为 `scheduler.py` 的公开纯函数（`order` / `current_step` / `all_done` / `has_executable`），**签名与服务逻辑保持等价**。
2. 保留 `goal_observation` 原私有函数一个版本窗口（本版本不改其调用点，只新增公开出口），保证搬运期可对照。
3. **等价性对照测试**：同一 plan（含深层嵌套与 `depends_on` DAG 用例）下，新旧实现输出逐条一致（§9.1 U1）。**此步未通过前，不得进入 Step 4 / Step 5。**
4. 新增 `ready_steps(plan)`：前驱全 `done` 且自身 `pending`。
5. 新增 `blocked_reason(plan, ctx)`：`off_surface` / `cooldown` / `predecessor_failed` 三类（§4.5）。

## Step 2 — `PlanExecutorBridge.to_intent` 与 `reconcile`

1. `to_intent`：由 (`capability`, `action`) 反查既有映射得 `action_type`；`params` 经 `normalize_core_params`；`dedupe_key = plan:{goal_id}:{version}:{index}`；`confidence="confident"`；`source="autonomy"`（随 `run_action_planning` 参数传入）。
2. 禁止空 `action_type`（若反查失败，抛实现缺陷异常而非静默构造）。
3. `reconcile`：把 `PlanStepOutcome` 回填到 `PlanStepSpec` 的内存副本（`status` / `attempt_count` / `last_attempt_at` / `failure_note`）；**只在 Action 终态时递增 `attempt_count`**。
4. 单测：`dedupe_key` 唯一且可复现；`to_intent` 不产出空 `action_type`；`attempt_count` 时机。

## Step 3 — `PlanExecutorBridge.execute_step`

1. 防御性断言 A1（就绪复核）→ `outcome.status = "skipped"`。
2. 防御性断言 A2（面复核）→ `outcome.status = "blocked"`（`gate_reason="capability_unavailable"`）。
3. 委托 `action_engine.run_action_planning(user_id, intent, session_id, goal_id=goal.id, source="autonomy")`（**唯一执行入口**）。
4. 从 `record.steps[0].result` 读 `ToolResult`（V2.4.0 契约）→ 归一为 `PlanStepOutcome`；`observations` 按 `step.observation_keys` 白名单裁剪。
5. 落库由调用方完成：`goal_repository.update_plan_progress(plan.id, sub_goals)`。
6. 单测：A1 / A2 两个断言路径；`ToolResult → PlanStepOutcome` 归一（含 `failure_kind` 取值 ⊆ 既有六值）；白名单裁剪。

## Step 4 — `PlanObserver.collect_facts` 与 `evaluate`

1. `collect_facts` 组装四源：`world`（`world_engine`）/ `state`（Character / 关系读取）/ `memory`（活跃长期记忆）/ **`tool`（`action_records.steps[].result`）**。
2. `tool` 源的键可见性受 `observation_keys` 白名单约束；未声明键不进事实包。
3. `evaluate` 委托既有 `goal_observation.evaluate_criteria`，并把 `tool` 源的 `action_succeeded` / `field_equals` 判定接入（**不新增判据类型**）。
4. 未声明判据 / 无对应事实 → 返回 `None`（**绝不默认 `True`**）。
5. 单测：四源两态；`fact_source="tool"` 的两类判定端到端；`None` 语义。

## Step 5 — `PlanObserver.observe` 与 `settle`

1. `observe` 委托既有 `goal_observation.advance_goal(goal, plan, facts, now)`，把 `detail["outcome"]` 归一为 `PlanAdvance.decision`（六个值，`skipped_ahead` → `skipped`）。
2. `settle`：`completed` → `finish_goal(completed)`；`failed` → `finish_goal(failed, failure_reason="plan_exhausted")`；`blocked` → 冻结不写；每次终态调 `goal_arbitration.record_goal_lifecycle` 一次。
3. `PlanAdvance` 写 `decision_records`（`kind="goal_lifecycle"`，`decision` 承载取值，`input_snapshot` 承载 `PlanAdvance`）。
4. 观测 `error` → 只 log，计划状态不变（`decision="hold"`）。
5. 单测：`settle` 零旁路；`decision_records.kind` 仍五值；观测 error 隔离。

## Step 6 — `PlanRevisionPolicy`

1. `should_replan` 四条判据（§4.2.7），返回理由码或 `None`。
2. **保留已完成步骤策略**：`kept_steps = [s.index for s in plan.steps if s.status == "done"]`；新版本复用同 `index` / 同 `criteria`，不重做、不重复副作用。
3. 修订预算：`plan.version < v25_plan_revision_budget`；达上限 → 计划 `rejected` + 目标 `failed("plan_exhausted")`（或交 `check_abandonment`）。
4. `explain(plan, reason)` 返回可读裁决 dict，进计划审计。
5. `policy_for(step)` 由 `step.retry_policy` 映射为 `RetryPolicy`（引用 settings，**不自建退避**）。
6. 单测：四类触发判据各一例；**保留步不重做**（`deferred_world_op` 计数验证）。

## Step 7 — 失败判定树与 `on_failure` 矩阵

1. 落地 §4.3.6 完整判定树：`blocked` 四类各有处置（`permission_denied` 不重试 / `invalid_params` 转 `permanent` / `pending_confirmation` 等既有确认流 / `capability_unavailable` 等下一 tick 复面并计入 `off_surface`）。
2. 落地 §4.3.2 `on_failure` 四值 × 后继矩阵。
3. 双层重试对齐：确认退避数学调用点唯一在 Action 层（`_process_due_retries`）；Plan 层零退避。
4. 单测：判定树逐分支；矩阵逐行。

## Step 8 — 挂载 `life_loop` 与回归

1. `life_loop._step_goal_advance` 内部改走 `PlanObserver.collect_facts` + `observe`；**签名与九步序列不变**。
2. 计划阶段以子步骤记入 `loop_runs.steps`（`plan_execute` / `plan_observe`），受既有 `budget_state` 约束。
3. `action_engine._process_due_retries` 不新增维护步，Plan 层不新增调度循环。
4. 回归：九步序列形状快照；Flag off 时 `goal_observation` / `goal_execution` 原路径生效，行为与 V2.4.0 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | **搬运等价性** | `PlanScheduler` 公开函数与 `goal_observation` 私有实现对同一 plan（含深层嵌套与 `depends_on` DAG）输出逐条一致 |
| U2 | 拓扑序确定性 | 同输入同输出；叶子优先；结构序（`index` 升序） |
| U3 | `ready_steps` | 前驱全 `done` 且自身 `pending`；前驱未完成时不在集内 |
| U4 | `blocked_reason` 三类 | `off_surface` / `cooldown` / `predecessor_failed` 各一例；有可执行步时为 `None` |
| U5 | `on_failure` 四值 × 后继矩阵 | 逐条与 §4.3.2 完全一致（含 `skip` 只影响直接后继、`continue` 显式放宽 `depends_on`、`replan` 暂停后继、`abort` 全置 `failed`） |
| U6 | 步级 `dedupe_key` | `plan:{goal_id}:{version}:{index}` 唯一且可复现；跨版本号变化可区分 |
| U7 | `to_intent` 不产空 `action_type` | 反查失败即抛实现缺陷异常 |
| U8 | **`attempt_count` 时机** | 只在 Action 终态（`succeeded` / `failed`）递增；`executing` / `planned` 中间态不递增 |
| U9 | `ToolResult → PlanStepOutcome` 归一 | `failure_kind` 取值全部 ⊆ `TOOL_FAILURE_KINDS`（6 值）；`effects` 投影含 `kind` / `ref` / `reversible` |
| U10 | 白名单裁剪 | `observations` 只保留 `observation_keys` 声明的键；未声明键不可见 |
| U11 | **`evaluate` 不可判定语义** | 未声明判据 / 无对应事实 → `None`（**绝不默认 `True`**） |
| U12 | `fact_source="tool"` 两类判定 | `action_succeeded`（读 `steps[].status`）与 `field_equals`（读 `observations[key]`）各一例 |
| U13 | 四源事实包 | 四源各有「可用 / 不可用」两态；`tool` 源键受白名单约束 |
| U14 | 四个重规划理由码 | 各一例；`should_replan` 返回理由码或 `None` |
| U15 | **保留步不重做** | 重规划后已完成步骤的 `tool_id` / `criteria` / `index` 不变，`kept_steps` 正确 |
| U16 | 修订预算终止 | 达上限 → 计划 `rejected` + 目标 `failed("plan_exhausted")`，且不再产生新版本 |
| U17 | 观测 `error` 隔离 | 只 log，计划状态不变（`decision="hold"`） |
| U18 | `policy_for` | `retry_policy` 三值映射正确；`RetryPolicy` 不含退避字段 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **执行唯一入口** | 步骤执行只经 `action_engine.run_action_planning`；静态断言 `services/planning/` 零直调 `ToolExecutor.run` / `Capability.execute`（G-EXEC） |
| I2 | 六闸门与五段短路经过性 | 一次步骤执行完整经过六闸门与五段（每段可观测） |
| I3 | `pending_confirmation` 三条路径 | 用户批准续跑（参数与幂等键复用原调用）/ 用户否定转 `failed` / TTL 过期转 `failed` |
| I4 | **零退避断言** | Plan 层无退避实现、无等待（静态 + 运行时）；退避数学调用点唯一在 Action 层 |
| I5 | **单一写面断言** | 终态结算必经 `goal_repository.set_status` 且调 `goal_arbitration.record_goal_lifecycle`；`decision_records.kind` 仍五值 |
| I6 | 计划推进审计投影 | 可从 `decision_records`（`kind='goal_lifecycle'`）正确投影 `PlanAdvance` |
| I7 | **保留步不重做断言（G-RETRY）** | 重规划后 `deferred_world_op` 计数**不增加**（用 `action_repository` 落库计数验证，确认未产生重复世界副作用） |
| I8 | `goal_plans.sub_goals` 落库形状 | 快照测试通过；零新表、零新列 |
| I9 | 计划阶段子步骤记账 | `loop_runs.steps` 中 `plan_execute` / `plan_observe` 记账正确且受既有 `budget_state` 约束 |
| I10 | `life_loop` 九步序列不变 | 形状快照对照零差异 |
| I11 | 额度与冷却未放宽 | `action_max_active_per_user` / 冷却窗口生效；额度耗尽时步骤不执行、不产生 `ActionRecord` |
| I12 | `services/planning/` 零 `world_repository` 导入 | 静态断言（G-WORLD 前置） |
| I13 | **Flag off 逐字节一致** | `CRITERION_FACT_SOURCES` 仍三值、`fact_source="tool"` 判据一律 `None`；`goal_observation` / `goal_execution` 原路径生效 |
| I14 | 零迁移断言 | 迁移链头 `0046`；`ck_decision_records_kind` 五值未变 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」全链（架构 §6.2 同构）** | 目标成熟 → `PlanContext` 装配 → 拆解（N Task + 工具绑定）→ 逐 tick 单步执行（受 `v25_plan_step_cooldown_minutes` 节流）→ 观测推进 → 终态结算 | 每步：`to_intent` → 六闸门 → `ToolExecutor` 五段 → `ToolResult` → `reconcile` → `update_plan_progress`；全步 `done` 后目标 `completed` |
| S2 | 单步失败但未达上限 | 步骤执行失败（`transient`）| Action 层退避重试；`attempt_count` 不递增（未达终态）；达终态后 Plan 层裁决 |
| S3 | 达 Plan 层尝试上限 + `on_failure=replan` | 连续失败达 `v25_plan_step_max_attempts` | `should_replan` 返回 `step_attempt_exhausted`；新版本产生；**已完成步骤不重做** |
| S4 | 达修订预算 | 连续修订达 `v25_plan_revision_budget` | 计划 `rejected`；目标 `failed("plan_exhausted")`；不再产生新版本 |
| S5 | `permission_denied` | 步骤被授权拒绝 | `step.failed`（`on_failure` 生效）；**不重试**；不自动绕过 |
| S6 | `pending_confirmation` 三条路径 | 批准 / 否定 / TTL 过期 | 批准续跑（幂等键复用）；两条失败路径 → `step.failed` |
| S7 | `capability_unavailable` 持续 | 工具连续 N tick `off_surface` | `blocked_reason="off_surface"` → `hold` → 触发 `tool_persistently_unavailable` 重规划 |
| S8 | 判据不可判定 | `criteria_result is None` 连续 N 轮 | 触发 `criteria_undecidable` 重规划 |
| S9 | 观测自身异常 | `collect_facts` 抛异常 | 只 log；计划状态不变；下一 tick 继续 |
| S10 | 世界副作用不重复（G-RETRY 端到端） | 含 `builtin.reminder.create` 的步骤 → 重规划 | `deferred_world_op` 计数不增加（无第二条提醒） |
| S11 | Flag off | 总闸 off → 推进目标 | 走 `goal_observation` 原路径；行为与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- **搬运等价性测试**：`PlanScheduler` 公开函数与 `goal_observation` 私有实现对同一 plan（含深层嵌套与 `depends_on` DAG 用例）输出逐条一致。
- 拓扑序与 `ready_steps` 确定性（同输入同输出，可复现锚点）；`blocked_reason` 覆盖 `off_surface` / 冷却中 / 前置失败三类。
- `on_failure` 四值 × 后继状态矩阵逐条测试，与 §4.3.2 矩阵完全一致（含 `skip` 只影响直接后继、`continue` 显式放宽 `depends_on`、`replan` 暂停后继、`abort` 全置 `failed`）。
- 步级 `dedupe_key = plan:{goal_id}:{version}:{index}` 唯一且可复现；`to_intent` 不产出空 `action_type`。
- **执行唯一入口断言**：步骤执行只经 `action_engine.run_action_planning`；静态断言 `services/planning/` 零直调 `ToolExecutor.run` / `Capability.execute`（G-EXEC）。
- `pending_confirmation` 步骤经既有 `run_confirmation_round` 三条路径端到端通过：用户批准续跑（参数与幂等键复用原调用）/ 用户否定转 `failed` / TTL 过期转 `failed`。
- **`attempt_count` 时机断言**：只在 Action 终态（`succeeded` / `failed`）递增；`executing` / `planned` 中间态不递增（用例）。
- **零退避断言**：Plan 层无退避实现、无等待（静态与运行时断言），退避数学调用点唯一在 Action 层。
- `fact_source="tool"` 的 `action_succeeded` 与 `field_equals` 各有端到端用例；不可判定一律返回 `None`（绝不默认 `True` 断言）。
- **单一写面断言**：终态结算必经 `goal_repository.set_status` 且调 `goal_arbitration.record_goal_lifecycle`；`decision_records.kind` 仍为五值；计划推进审计可从 `decision_records` 正确投影。
- **保留步不重做断言（G-RETRY）**：重规划后已完成步骤的 `tool_id` / `criteria` / `index` 不变，且 `deferred_world_op` 计数不增加（使用 `action_repository` 落库计数验证，确认未产生重复世界副作用）。
- 修订预算达上限的终止路径可判定：计划置 `rejected` + 目标 `failed("plan_exhausted")`，且不再产生新版本。
- `goal_plans.sub_goals` 落库形状快照测试通过；零新表、零新列。
- 观测故障隔离：`error` 只 log、计划状态不变（用例）。
- Flag off 时 `CRITERION_FACT_SOURCES` 仍为三值、`fact_source="tool"` 判据一律 `None`，`goal_observation` / `goal_execution` 原路径生效，行为与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- `life_loop._step_goal_advance` 签名与九步序列不变；`autonomous_tick` stage 序列不变（形状快照对照）。
- 计划阶段子步骤（`plan_execute` / `plan_observe`）正确记入 `loop_runs.steps`，受既有 `budget_state` 约束。
- Action 层既有维护步（`action_engine._process_due_retries`）承载全部退避；Plan 层不新增维护步、不新增调度循环。
- `action_engine.run_action_planning` 的额度与冷却（`action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes`）未被放宽（用例）。
- 既有 `goal_observation` / `goal_execution` / `action_engine` / `action/planner` 测试零失败。
- V2.4.0 工具侧既有测试零失败（确认执行链未被绕过）。
- `services/planning/` 零 `world_repository` 导入；零 `character_state` / `personality_state` / `relationship_*` 写入（静态断言）。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`。
- **先搬后改可举证**：搬运等价性测试先于执行桥接与观测推进定稿（本任务 Step 1 的出口条件），避免行为变更污染后续观测语义。
- **纯函数纪律**：`PlanScheduler` / `PlanRevisionPolicy` / `PlanValidator`（PLAN-004）为零 IO 纯函数；`PlanObserver` 的 `facts` 由调用方注入。
- **零新建基础设施**：不新建执行编排器、不新建调度循环 / Worker、不新建审计表、不扩 `ActionStatus` / `GATE_REASONS` / `DecisionKind` 值集。
- **本任务最容易写错的点已单列验收**：重规划保留已完成步骤（G-RETRY）与 `attempt_count` 递增时机（D7/U8）各有专项目例。
- **文档一致**：本文件与 architecture §3.6 ~ §3.9、§5.3、§5.5、§5.6、§6.4 ~ §6.6、§7.8、§8.4、§8.5 及 tasks.md PLAN-005 Acceptance Criteria 逐条对应，无自相矛盾。
