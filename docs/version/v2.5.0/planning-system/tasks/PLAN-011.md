# PLAN-011 Task Detail — Planning API / Interface

> 上游：[../architecture.md](../architecture.md) §8.1 ~ §8.7（API Interface）、§4.6（`PlanAdvance`）、§4.9（零迁移裁决）、§7.8（Life Loop）、§7.9（逐系统契约）、§9.7 Q10；[../tasks.md](../tasks.md) PLAN-011
> 状态：DONE（已实现，commit 248836f，2026-09-16）
> 范围红线：**冻结内部接口契约，不新建仓储模块**；`goal_repository` 既有九函数零改动、只加三个只读扩展；审计**复用既有 `kind='goal_lifecycle'`**（不新增 `DecisionKind`）；6 个调试端点全部受总闸 + 调试子闸门控；可观测面全部投影自四张既有表。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-011 |
| **Task Name** | Planning API / Interface |
| **Priority** | P1 |
| **Dependencies** | PLAN-005, PLAN-006 |
| **Phase** | Phase 4 接口与验收 |
| **建议提交** | `feat: V2.5.0 计划内部接口冻结、只读扩展与调试面` |

## 1.1 Goal

冻结并验证 Planning 的**内部接口契约**，交付 `goal_repository` 只读扩展与计划可观测面：

1. **内部接口契约冻结与一致性验证**：六个模块（`PlanningEngine` / `PlanContextAssembler`+`PlanContextProbe` / `PlanRepository` / `PlanScheduler`+`PlanExecutorBridge` / `PlanObserver`+`PlanRevisionPolicy` / `PlanValidator`+`PlanningRevisionListener`）的公开签名与 architecture §8.1 ~ §8.6 逐条一致。
2. **`goal_repository` 只读扩展三项**：`list_plans_by_status` / `count_plan_versions` / `list_terminal_plans_since`（后者供 PLAN-010 证据窗投影）。
3. **计划审计与运行态投影**：`PlanAdvance` → `decision_records`（复用 `kind='goal_lifecycle'`）；计划阶段子步骤 → `loop_runs.steps`。
4. **管理面调试端点 6 个**（受总闸 + 调试子闸门控）。

## 1.2 Scope

**包含**

- 六个模块的公开接口契约对照（签名漂移即失败）。
- `goal_repository` 三项只读扩展（**零写库**）。
- `PlanAdvance` 落 `decision_records` 的投影验证（`kind='goal_lifecycle'` + 差异化 `decision`）。
- 修订链从 `goal_plans` + `decision_records` 重建：`from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps` 逐条可读。
- `loop_runs.steps` 计划子步骤记账（`plan_assemble` / `plan_execute` / `plan_observe`）。
- 6 个调试端点（`app/api/v1/debug.py` 的 `debug_router` 风格）。
- 三条纪律的静态断言：只读 / 零 IO / 纯函数。

**不包含（Non-Scope）**

- 六个模块的**实现**（分别由 PLAN-003 ~ PLAN-010 交付；本任务只冻结签名与做对照）。
- 新建仓储模块（**永不**；扩展既有 `goal_repository`）。
- 新增 `DecisionKind` / `ActionStatus` / `GATE_REASONS` 值集（**永不**）。
- 新建可观测表（**永不**；全部投影）。
- 前端调试控制台（`apps/frontend/`，Q10 记录，本版本不实现）。
- `regression-checklist.md` 与版本级验收（PLAN-012）。

## 1.3 本任务解决什么问题

architecture §1.3 断层 **B8（无计划可观测面）** 的关闭：

| 断层 | 现状 | 本任务的关闭方式 |
|---|---|---|
| B8 | `goal_plans` 只有当前态（`status` / `rejection_reason`），无转移审计投影；`decision_records.kind` 是五值 CHECK | ① `PlanAdvance` 复用既有 `kind='goal_lifecycle'` + 差异化 `decision` 值落 `decision_records`；② 修订链从两张既有表重建；③ 6 个调试端点暴露计划 / 步骤 / 上下文 / 修订链 / 待推进 |

**本任务的双重性质**：它既是**契约冻结**（防签名漂移），又是**可观测面交付**（让「这个计划为什么走到这一步、每次修订是谁触发的」可回答）。其中「调试端点与前端视图」是 tasks.md §1.1 明确的**可延后子项**（P2 语义）。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Goal System** | `goal_repository` 为唯一仓储面；本任务在其上**只加三个只读函数** |
| **Planning System（PLAN-003 ~ PLAN-010）** | 六个模块的接口为本任务的冻结对象 |
| **可观测基础设施** | `decision_records`（`DecisionKind` 五值）/ `loop_runs.steps` / `api/v1/debug.py` 的 `debug_router` |
| **Tool System V2.4.0** | `debug.py` 的 `/debug/tools*` 面板为调试端点的**同构样板** |
| **World Simulation V2.3.0** | WS-018 world debug 面板为同构样板 |
| **Memory 2.0 / Reflection** | **不涉及**（只读其既有表用于投影） |
| **Autonomy 2.0** | **不涉及**（属 PLAN-007） |

**关键事实（已核对真实源码）**

