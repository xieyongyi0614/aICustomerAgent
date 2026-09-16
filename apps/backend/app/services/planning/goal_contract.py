"""PLAN-001 Goal 域契约冻结：Planning 对 Goal System 的唯一合法边界（纯声明，零业务逻辑）。

本模块**只声明常量**：零函数、零 IO、零落库、零模型依赖。契约的可判定断言全部落在
`tests/v25/`（快照对照 + 静态扫描 + 联动不变量）。

────────────────────────────────────────────────────────────────────────────
一、只读消费面（`PLANNING_READ_INTERFACES`，来源 Task Detail §6.1）

| 接口 | 用途 |
|---|---|
| `goal_repository.get_goal` | 规划主体（唯一硬依赖） |
| `goal_repository.list_children` | 祖先/子目标链 |
| `goal_repository.list_tree` | 层级视图 |
| `goal_repository.get_latest_plan` | 当前生效计划 |
| `goal_repository.list_plans` | 版本链 |
| `goal_repository.count_plans` | 修订预算判定 |
| `goal_repository.list_active_plans` | 推进候选集 |
| `goal_arbitration.compute_priority` | **只读**，Planning 不重算 |
| `goal_stack.evaluate_stack` | 四层栈 |
| `models.goal.goal_transitions` | 合法迁移目标查询（诊断用） |

二、写回面（`PLANNING_WRITE_INTERFACES`，**恰好 5 个**，来源 Task Detail §6.2）

| 接口 | 说明 |
|---|---|
| `set_status(goal_id, target, arbitration_state=None)` | 唯一状态变更入口（迁移表守卫） |
| `finish_goal(goal_id, status, failure_reason=None)` | 终态 + `failure_reason` |
| `complete_goal(goal_id)` | `finish_goal(.., "completed")` 便捷式 |
| `fail_goal(goal_id, failure_reason)` | `finish_goal(.., "failed", ..)` 便捷式 |
| `reactivate_goal(goal_id)` | `failed → active` 单边（单次 replan 成功边） |

上表五者均在 `goal_repository`；`set_status` 额外具备仲裁轨迹（`arbitration_state`）原子写入。

**不在写回面**：`expire_goal` / `cancel_goal` / `create_hierarchical_goal` / `create_goal` /
`seed_goals` —— Planning 不得调用；计划被拒（`GoalPlanStatus.rejected`）**不改变** `GoalStatus`。

计划本体的落库面（`create_plan` / `set_plan_status` / `set_plan_rejection` /
`update_plan_progress`）属既有「计划面九函数」；**PLAN-003 起这四者进入调用白名单**
（见下方「九、PLAN-003 契约演进留痕」），由 PLAN-011 做完整契约对照。

三、归因面（每次计划终态调一次，来源 Task Detail §6.3）

`goal_arbitration.record_goal_lifecycle(record, decision, reason, snapshot)` 写
`decision_records`（复用既有 `DecisionKind.GOAL_LIFECYCLE`，**不新增 kind**）。

四、生命周期介入点（**恰好三处**，来源 Task Detail §4.3.2 / architecture §3.2.2）

| # | 介入点（`LIFECYCLE_INTERVENTION_POINTS`） | 时机 | 既有调用 | 约束 |
|---|---|---|---|---|
| 1 | `goal_created` | `materialize` 之后 | `enqueue_planning(goal_created)` | 既有行为不变 |
| 2 | `step_blocked` | `PlanObserver` 判定不可推进 | `enqueue_planning(goal_blocked)` | 既有常量，新增判定来源 |
| 3 | `plan_revision_approved` | `PlanRevisionPolicy` 裁决 | `enqueue(goal_replan)` | 既有常量，新增反思触发源 |

介入点 2 的判定来源属 PLAN-005，介入点 3 的 Reflection 触发源属 PLAN-010；
介入点 1 即既有 `materialize` → `enqueue_planning` 路径。

计划终态**不新增介入点**：全步达成走既有 `goal_observation._complete` → `finish_goal`
（PLAN-005 的 `PlanObserver` 只做包装）。三处的 trigger 取值即 `goal_planning.PLANNING_TRIGGERS`
三元组，`PLANNING_TRIGGER_VALUES` 为其冻结副本（差异由快照用例比对，非新增枚举域）。

五、`failure_reason` 取名词表（`PLANNING_FAILURE_REASONS`，来源 Task Detail §4.5）

`GoalStatus` 的新增语义一律经 `failure_reason` **字符串**承载（既有范式：`goal_completed` /
`exec_period_exceeded` / `subgoal_threshold_exceeded` / `replan_exhausted` 均已在用）。

| 词条 | 含义 | 触发者 |
|---|---|---|
| `plan_exhausted` | 计划达修订预算仍不可行 | PLAN-005 `PlanRevisionPolicy` |
| `criteria_undecidable` | 判据连续不可判定，重规划亦无改善 | PLAN-005 |

**不新增列、不扩 CHECK**：`character_goals.failure_reason` 是既有可空 String 列，新词条无需 DDL。

六、禁止事项（`PLANNING_FORBIDDEN_PRACTICES`，来源 Task Detail §10.1 / §10.3）

1. `second_priority_algorithm`：重算优先级，或按目标 tier / 显式 priority 对**计划步骤**重排
   （计划步骤顺序只由 `depends_on` DAG + `index` 升序决定，即结构序）。
2. `character_priority_asset_import`：导入角色优先级资产（`app/character/**`）。
   **PLAN-003 起的唯一窄例外**：`app.character.asuna.scene_profiles`（场景画像资产，
   非优先级资产）——`PlanContext.scene` 按 Task Detail §4.1.3 取 `scene_profile_for`；
   例外范围由 `tests/v25/test_plan001_static_scan.py::ALLOWED_CHARACTER_IMPORT_MODULES`
   逐模块枚举，不得扩成前缀。
3. `direct_goal_row_persistence`：直构 ORM 行对象或直接构造写语句写 `character_goals`，
   绕过 `goal_repository` 写面。
4. `new_goal_status_value`：新增 `GoalStatus` 取值。
5. `new_goal_transition_edge`：新增 `GOAL_TRANSITIONS` 边。
6. `new_planning_trigger_value`：新增规划触发源（只有 `goal_created` / `goal_blocked` / `goal_replan`）。
7. `goal_status_change_on_plan_rejection`：计划被拒时改写 `GoalStatus`。
8. `fourth_lifecycle_intervention_point`：在计划终态之外新增对目标生命周期的介入点。

七、契约的运行时事实（Task Detail §6.5 的核对待报项）

- 迁移表守卫由 `models.goal.goal_transitions` 承担；`IllegalGoalTransition(ValueError)` 是声明的
  异常类型，但既有写面（`goal_repository`）在非法迁移时抛的是 `ValueError` 本身——
  Planning 侧一律按 `ValueError` 捕获，二者兼容（`IllegalGoalTransition` 是 `ValueError` 子类）。
- 迁移必然失败（终态 → 任何态）表现为 `goal_transitions` 返回空元组，视为业务结果，不重试。

八、联动不变量 I2 的两种允许形态（Task Detail §4.4 I2）

「目标终态不得留下仍在推进的计划」有两种合法实现，本任务冻结两者**至少成立其一**：

1. **冻结（今日已成立）**：推进候选集取自 `PLANNING_ADVANCE_CANDIDATE_GATE`，其查询条件含
   `GoalRow.status == "active"`——目标一转终态，其计划即刻退出候选集，不再被推进/调度。
2. **进终态（待 PLAN-005 落地）**：`PlanObserver.settle` 在结算目标终态的同时把该计划置
   `superseded`。PLAN-001 只冻结契约，不实现 `settle`；对应断言在 `tests/v25/test_plan001_deferred.py`
   中显式登记为 deferred（不得以编造实现来满足）。

────────────────────────────────────────────────────────────────────────────
九、PLAN-003 契约演进留痕（**预期的越界评审点**，PLAN-001 已预告）

Task Detail §10.3 的白名单原为 §6.1 ∪ §6.2（12 项，Goal 状态读写面）。PLAN-003 的计划引擎
必须经既有计划面四函数落库（`create_plan` / `set_plan_status` / `set_plan_rejection` /
`update_plan_progress`），故 `PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS` 由 **12 项扩为 16 项**。
演进范围精确且最小：

- 只加这四者——`expire_goal` / `cancel_goal` / `seed_goals` / `create_goal` /
  `create_hierarchical_goal` / `list_layered*` 等既有旁路调用**仍不在白名单**。
- `PLANNING_WRITE_INTERFACES`（恰好 5 个 Goal 状态写面）**不变**：计划面四函数不属 Goal
  状态写面，计划被拒仍不改 `GoalStatus`。
- 同步更新三处冻结快照（均属留痕而非放松）：`test_plan001_static_scan.py` 的白名单口径、
  `test_plan001_goal_contract.py` 的白名单计数与集合断言、`test_plan001_scope_markers.py`
  的「已落地 / 仍不得预埋」标记。
"""