- `app/models/observability.py::DecisionKind`（`StrEnum`）五值：`PROACTIVE_AUTONOMY="proactive_autonomy"` / `TURN_GOAL="turn_goal"` / `TURN_INTENTION="turn_intention"` / `TURN_BEHAVIOR="turn_behavior"` / `GOAL_LIFECYCLE="goal_lifecycle"`。
- `app/core/db.py::DecisionRecordRow`：`decision_records` 表有 `input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)`；`ck_decision_records_kind` CHECK 五值；`idx_decision_records_user_time`（`user_id` / `kind` / `created_at`）。
- `app/repositories/goal_repository.py` 计划面九函数（**零改动**）：`create_plan` / `get_plan` / `list_plans` / `get_latest_plan` / `count_plans` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress` / `list_active_plans`。
- `app/repositories/loop_run_repository.py`：`create_run` / `mark_step(run_id, step, now=None)` / `finish_run` / `get` / `list_recent`。
- `app/api/v1/debug.py`：模块级 `debug_router`（既有 `/debug/tools`、`/debug/tools/surface`、`/debug/tools/executions`、`/debug/tools/permissions`、`/debug/tools/confirmations`、`/debug/tools/manifests`、`/debug/tools/external`、`/debug/tools/user-defined`、`/debug/tools/{tool_id}`、`/debug/decisions`、`/debug/metrics`、`/debug/traces*`、`/debug/llm-calls*`、`/debug/prompts*`、`/debug/memory/{memory_id}/attribution`、`/debug/insights/{insight_id}/attribution` 等），并有 `ToolsOut` / `ToolSurfaceOut` / `ToolExecutionsOut` / `ToolPermissionsOut` 等 Pydantic 输出模型。
- 迁移链头 `0046_tool_insight_types.py`。

## 2.2 为什么需要本任务

architecture §8 明确：**「以下为接口设计，不含实现」**。分散在七个任务里交付的六个模块，若无一次集中的契约冻结，很容易出现：

- 签名漂移（`blocked_reason` 的 `ctx` 参数从必填变可选、`settle` 的返回值语义变化）——下游任务按错误假设实现；
- 审计面走偏（为计划推进新增 `DecisionKind` 值，触发迁移）；
- 可观测面走偏（为计划新建一张投影表，破坏零迁移）。

本任务就是这三件事的集中守卫。tasks.md §6 追溯矩阵也明确：PLAN-011 同时承载「内部接口契约冻结 + `goal_repository` 只读扩展 + 审计投影」，因此整体定级 P1（而非 architecture §9.2 的 P2），只有**调试端点子项**保留 P2 语义。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 六个模块公开接口的签名冻结与一致性验证 | 契约对照 + 用例 |
| R2 | `goal_repository` 三项只读扩展 | 函数 + 用例 |
| R3 | `PlanAdvance` → `decision_records` 投影（复用既有 kind） | 契约 + 用例 |
| R4 | 修订链从两张既有表重建 | 投影契约 + 用例 |
| R5 | `loop_runs.steps` 计划子步骤记账 | 契约 + 用例 |
| R6 | 6 个调试端点（受总闸 + 调试子闸） | 端点 + 用例 |
| R7 | 三条纪律静态断言（只读 / 零 IO / 纯函数） | 静态测试 |
| R8 | 零新建表断言（四张既有表投影） | 断言 |
| R9 | Q10 记录（前端控制台是否纳入） | 文档留痕 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 六个模块的实现 | PLAN-003 ~ PLAN-010 |
| N2 | 新建仓储模块 | **永不**（扩展既有 `goal_repository`） |
| N3 | 新增 `DecisionKind` 值 | **永不**（需改 CHECK = 需迁移） |
| N4 | 新建可观测表 | **永不**（全部投影） |
| N5 | `daily_plans` 与 `goal_plans` 的语义收敛（Q7） | 独立评估，不进本版本 |
| N6 | 前端调试控制台（`apps/frontend/`） | Q10 记录，本版本不实现 |
| N7 | `regression-checklist.md` 与版本验收 | PLAN-012 |
| N8 | 计划引擎 / 调度 / 执行 / 观测 / 修订 / 集成的逻辑 | PLAN-003 ~ PLAN-010 |

## 3.3 职责边界一句话

> **本任务不改任何计划逻辑，只做三件事：把六个模块的签名钉死、在既有仓储上加三个只读口、把计划的状态与推进投影到四张既有表上。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/*.py` | 由 PLAN-003 ~ PLAN-010 建立 | **签名冻结**（本任务做契约对照，不实现） | — |
| `app/repositories/goal_repository.py` | 既有 | **扩展三个只读函数**（九函数零改动） | 只读 |
| `app/api/v1/debug.py` | 既有 | **扩展 6 个计划端点 + 输出模型** | → `goal_repository` / `action_repository` / `decision_records` / `PlanContextProbe` |

**分层纪律（静态断言强制）**
- 三个新增只读函数**零写库**（无 `add` / `commit` / `update` / `delete`）。
- `PlanScheduler` / `PlanValidator` / `PlanRevisionPolicy` 为纯函数（零 IO）。
- `PlanObserver` 的 `facts` 由调用方注入。
- 调试端点全部受 `v25_planning_enabled` + `v25_plan_debug_enabled` + 调试总闸门控。

### 4.1.2 Component 划分

```text
① 契约冻结（对照 architecture §8.1 ~ §8.6）
├── PlanningEngine              plan / revise / enqueue / run_jobs / register_runtime
├── PlanContextAssembler        assemble
│   PlanContextProbe            world_available / surface_size / degraded_sources
├── PlanRepository              既有 9 函数 + 新增 3 只读函数
├── PlanScheduler               order / ready_steps / current_step / all_done
│                               / has_executable / blocked_reason
│   PlanExecutorBridge          to_intent / execute_step / reconcile
├── PlanObserver                collect_facts / observe / evaluate / settle
│   PlanRevisionPolicy          should_replan / policy_for / explain
└── PlanValidator               validate_shape / validate_binding / validate_budget
    PlanningRevisionListener    on_insight_created / enqueue_replan

② goal_repository 只读扩展（3 项）
├── list_plans_by_status(user_id, statuses) -> list[GoalPlanRecord]
├── count_plan_versions(goal_id) -> int
└── list_terminal_plans_since(user_id, since) -> list[GoalPlanRecord]   # 供 PLAN-010 证据窗投影

③ 审计与运行态投影
├── PlanAdvance → decision_records（kind="goal_lifecycle" + decision + input_snapshot）
├── 修订链      → goal_plans（新版本行）+ decision_records（plan_revised）
└── 运行态序列  → loop_runs.steps（plan_assemble / plan_execute / plan_observe）

④ 管理面（6 个端点，debug_router）
├── GET /debug/plans?user_id=&status=
├── GET /debug/plans/{plan_id}
├── GET /debug/plans/{plan_id}/steps
├── GET /debug/plans/context?user_id=&goal_id=
├── GET /debug/plans/revisions?goal_id=
└── GET /debug/plans/pending?user_id=
```

### 4.1.3 数据流：可观测面的投影来源

```text
                        ┌──────────────────────┐
  goal_plans ──────────►│  计划本体 / 状态      │──► /debug/plans
                        │  / 步骤 / 修订链      │──► /debug/plans/{id}
                        └──────────────────────┘──► /debug/plans/{id}/steps
                        ┌──────────────────────┐──► /debug/plans/revisions
  decision_records ────►│  推进审计 / 修订审计  │
  (kind=goal_lifecycle) │  / 规划轮次审计       │
                        └──────────────────────┘
                        ┌──────────────────────┐──► /debug/plans/pending
  PlanContextProbe ────►│  装配结果 / degraded  │──► /debug/plans/context
                        └──────────────────────┘
                        ┌──────────────────────┐
  action_records ──────►│  步骤执行台账         │──► （并入 steps 视图）
  (steps[].result)      └──────────────────────┘
                        ┌──────────────────────┐
  loop_runs.steps ─────►│  运行态子步骤序列     │──► /debug/traces*（既有）
                        └──────────────────────┘

★ 全部投影自四张既有表：goal_plans / action_records / decision_records / loop_runs
```

## 4.2 Core Model

本任务**不新增持久模型**。下表为接口契约与投影契约。

### 4.2.1 六个模块的公开接口（冻结，对照 architecture §8.1 ~ §8.6）

| 模块 | 公开方法 | 纪律 |
|---|---|---|
| `PlanningEngine` | `plan(goal, ctx, *, trigger) -> PlanOutcome` / `revise(plan, ctx, *, reason) -> PlanOutcome` / `enqueue(user_id, goal_id, trigger, *, ctx) -> bool` / `run_jobs() -> int` / `register_runtime() -> None` | `plan` / `revise` 不直接落库；`enqueue` 幂等；拒绝不抛异常 |
| `PlanContextAssembler` | `assemble(goal, *, run, now) -> PlanContext \| PlanUnavailable` | 只读、零写库；硬依赖缺失返回 `PlanUnavailable` |
| `PlanContextProbe` | `world_available(user_id) -> bool` / `surface_size(user_id, *, run_kind) -> int` / `degraded_sources(user_id) -> list[str]` | 只读探测，零 IO（除既定读） |
| `PlanRepository` | 既有 9 + 新增 3 | 新增 3 只读、零写库 |
| `PlanScheduler` | `order(plan) -> list[int]` / `ready_steps(plan) -> list[PlanStepSpec]` / `current_step(plan) -> PlanStepSpec \| None` / `all_done(plan) -> bool` / `has_executable(plan) -> bool` / `blocked_reason(plan, ctx) -> str \| None` | 纯函数、零 IO、零 LLM、同输入同输出 |
| `PlanExecutorBridge` | `to_intent(goal, plan, step, ctx) -> ActionIntent` / `execute_step(goal, plan, step, ctx) -> PlanStepOutcome` / `reconcile(outcome, step) -> PlanStepSpec` | `execute_step` 唯一入口 `action_engine.run_action_planning`；`reconcile` 只写内存副本 |
| `PlanObserver` | `collect_facts(user_id, ctx) -> dict` / `observe(goal, plan, facts, *, now) -> PlanAdvance` / `evaluate(criteria, facts) -> bool \| None` / `settle(goal, plan, advance) -> PlanOutcome` | `facts` 调用方注入；`evaluate` 不可判定返回 `None`；`settle` 唯一改 `GoalStatus` 入口 |
| `PlanRevisionPolicy` | `should_replan(outcome, plan, ctx) -> str \| None` / `policy_for(step) -> RetryPolicy` / `explain(plan, reason) -> dict` | 纯函数；不执行动作，只返回理由码 |
| `PlanValidator` | `validate_shape(steps, *, max_depth) -> list[str]` / `validate_binding(steps, surface) -> list[str]` / `validate_budget(steps, plan_versions, budget) -> list[str]` | 纯函数、零 IO；空列表 = 通过 |
| `PlanningRevisionListener` | `on_insight_created(user_id, created) -> None` / `enqueue_replan(goal_id, insight_id) -> bool` | 唯一动作 = 幂等入队；幂等键 `plan_replan:{goal_id}:{insight_id}` |

**签名漂移的判定**：参数名、参数顺序、是否必填、返回类型注解——任一变化即用例失败。

### 4.2.2 `goal_repository` 只读扩展三项