PLANNING_READ_INTERFACES: tuple[tuple[str, str], ...] = (
    ("app.repositories.goal_repository", "get_goal"),
    ("app.repositories.goal_repository", "list_children"),
    ("app.repositories.goal_repository", "list_tree"),
    ("app.repositories.goal_repository", "get_latest_plan"),
    ("app.repositories.goal_repository", "list_plans"),
    ("app.repositories.goal_repository", "count_plans"),
    ("app.repositories.goal_repository", "list_active_plans"),
    ("app.services.goal_arbitration", "compute_priority"),
    ("app.services.goal_stack", "evaluate_stack"),
    ("app.models.goal", "goal_transitions"),
)

PLANNING_WRITE_INTERFACES: tuple[tuple[str, str], ...] = (
    ("app.repositories.goal_repository", "set_status"),
    ("app.repositories.goal_repository", "finish_goal"),
    ("app.repositories.goal_repository", "complete_goal"),
    ("app.repositories.goal_repository", "fail_goal"),
    ("app.repositories.goal_repository", "reactivate_goal"),
)

PLANNING_WRITE_FUNCTION_NAMES: tuple[str, ...] = (
    "set_status",
    "finish_goal",
    "complete_goal",
    "fail_goal",
    "reactivate_goal",
)

PLANNING_ATTRIBUTION_TARGET: tuple[str, str] = (
    "app.services.goal_arbitration",
    "record_goal_lifecycle",
)