| 函数 | 签名 | 用途 | 纪律 |
|---|---|---|---|
| `list_plans_by_status` | `(user_id: str, statuses: tuple[str, ...]) -> list[GoalPlanRecord]` | 按状态批量取计划（调试端点 / 运维） | 只读 |
| `count_plan_versions` | `(goal_id: str) -> int` | 版本链长度（修订预算判定与调试展示） | 只读 |
| `list_terminal_plans_since` | `(user_id: str, since: datetime) -> list[GoalPlanRecord]` | **供 PLAN-010 证据窗投影**（计划成功率窗口） | 只读 |

**既有九函数零改动**：`create_plan` / `get_plan` / `list_plans` / `get_latest_plan` / `count_plans` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress` / `list_active_plans`（签名与行为差异对照为空）。

### 4.2.3 `PlanAdvance` 落 `decision_records` 的投影契约

| `decision_records` 列 | 承载 |
|---|---|
| `kind` | **`"goal_lifecycle"`**（既有 `DecisionKind.GOAL_LIFECYCLE`，CHECK 五值之一） |
| `decision` | `PlanAdvance.decision` 取值（`advanced` / `completed` / `failed` / `replanning` / `skipped` / `hold`） |
| `input_snapshot` | `PlanAdvance` 整体（`goal_id` / `plan_id` / `plan_version` / `reason` / `step_index` / `facts_digest` / `at`） |
| 其他既有列 | 按既有决策记录写入惯例（`user_id` / `created_at` 等） |

**不新增 kind 的理由**：新增 kind 需改 `ck_decision_records_kind` CHECK = 需迁移 → 违反 architecture §2.3 红线 1。V2.4.0 `post_process._persist_tool_decision` 已建立「复用 `TURN_INTENTION` + `decision="tool_surface"`」的先例。

### 4.2.4 修订链与规划轮次审计的投影契约

| 数据 | 落点 | 承载 |
|---|---|---|
| 修订链（版本） | `goal_plans`（新版本行 + 旧版 `superseded`） | `version` / `status` / 既有列 |
| 修订审计 | `decision_records`（`kind='goal_lifecycle'`） | `decision="plan_revised"`，`input_snapshot={from_version, to_version, reason, trigger_source, evidence_refs, kept_steps}` |
| 规划轮次审计 | `decision_records`（`kind='goal_lifecycle'`） | `decision` 为规划轮次名；`input_snapshot` 承载 `trigger` / `context_digest` / `revision_of` / `evidence_refs`（PLAN-002 §4.4.1 落点裁决） |
| 计划状态变更 | `goal_plans.status` | 既有列（`set_plan_status`） |

**修订链可重建性**：`from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps` 六项**逐条可读**（§9.2 I4）。

### 4.2.5 `loop_runs.steps` 计划子步骤记账

| 子步骤名 | 时机 | 承载 |
|---|---|---|
| `plan_assemble` | 上下文装配（PLAN-003） | `loop_runs.steps`（既有 `mark_step`） |
| `plan_execute` | 步骤执行桥（PLAN-005） | 同上 |
| `plan_observe` | 观测推进（PLAN-005） | 同上 |

**纪律**：受既有 `budget_state` 约束；`life_loop` 九步阶段序列**不变**（子步骤记在阶段内部）。

### 4.2.6 6 个调试端点

| # | 端点 | 返回 | 门控 |
|---|---|---|---|
| 1 | `GET /debug/plans?user_id=&status=` | 计划清单（含版本链与状态） | 总闸 + 调试子闸 + 调试总闸 |
| 2 | `GET /debug/plans/{plan_id}` | 单计划详情（步骤 / 绑定 / 判据 / 推进历史） | 同上 |
| 3 | `GET /debug/plans/{plan_id}/steps` | 步骤视图（含 `tool_id` 绑定与 `blocked_reason`） | 同上 |
| 4 | `GET /debug/plans/context?user_id=&goal_id=` | `PlanContext` 装配结果（六源 + `degraded` 清单） | 同上 |
| 5 | `GET /debug/plans/revisions?goal_id=` | 修订链（from/to version + reason + evidence_refs） | 同上 |
| 6 | `GET /debug/plans/pending?user_id=` | 待推进步骤（含 `off_surface` / 冷却中原因） | 同上 |

**门控纪律**：Flag off 时端点**不可见**（与 WS-018 world debug 面板、TOOL-012 tools 面板同款）。

## 4.3 State Machine

本任务**不新增状态机**。下为投影视图所反映的既有状态。

### 4.3.1 计划可观测视图的状态来源

| 视图 | 状态来源 | 既有 / 新投影 |
|---|---|---|
| 计划清单 | `goal_plans.status`（五态） | 既有列 |
| 计划详情 | `goal_plans` + `decision_records`（推进历史） | 新投影（复用既有 kind） |
| 步骤视图 | `goal_plans.sub_goals[].status`（四态）+ `blocked_reason` | 既有 JSON + `PlanScheduler` 纯函数 |
| 装配结果 | `PlanContext`（内存）+ `degraded` | 新投影（装配时快照） |
| 修订链 | `goal_plans`（版本行）+ `decision_records`（`plan_revised`） | 新投影（复用既有 kind） |
| 待推进步骤 | `PlanScheduler.current_step` / `ready_steps` + `blocked_reason` | 纯函数实时计算 |

### 4.3.2 投影的产生时机

```text
计划推进（PLAN-005）
    │
    ├─ settle 产生 PlanAdvance
    │     └─► decision_records（kind="goal_lifecycle"，decision=advance.decision）
    ├─ 修订产生新版本
    │     └─► goal_plans（version+1）+ decision_records（decision="plan_revised"）
    └─ 装配产生 PlanContext
          └─► loop_runs.steps（plan_assemble 子步骤，含 degraded）

查询时（调试端点）
    └─► 只读投影：goal_plans + action_records + decision_records + loop_runs
        ★ 无新表、无物化视图、无缓存表
```

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `plan_facts` | PLAN-007 | **不涉及** |
| 候选面 | PLAN-007 | **不涉及** |
| 调试端点的自治投影 | 既有 `/debug/decisions` | **零改动**（本任务只加计划端点） |

**为什么不涉及**：本任务是接口与可观测面交付，不改自治接线；`PlanContextProbe.surface_size` 虽被 PLAN-007 用于事实收集，但其签名冻结在本任务，属**只读探测**面。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `/debug/tools*` 面板 | 调试端点的**同构样板**（`debug_router` + Pydantic 输出模型） | 参照风格，不修改工具端点 |
| 工具面 / 选择器 / 执行器 | 既有 | **不涉及**（属 PLAN-006） |
| 步骤视图的 `tool_id` 绑定展示 | 读 `goal_plans.sub_goals[].tool_id` | **新投影**（只读） |

**为什么只参照风格**：调试端点须与既有面板同构（门控方式、输出模型命名、错误处理），否则调试体验分裂。本任务**不新增权限等级**、不新增工具治理面。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| WS-018 world debug 面板 | 同构样板 | 参照风格 |
| 世界事实在 `PlanContext` 的投影 | `/debug/plans/context` 展示六源之一 | **新投影**（只读快照） |
| 世界写入 | PLAN-008 | **不涉及** |

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 记忆条数在 `PlanContext` 的投影 | `/debug/plans/context` 展示计数与摘要 | **新投影**（只读） |
| 计划终态记忆 | PLAN-009 | **不涉及** |

**纪律**：调试投影**不回显记忆正文**（只显计数与 id），避免调试面成为记忆内容泄漏渠道（对齐既有 `/debug/memory/{memory_id}/attribution` 的脱敏惯例）。

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `list_terminal_plans_since` 供 PLAN-010 证据窗投影 | **本任务交付该只读函数** | 新增只读口 |
| `EVIDENCE_CHANNEL_PLAN` | PLAN-010 | **不涉及**（本任务不改反思） |
| `/debug/insights/{insight_id}/attribution` | 既有端点 | **零改动** |

**接线关系**：本任务为 PLAN-010 提供「终态计划批量只读查询」这一基础设施；两者在 tasks.md §1.1 中互为独立任务（PLAN-010 依赖 PLAN-005，PLAN-011 依赖 PLAN-005 / PLAN-006），消费方向为 PLAN-010 → 本任务交付的只读函数。

## 5.6 与 Life Loop / Runtime

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `loop_runs.steps` | 计划子步骤承载位 | **投影契约**（不改 `life_loop` 九步序列） |
| `life_loop_budget` | 既有 | **不涉及** |
| `/debug/traces*` | 既有端点可读 `loop_runs` | **零改动**（计划子步骤自动可见） |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 计划生成 / 拆解 / 调度 / 执行 / 观测 / 修订的逻辑 | 不涉及（只冻结签名） | PLAN-003 ~ PLAN-005 |
| 工具治理逻辑 | 不涉及 | PLAN-006 |
| 世界写入与广播 | 不涉及 | PLAN-008 |
| 计划终态记忆 | 不涉及 | PLAN-009 |
| 反思证据窗与监听器 | 不涉及（只提供只读函数） | PLAN-010 |
| 自治 `plan_facts` | 不涉及 | PLAN-007 |
| 前端调试控制台 | 不涉及（Q10 记录） | 推后续版本 |
| 版本级验收与回归清单 | 不涉及 | PLAN-012 |

---

# 6. API / Interface Design

## 6.1 `PlanRepository` 只读扩展接口

```text
interface PlanRepository:                       # 全部为既有 goal_repository 内的扩展，不新建仓储模块
    # 既有（零改动，9 个）
    create_plan(record: GoalPlanRecord) -> GoalPlanRecord
    get_plan(plan_id: str) -> GoalPlanRecord | None
    get_latest_plan(goal_id: str) -> GoalPlanRecord | None
    list_plans(goal_id: str) -> list[GoalPlanRecord]
    count_plans(goal_id: str) -> int
    set_plan_status(plan_id: str, status: str) -> GoalPlanRecord | None
    set_plan_rejection(plan_id: str, reason: str) -> GoalPlanRecord | None
    update_plan_progress(plan_id: str, sub_goals: list[PlanStepSpec]) -> GoalPlanRecord | None
    list_active_plans(user_id: str) -> list[tuple[GoalRecord, GoalPlanRecord]]

    # 本版本新增（只读扩展，3 个）
    list_plans_by_status(user_id: str, statuses: tuple[str, ...]) -> list[GoalPlanRecord]
    count_plan_versions(goal_id: str) -> int
    list_terminal_plans_since(user_id: str, since: datetime) -> list[GoalPlanRecord]
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 既有九函数签名与行为零改动 | 签名 + 行为差异对照为空 |
| D2 | 三个新函数**零写库** | 打桩断言（零 `add` / `commit` / `update` / `delete`） |
| D3 | `statuses` 参数取值 ⊆ `PLAN_STATUS_VALUES`（五值） | 用例断言 |
| D4 | `list_terminal_plans_since` 只返回终态（`completed` / `rejected` / `superseded`） | 用例断言 |