PLANNING_TRIGGER_TARGET: tuple[str, str] = (
    "app.services.goal_planning",
    "enqueue_planning",
)

PLANNING_TRIGGER_VALUES: tuple[str, ...] = (
    "goal_created",
    "goal_blocked",
    "goal_replan",
)

LIFECYCLE_INTERVENTION_POINTS: tuple[tuple[str, str, str], ...] = (
    ("goal_created", "goal_planning.materialize", "goal_created"),
    ("step_blocked", "PlanObserver", "goal_blocked"),
    ("plan_revision_approved", "PlanRevisionPolicy.should_replan", "goal_replan"),
)

PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS: tuple[str, ...] = (
    "get_goal",
    "list_children",
    "list_tree",
    "get_latest_plan",
    "list_plans",
    "count_plans",
    "list_active_plans",
    "set_status",
    "finish_goal",
    "complete_goal",
    "fail_goal",
    "reactivate_goal",
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
)

PLANNING_FAILURE_REASON_PLAN_EXHAUSTED = "plan_exhausted"
PLANNING_FAILURE_REASON_CRITERIA_UNDECIDABLE = "criteria_undecidable"

PLANNING_FAILURE_REASONS: tuple[str, ...] = (
    PLANNING_FAILURE_REASON_PLAN_EXHAUSTED,
    PLANNING_FAILURE_REASON_CRITERIA_UNDECIDABLE,
)

PLANNING_FORBIDDEN_PRACTICES: tuple[str, ...] = (
    "second_priority_algorithm",
    "character_priority_asset_import",
    "direct_goal_row_persistence",
    "new_goal_status_value",
    "new_goal_transition_edge",
    "new_planning_trigger_value",
    "goal_status_change_on_plan_rejection",
    "fourth_lifecycle_intervention_point",
)

GOAL_STATUS_PLANNABLE: tuple[str, ...] = ("active",)

GOAL_STATUS_TERMINAL: tuple[str, ...] = (
    "completed",
    "failed",
    "abandoned",
    "expired",
    "cancelled",
)

PLANNING_ADVANCE_CANDIDATE_GATE: tuple[str, str] = (
    "app.repositories.goal_repository",
    "list_active_plans",
)