## 6.2 审计投影接口（写入侧，PLAN-005 调用）

```text
record_plan_advance(advance: PlanAdvance) -> None
    # 写 decision_records：
    #   kind = DecisionKind.GOAL_LIFECYCLE（"goal_lifecycle"，既有）
    #   decision = advance.decision
    #   input_snapshot = advance 整体
    # ★ 不新增 DecisionKind 值

record_plan_revision(revision: PlanRevision) -> None
    # 写 decision_records：
    #   kind = "goal_lifecycle"
    #   decision = "plan_revised"
    #   input_snapshot = {from_version, to_version, reason, trigger_source, evidence_refs, kept_steps}
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D5 | `kind` 恒为既有 `goal_lifecycle` | 值集快照（`ck_decision_records_kind` 仍五值） |
| D6 | `decision` 承载计划迁移名（差异化值） | 用例（每值可读） |
| D7 | `input_snapshot` 承载完整 `PlanAdvance` / `PlanRevision` | 投影重建用例 |

## 6.3 调试端点接口

```text
# app/api/v1/debug.py（module-level debug_router，风格对齐既有 /debug/tools*）
GET /debug/plans?user_id=&status=                   -> PlansOut
GET /debug/plans/{plan_id}                          -> PlanDetailOut
GET /debug/plans/{plan_id}/steps                    -> PlanStepsOut
GET /debug/plans/context?user_id=&goal_id=          -> PlanContextOut
GET /debug/plans/revisions?goal_id=                 -> PlanRevisionsOut
GET /debug/plans/pending?user_id=                   -> PlanPendingOut
```

**输出模型字段契约**

| 模型 | 关键字段 |
|---|---|
| `PlansOut` | `plans: list[{plan_id, goal_id, version, status, step_count, updated_at}]` |
| `PlanDetailOut` | `plan` + `steps` + `bindings` + `criteria` + `advance_history` |
| `PlanStepsOut` | `steps: list[{index, description, kind, tool_id, binding_reason, status, attempt_count, blocked_reason}]` |
| `PlanContextOut` | `sources: {goal, context, world, memory, reflection, tool_surface}` + `degraded: list[str]` |
| `PlanRevisionsOut` | `revisions: list[{from_version, to_version, reason, trigger_source, evidence_refs, kept_steps, at}]` |
| `PlanPendingOut` | `pending: list[{goal_id, plan_id, step_index, tool_id, reason}]`（`reason` ∈ `off_surface` / `cooldown` / `predecessor_failed`） |

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D8 | 全部端点受 `v25_planning_enabled` + `v25_plan_debug_enabled` + 调试总闸门控 | 用例：任一 off → 端点不可见（404 / 未注册） |
| D9 | 全部端点为**只读**（GET），零写库 | 打桩断言 |
| D10 | 投影只读四张既有表（`goal_plans` / `action_records` / `decision_records` / `loop_runs`） | 静态断言 |
| D11 | 上下文投影含**六源**与 `degraded` 清单 | 用例断言 |
| D12 | 步骤视图含 `tool_id` 绑定与 `blocked_reason` | 用例断言 |
| D13 | 不回显记忆正文（只计数与 id） | 用例断言（脱敏） |

## 6.4 三条纪律的静态断言

```text
# 只读
PlanRepository 新增三函数：零写库调用

# 零 IO
PlanScheduler / PlanValidator / PlanRevisionPolicy：零仓储 / 零 LLM / 零网络

# 纯函数
PlanScheduler 全部函数：同输入同输出（可复现）
PlanValidator 三闸：同输入同输出
PlanRevisionPolicy 三函数：同输入同输出

# 依赖注入
PlanObserver.observe 的 facts 由调用方注入（组件内零 IO）
PlanContextAssembler 除 assemble 外零 IO
```

## 6.5 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| 计划不存在 | 调试端点 | 返回 404（与既有 `/debug/tools/{tool_id}` 风格一致） |
| `plan_id` 非法 / 无权限 | 调试端点 | 返回 404 / 400（与既有端点惯例一致） |
| 投影读取异常 | 只读仓储 | 捕获 → 返回降级结构（含 `degraded` 标记）；log |
| Flag off | 调试端点 | 端点不可见（未注册 / 404） |
| 审计写入异常 | `record_plan_advance` / `record_plan_revision` | 捕获 → log；**不影响计划推进**（与「观测故障只 log」同款纪律） |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 可观测面全部**投影**自 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表 |
| 新列 | 无 | `PlanAdvance` / `PlanRevision` 落 `decision_records.input_snapshot`（既有 JSON）；三重只读扩展不引入新查询列 |
| 新索引 | 无 | 新增查询复用既有 `idx_goal_plans_goal_status` / `idx_decision_records_user_time` |
| 改 CHECK | 无 | `ck_decision_records_kind` 五值不变（复用 `goal_lifecycle`）；`ck_goal_plans_status` 五值不变 |
| 迁移 | 无 | 迁移链保持 **0046** |

**落库归属表（本任务的投影来源）**

| 数据 | 落点 | 表 / 列 | 是否新列 |
|---|---|---|---|
| 计划本体 + 步骤 | `goal_plans` | `sub_goals`（JSON） | ❌ |
| 计划状态 | `goal_plans` | `status`（既有五值 CHECK） | ❌ |
| 计划拒绝理由 | `goal_plans` | `rejection_reason` | ❌ |
| 规划轮次审计（`trigger` / `context_digest` / `revision_of` / `evidence_refs`） | `decision_records` | `input_snapshot`（JSON） | ❌ |
| 计划推进审计 | `decision_records` | `kind='goal_lifecycle'` + `decision` + `input_snapshot` | ❌ |
| 修订链审计 | `decision_records` | 同上（`decision="plan_revised"`） | ❌ |
| 步骤执行台账 | `action_records` | `steps`（JSON） | ❌ |
| 运行态步骤序列 | `loop_runs` | `steps`（JSON） | ❌ |

> **零新建表的结论**：计划可观测面**不为计划系统新建任何表、物化视图或缓存表**。若实现期发现需要建表以支撑调试端点，说明 architecture §4.9 与 §6.7 ⑪ 的裁决被违背，必须回退重审并在验收记录留痕。

---

# 8. Implementation Plan

## Step 1 — `goal_repository` 只读扩展

1. `list_plans_by_status(user_id, statuses)`：按 `user_id` + 状态集合批量查询；`statuses` 取值校验 ⊆ `PLAN_STATUS_VALUES`。
2. `count_plan_versions(goal_id)`：返回该目标的版本数（供修订预算与版本链长度）。
3. `list_terminal_plans_since(user_id, since)`：返回终态计划（供 PLAN-010 证据窗投影）。
4. 三个函数**零写库**（不调用 `add` / `commit` / `update` / `delete`）；复用既有 `_to_plan_record` 转换。
5. 单测：三函数各有正例/边界；零写库打桩断言。

## Step 2 — 审计投影落地与验证

1. `record_plan_advance(advance)`：写 `decision_records`（`kind="goal_lifecycle"`，`decision=advance.decision`，`input_snapshot=advance`）。
2. `record_plan_revision(revision)`：写 `decision_records`（`decision="plan_revised"`，`input_snapshot` 六字段）。
3. 断言 `ck_decision_records_kind` 仍五值（未新增 kind）。
4. 断言可从 `decision_records` 正确投影 `PlanAdvance`。
5. 单测：每类 `decision` 值可读；投影重建正确。

## Step 3 — 修订链重建

1. 从 `goal_plans`（版本行 + 状态）+ `decision_records`（`plan_revised`）重建修订链。
2. 六字段逐条可读：`from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps`。
3. 单测：多版本链（含 `superseded` 与 `rejected` 混合）重建正确。

## Step 4 — `loop_runs.steps` 子步骤记账验证

1. 验证 `plan_assemble` / `plan_execute` / `plan_observe` 三个子步骤被正确记入 `loop_runs.steps`。
2. 断言受既有 `budget_state` 约束（超预算时降级记账）。
3. 断言 `life_loop` 九步阶段序列不变。
4. 单测：子步骤名与内容正确；阶段序列形状快照零差异。

## Step 5 — 6 个调试端点

1. 在 `app/api/v1/debug.py` 的 `debug_router` 上追加 6 个 GET 端点（风格对齐既有 `/debug/tools*`）。
2. 定义 6 个 Pydantic 输出模型（§6.3 字段契约）。
3. 全部受 `v25_planning_enabled` + `v25_plan_debug_enabled` + 调试总闸门控；Flag off 时端点不可见。
4. 端点只读；上下文投影含六源与 `degraded`；步骤视图含 `tool_id` 与 `blocked_reason`；记忆只计数与 id（脱敏）。
5. 单测：门控（三种 off 组合）；六端点各一正例；脱敏断言。

## Step 6 — 契约对照与静态断言

1. 对六个模块生成公开签名快照，与 architecture §8.1 ~ §8.6 逐条对照，差异必须为空。
2. 静态断言：`PlanScheduler` / `PlanValidator` / `PlanRevisionPolicy` 零 IO；`PlanObserver.observe` 的 `facts` 为注入参数；`PlanContextAssembler` 除 `assemble` 外零 IO。
3. 静态断言：调试端点零写库；投影只读四张既有表。
4. 单测：签名漂移即失败；三条纪律各一断言。

## Step 7 — Q10 记录与回归

1. 记录 Q10：计划可观测面是否纳入 `apps/frontend/` 调试控制台——**本版本不实现**，仅设计后端调试端点；是否纳入前端推后续版本评估。
2. 回归：`goal_repository` 既有九函数零改动（差异对照为空）；零迁移断言。
3. Flag off 时端点不可见；既有测试零修改通过。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 六个模块公开签名 | 与 architecture §8.1 ~ §8.6 逐条一致；参数名 / 顺序 / 必填 / 返回注解任一漂移即失败 |
| U2 | `list_plans_by_status` | 状态过滤正确；`statuses` 越出 `PLAN_STATUS_VALUES` 即拒 |
| U3 | `count_plan_versions` | 版本数正确（含 `superseded` / `rejected`） |
| U4 | `list_terminal_plans_since` | 只返回终态；`since` 边界正确 |
| U5 | 三函数零写库 | 打桩断言（零 `add` / `commit` / `update` / `delete`） |
| U6 | `PlansOut` / `PlanDetailOut` / `PlanStepsOut` / `PlanContextOut` / `PlanRevisionsOut` / `PlanPendingOut` | 字段与 §6.3 契约一致 |
| U7 | `PlanPendingOut.reason` 值域 | ∈ `off_surface` / `cooldown` / `predecessor_failed` |
| U8 | 脱敏 | 上下文投影不回显记忆正文 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | `goal_repository` 既有九函数零改动 | 签名 + 行为差异对照为空 |
| I2 | **审计投影** | 可从 `decision_records`（`kind='goal_lifecycle'`）正确投影 `PlanAdvance` |
| I3 | `decision_records.kind` 仍五值 | 值集快照对照（零新增 CHECK 值） |
| I4 | **修订链重建** | `from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps` 逐条可读 |
| I5 | `loop_runs.steps` 子步骤记账 | `plan_assemble` / `plan_execute` / `plan_observe` 记账正确且受既有 `budget_state` 约束 |
| I6 | `life_loop` 九步阶段序列不变 | 形状快照对照零差异 |
| I7 | **零新建表断言** | 可观测面全部投影自四张既有表（静态断言零新表引用） |
| I8 | 三条纪律静态断言 | `PlanScheduler` / `PlanValidator` / `PlanRevisionPolicy` 零 IO；`PlanObserver.observe` 的 `facts` 为注入参数；`PlanContextAssembler` 除 `assemble` 外零 IO |
| I9 | 调试端点门控 | `v25_planning_enabled` / `v25_plan_debug_enabled` / 调试总闸任一 off → 端点不可见 |
| I10 | 调试端点只读 | 打桩断言零写库 |
| I11 | 既有 `/debug/tools*` 面板零改动 | 端点集与输出模型未变 |
| I12 | `list_terminal_plans_since` 被 PLAN-010 消费 | 调用点可追溯；只读 |
| I13 | 零迁移断言 | 迁移链头 `0046`；`ck_goal_plans_status` / `ck_decision_records_kind` 值集未变 |
| I14 | **Flag off 逐字节一致** | 端点不可见；既有测试零修改通过 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」全链可观测** | 目标 → 计划生成 → 逐 tick 执行 → 观测推进 → 终态 | `/debug/plans` 见计划；`/debug/plans/{id}` 见步骤与推进历史；`/debug/plans/{id}/steps` 见 `tool_id` 与 `blocked_reason` |
| S2 | 装配结果可解释 | `/debug/plans/context?user_id=&goal_id=` | 六源齐备 + `degraded` 清单（如 `world_disabled`） |
| S3 | 修订链可追溯 | 三次修订后 `/debug/plans/revisions?goal_id=` | 链上每步 `from/to version`、`reason`、`trigger_source`、`evidence_refs`、`kept_steps` 可读 |
| S4 | 待推进原因可读 | 工具被时段剔除期间 `/debug/plans/pending?user_id=` | `reason="off_surface"` 可读 |
| S5 | 冷却中原因可读 | 步骤刚执行完 | `reason="cooldown"` 可读 |
| S6 | 前端未接入 | 检查 `apps/frontend/` | 无计划视图（Q10 记录，本版本不实现） |
| S7 | Flag off | 总闸 off | 六端点不可见（404 / 未注册） |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 六个模块的公开接口与 architecture §8.1 ~ §8.6 签名逐条一致（契约对照）；任何签名漂移即用例失败。
- `goal_repository` 既有九个计划函数零改动（差异对照为空）；新增三个只读函数有测试且**零写库**（打桩断言）。
- 计划推进审计可从 `decision_records`（`kind='goal_lifecycle'`）正确投影 `PlanAdvance`；`decision_records.kind` 仍为五值（零新增 CHECK 值）。
- 修订链可从 `goal_plans` + `decision_records` 正确重建：`from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps` 逐条可读。
- `loop_runs.steps` 中计划子步骤（`plan_assemble` / `plan_execute` / `plan_observe`）记账正确且受既有 `budget_state` 约束；`life_loop` 九步阶段序列不变。
- 六个调试端点全部受总闸 + 调试子闸门控；Flag off 时端点不可见；`PlanContext` 投影含六源与 `degraded` 清单；步骤视图含 `tool_id` 绑定与 `blocked_reason`。
- 调试投影不回显记忆正文（脱敏）。
- **零新建表断言**：计划可观测面全部投影自 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表。
- 内部接口契约的「只读 / 零 IO / 纯函数」三条纪律各有静态断言（`PlanScheduler` / `PlanValidator` / `PlanRevisionPolicy` 为纯函数；`PlanObserver` 的 `facts` 由调用方注入）。

## 10.2 Integration Acceptance

- `list_terminal_plans_since` 被 PLAN-010 证据窗消费，调用点可追溯且只读。
- 审计写入异常不影响计划推进（与「观测故障只 log」同款纪律）。
- 既有 `/debug/tools*` 面板与 `/debug/traces*` / `/debug/decisions` 端点零改动。
- 新增端点的门控方式与既有面板同构（总闸 + 子闸 + 调试总闸）。
- `life_loop` 九步序列与 `autonomous_tick` stage 序列不变（形状快照对照）。
- 零迁移断言：迁移链头 `0046`；`ck_goal_plans_status` / `ck_decision_records_kind` 值集未变；无新索引。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`。
- **零新建仓储模块**：三个只读函数扩展在既有 `goal_repository` 内（可 grep 验证无新仓储文件）。
- **零新增可观测表**：调试端点全部为只读投影；无物化视图、无缓存表。
- **签名冻结可举证**：六模块签名快照与 architecture §8.1 ~ §8.6 对照，差异为空。
- **Q10 记录留痕**：计划可观测面是否纳入 `apps/frontend/` 调试控制台在本任务内记录，明确本版本不实现、推后续版本评估。
- **子项定级留痕**：6 个调试端点与前端视图作为**可延后子项**（P2 语义）标注，不阻断其余验收条目。
- **文档一致**：本文件与 architecture §8.1 ~ §8.7 / §4.6 / §4.9 / §7.8 / §7.9 / §9.7 Q10 及 tasks.md PLAN-011 Acceptance Criteria 逐条对应，无自相矛盾。
