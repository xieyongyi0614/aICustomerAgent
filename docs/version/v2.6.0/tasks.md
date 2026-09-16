# V2.6.0 Action Execution System Tasks

> **上游**：`docs/version/v2.6.0/architecture.md`
> **状态**：已实现（TASK-001 ~ TASK-009 DONE）
> **主干**：TASK-001 ~ TASK-009（依赖顺序即文档顺序）
> **说明**：本文档只做任务级拆分；各任务 Task Detail 见 `tasks/TASK-XXX.md`（TASK-001 ~ TASK-009），不含代码、不含 DDL 与迁移脚本。
> **定位复述**：Action Execution System = **行动执行层**。把 V9 遗留的「单次动作执行」（`action_engine.run_action_planning`）升级为一个统一 Action 抽象 + 执行引擎 + 调度器 + 结果系统，打通 Plan → Action → Execution → Result → State Update → Feedback 闭环。

---

## 0. 关键前提裁决（先读）

> 本版本所有任务建立在**一条前提裁决**之上：**Action 持久化复用既有 `action_records` 表，不新建 `actions` / `action_results` 表。**

**理由（对照 architecture §1.2 既有资产盘点、§9.3 零迁移裁决）**：

| 用户 Task 拆分的设想表 | 既有承载物 | 本版本裁决 |
|---|---|---|
| `actions` 表 | **`action_records` 表（V9 既有）** | 复用 + 扩展模型字段，不新建 |
| `action_results` 表 | **`action_records.result`（JSON 列）+ `ActionResult` 值对象（既有）** | 复用 + 强化 `ActionResult` 值对象，不新建表 |
| execution records | **`action_records.steps`（JSON 列）+ `ToolExecution` / `CapabilityResult`** | 复用 |

**唯一新表**：`action_schedules`（调度语义无法用单表承载，见 architecture §9.3 裁决）。

**为什么不能照搬「新建 actions 表」**：项目铁律是「零新建表、零迁移、复用既有」（V2.5.0 红线 1 的延续）。`action_records` 已含六态状态机、`scheduled_at`/`executed_at`/`dedupe_key`/`attempt`/`next_retry_at`/`steps`/`result` 全部字段，仓储已含 `save_record`/`get_record`/`list_records`/`list_retryable`/`list_planned`/`count_active`/`save_record_with_outbox`——新建 `actions` 表会引入「库与代码双源」并破坏零迁移断言。这是「避免重复设计」原则的直接体现（对照 AGENTS.md 全局约定与架构演进方向）。

---

## 1. 任务总览

### 1.1 总览表

| ID | Task Name | Priority | Dependencies | Phase |
|---|---|---|---|---|
| TASK-001 | Action Core Model | P0 | 无 | Phase 1 领域地基 |
| TASK-002 | Action Persistence Layer | P0 | TASK-001 | Phase 1 领域地基 |
| TASK-003 | Action Manager | P0 | TASK-001, TASK-002 | Phase 2 执行核心 |
| TASK-004 | Action Executor | P0 | TASK-003 | Phase 2 执行核心 |
| TASK-005 | Action Scheduler | P1 | TASK-002 | Phase 3 增强能力 |
| TASK-006 | Action Result System | P1 | TASK-004 | Phase 3 增强能力 |
| TASK-007 | System Integration | P1 | TASK-004, TASK-006 | Phase 4 系统集成 |
| TASK-008 | API / Interface Layer | P1 | TASK-003, TASK-004 | Phase 5 接口层 |
| TASK-009 | Testing & Validation | P0 | TASK-001 ~ TASK-008 | Phase 5 验收 |

**Priority 语义**：P0 = 版本发布阻断项（缺一不可上线）；P1 = 版本价值主体；P2 = 可延后至版本内末尾或下一版本。
**Priority ≠ 顺序**：TASK-009 为 P0 但必须最后执行（验收性质决定）。
**Dependencies 记法**：只列**直接**前置；由于 TASK-004 传递依赖 TASK-003 → TASK-002 → TASK-001，故 TASK-005 ~ TASK-009 不再重复罗列 TASK-001 ~ TASK-003。

### 1.2 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| **Phase 1 领域地基** | 001, 002 | Action 统一抽象冻结；六态状态机与迁移数学就位；`action_records` 扩展 + `action_schedules` 新表 |
| **Phase 2 执行核心** | 003, 004 | Action 生命周期可管理；三种执行方式（Internal/Tool/External）可分派；异常捕获与结果捕获 |
| **Phase 3 增强能力** | 005, 006 | 延迟/定时/优先级/队列统一到 Action 级；ActionResult 统一契约 + 旧读键退役 |
| **Phase 4 系统集成** | 007 | Planning / World / Relationship / Memory 四系统接线完成 |
| **Phase 5 接口与验收** | 008, 009 | 内部接口契约冻结；全部 Gate 全绿 |

---

## 2. 依赖关系

### 2.1 依赖关系图

```text
Phase 1 领域地基
─────────────────────────────────────────────────────────────────
TASK-001 Action Core Model
    │
    ▼
TASK-002 Action Persistence Layer
    │
    ├─────────────────────────────────────┐
    ▼                                     ▼
Phase 2 执行核心                          Phase 3（调度，仅依赖 002）
──────────────────────────────────────────────
TASK-003 Action Manager               TASK-005 Action Scheduler
    │
    ▼
TASK-004 Action Executor
    │
    ├──────────────────┐
    ▼                  ▼
TASK-006            TASK-007
Action Result       System Integration
System              （Planning/World/Relationship/Memory）
    │                  │
    ├──────────┬───────┘
    ▼          ▼
Phase 5 接口与验收
─────────────────────────────────────────────────────────────────
TASK-008 API / Interface Layer
    │
    ▼
TASK-009 Testing & Validation
    ▲ 全量扇入：TASK-001 ~ TASK-008
```

### 2.2 关键路径

```text
TASK-001 → TASK-002 → TASK-003 → TASK-004 → TASK-006 → TASK-007 → TASK-008 → TASK-009
```

（8 个任务，为本版本最长依赖链。经 TASK-005 的链与之并行，且 TASK-005 只依赖 TASK-002，可提前启动。）

### 2.3 并行建议

| 可并行组 | 任务 | 前提 |
|---|---|---|
| A | TASK-005 ‖ TASK-003 ‖ TASK-004 | TASK-002 完成（TASK-005 只依赖 `action_schedules` 表与 `ActionRecord.scheduled_at`/`priority` 字段） |
| B | TASK-006 的 `ActionResult` 值对象强化可先于 TASK-004 收尾启动 | TASK-001 完成（纯值对象，只依赖 Action 模型） |

---

## 3. 任务明细

## TASK-001 Action Core Model

Priority: P0

Goal: 建立 Action 的**统一领域模型**：在既有 `models/action.py` 之上，冻结 `Action` 值对象（六问可答）、`ActionType` 执行方式映射、`ActionStatus` 六态状态机与完整生命周期，使 Action 成为独立于 Goal / Plan / Tool 语义的抽象层（architecture §6）。

Description:

- **复用既有 `app/models/action.py`，不新建模型模块**（对照 architecture §1.2 既有资产盘点）：
  - `ActionType`（9 值）/ `ACTION_TYPES` / `ActionStatus`（6 值）/ `ACTION_STATUSES` / `TERMINAL_STATUSES` / `GateReason`（10 值）/ `FailureKind`（4 值）/ `transition_action`（六态迁移纯函数）**一律不改语义**。
  - `ActionRecord` 已含 `id`/`user_id`/`action_type`/`intent`/`params`/`status`/`gate_reason`/`steps`/`result`/`attempt`/`next_retry_at`/`scheduled_at`/`executed_at`/`dedupe_key`/`source`/`goal_id`——**执行台账字段已完备，本任务只做「统一抽象」的语义强化，不新增状态值、不扩 CHECK**。
- **新增 `Action` 值对象（运行期，不落库）**：把散落在 `ActionIntent`（决策产物）/ `ActionRecord`（台账）/ `ActionStep`（执行步骤）三处的字段，收敛为一个可回答「是什么（type）/ 做什么（target+parameters）/ 什么状态（status）/ 什么结果（result）/ 什么时候创建（created_at）/ 什么时候执行（scheduled_at/executed_at）」六问的统一抽象。字段集对齐 architecture §6.1，`source` 扩展 `plan` / `event_driven` 两个取值（既有 `ActionSource` 为 `conversation`/`autonomy`/`cancel`，新增计划与事件驱动两个来源，**不改既有三值语义**）。
- **新增 `ActionType → ExecutionKind` 映射**（`ACTION_EXECUTION_MAP`，角色资产层，纯数据）：`create_reminder`/`cancel_reminder`/`remember_fact`/`create_object`/`move_object`/`use_object` → `INTERNAL`；`query_environment`/`query_search` → `TOOL`；`send_notification` → `EXTERNAL`（经 Tool Adapter，预留）。`ExecutionKind = Literal["internal", "tool", "external"]`（architecture §6.2）。
- **六态状态机语义强化（不改值集）**：`ActionStatus` 六态 `created`/`planned`/`executing`/`succeeded`/`failed`/`cancelled` 与既有 `_TRANSITIONS` 迁移表**完全保留**；本任务补一张「语义对照表」（`created`=已创建未调度 / `planned`=已排期待执行 / `executing`=执行中 / `succeeded`=成功终态 / `failed`=失败终态可重试 / `cancelled`=取消终态），并明确 `failed → planned`（retry）是唯一从终态回退的边，受 `action_retry_max_attempts` 约束（architecture §6.4）。
- **生命周期事件**：`ActionTransitionEvent`（8 值）沿用；生命周期四阶段（创建 → 调度 → 执行 → 终态）以 `transition_action` 纯函数为唯一迁移权威，非法迁移返回 `None`（既有纪律）。
- **明确不做**：不新增 `ActionStatus` 值（六态已完备）；不新增 `ActionType` 值（九能力已完备，外部能力经 `EXTERNAL` 执行方式挂载而非新增类型）；不把 `Action` 值对象落库（落库的是 `ActionRecord`，`Action` 是它的运行期投影）。
- 对应 architecture §6（§6.1 ~ §6.4）、§3.1（G1）。

Dependencies: 无

Acceptance Criteria:

- **零改动断言**：`ActionType` / `ActionStatus` / `GateReason` / `FailureKind` / `ACTION_TYPES` / `ACTION_STATUSES` / `TERMINAL_STATUSES` / `GATE_REASONS` / `FAILURE_KINDS` 值集与 `_TRANSITIONS` 迁移数学零变化（差异对照为空）；`transition_action` 行为不变。
- **六问可答断言**：`Action` 值对象可回答「是什么 / 做什么 / 什么状态 / 什么结果 / 什么时候创建 / 什么时候执行」六问，且有 `model_dump` / `model_validate` 序列化往返测试。
- **`ACTION_EXECUTION_MAP` 全覆盖断言**：九个 `ActionType` 全部有 `ExecutionKind` 映射，无遗漏；`send_notification` 映射为 `EXTERNAL`。
- **`ActionSource` 扩展断言**：`source` 值域含 `plan` / `event_driven` 且不破坏既有 `conversation`/`autonomy`/`cancel` 三值；`ActionRecord.source` 读取新值时安全（Pydantic Literal 校验通过）。
- **状态机纯函数断言**：非法迁移返回 `None`（用例：`succeeded` → 任意事件 = `None`）；`failed → planned` 仅在 `transition_action` 显式支持的重试路径发生（受 `attempts_exceeded` 约束）。
- **模型层纯值对象断言**：`Action` / `ActionRecord` / `ActionResult` 零 `app.repositories` / `app.application` / `app.services` 依赖（静态断言，同 `models/action.py` 既有纪律）。
- Flag 全 off 时既有 `models/action.py` 测试零修改通过。

---

## TASK-002 Action Persistence Layer

Priority: P0

Goal: 交付 Action 数据存储：复用 `action_records` 表承接 Action 本体与结果，新增唯一表 `action_schedules` 承接调度；交付 Schema、Migration、Repository 三件套（architecture §9）。

Description:

- **复用 `action_records` 表（不新建 `actions` / `action_results` 表）**——见 §0 前提裁决。`ActionRecordRow`（`app/core/db.py`）已有全部列，本任务只做**模型字段扩展 + 仓储扩展**：
  - `ActionRecord` 模型新增 `priority: int = 100` 字段（调度排序用，`scheduled_at` 已有）；`ActionRecordRow` 对应加列 `priority`（**本版本唯一一次对 `action_records` 的加列**，其余字段全部复用）。
  - `steps` JSON 列已承载 `capability`/`action`/`params`/`status`/`result`，本任务不扩其结构。
  - `result` JSON 列已承载执行结果，本任务统一其 schema 为 `ActionResult` 值对象（见 TASK-006），本任务只保证落库/读回往返一致。
- **新增 `action_schedules` 表（唯一新表）**：字段对齐 architecture §9.3——`id`（PK）/ `action_id`（FK → `action_records.id`）/ `when_type`（`immediate`/`delay`/`cron`）/ `scheduled_at`（timestamptz）/ `priority`（int，默认 100）/ `status`（`scheduled`/`due`/`executed`/`cancelled`）/ `created_at` / `updated_at`。约束：`uq_action_schedules_action (action_id)`（一 Action 一调度）；索引 `idx_action_schedules_due (status, scheduled_at, priority)`。
- **Migration**：线性 down_revision 链接当前迁移链头（V2.5.0 为 0046，实现期以实际链头为准）；建 `action_schedules` 表 + `action_records` 加 `priority` 列；SQLite 不支持的约束变更沿用 `batch_alter_table` 模式（既有惯例）；逆放可执行纳入回归。
- **Repository 扩展（模块级函数仓储惯例，沿用 `action_repository.py`）**：
  - 复用既有 `save_record` / `get_record` / `list_records` / `list_by_status` / `list_retryable` / `list_planned` / `list_by_dedupe` / `count_active` / `recent_records` / `retain_cleanup` / `save_record_with_outbox`——**零改动**。
  - 新增 `save_schedule` / `get_schedule` / `list_due_schedules(now, limit)` / `mark_schedule_executed` / `mark_schedule_cancelled`（对应 `action_schedules` 表 CRUD）。
  - `save_record` 的更新字段列表扩 `priority`（与 `scheduled_at`/`executed_at` 并列）。
- **明确不做**：不新建 `action_results` 表（结果落 `action_records.result` JSON 列）；不新建 execution records 表（落 `action_records.steps` JSON 列）；不新建独立 Repository 模块（沿用模块级函数仓储惯例）。
- 对应 architecture §9（§9.1 ~ §9.4）、§0 前提裁决。

Dependencies: TASK-001

Acceptance Criteria:

- **复用断言**：`action_records` 表结构与既有列语义未动（除 `priority` 加列）；`ActionRecordRow` 差异对照仅 `priority` 一列。
- **新表断言**：`action_schedules` 表结构与 §9.3 逐条一致；`uq_action_schedules_action` 唯一约束生效（重复 `action_id` 落库被拒）；`idx_action_schedules_due` 索引存在。
- **迁移断言**：迁移链头 = 既有链头 + 1；down_revision 线性链接；逆放可执行（`alembic downgrade` 后 `action_schedules` 消失、`action_records.priority` 移除）；SQLite 兼容（batch mode 验证）。
- **仓储断言**：既有 11 个函数零改动（差异对照为空）；新增 5 个 schedule 函数有测试且往返一致（save → get → list → mark）。
- **结果往返断言**：`result` JSON 列写入 `ActionResult` 值对象后读回字段无丢失（`model_dump` / `model_validate` 往返）。
- **加列落库断言**：`priority` 字段经 `save_record` 持久化后读回一致（默认 100）。
- Flag 全 off 时既有 `action_repository` 测试零修改通过。

---

## TASK-003 Action Manager

Priority: P0

Goal: 实现 Action 生命周期管理：`create` / `update` / `query` / `cancel` / `retry` / `get_status` 六能力的统一入口，作为 Action 的**唯一生命周期管理者**（architecture §8.1）。

Description:

- **强化既有 `action_engine` + `action_repository`，不新建管理器模块**（对照 architecture §1.2、§8.1）：
  - 新建 `app/services/action/manager.py`（模块级函数形态，对齐既有 `services/action/*` 惯例），作为 Action 生命周期管理的**唯一入口**，内部委托既有 `action_engine` / `action_repository`。
  - `create(intent | plan_step, *, source)` → `Action`：统一抽象构造（type / target / params / priority / dedupe_key），落 `action_records`（`status=created`）；`dedupe_key` 复用既有 `make_dedupe_key`。
  - `update(action_id, **fields)` → `Action`：受控字段更新（仅 `status`/`params`/`priority`/`scheduled_at` 可更新，`id`/`user_id`/`action_type`/`dedupe_key` 不可变）。
  - `query(action_id | filters)` → `Action | list[Action]`：委托既有 `get_record` / `list_records` / `list_by_status`。
  - `cancel(action_id, *, reason)` → `bool`：仅 `created`/`planned` 可取消（`executing` 不可取消，等自然结束——既有 `transition_action` 语义）；落 `gate_reason=reason`。
  - `retry(action_id)` → `ActionResult | None`：仅 `failed` 可重试（受 `action_retry_max_attempts` 约束）；复用原 `dedupe_key`（防重复副作用）；`attempt+1` 回填。
  - `get_status(action_id)` → `ActionStatus`：读 `action_records` 当前态。
- **关键约束（architecture §3.3 设计原则落地）**：
  - `create` **不判断「该不该做」**——那是 `decision_pipeline` 的职责（G3：Executor 不决策、Manager 也不决策）。
  - `create` **不拆步骤**——那是 Planning 的职责（G2：Planning 不执行、Manager 不编排）。
  - `cancel` / `retry` **不写世界 / 记忆 / 关系**——只改 Action 状态，副作用回滚由既有通道处理。
- **唯一写面纪律**：`action_records` 的状态迁移**唯一入口是 `action_engine.run_action_planning`**（V2.5.0 红线 3 延续）；`ActionManager` 的 `cancel`/`retry` 是对「非执行路径」状态变更的补充入口，不绕过 `action_engine` 的六闸门。
- 对应 architecture §8.1、§3.3（G2/G3）、§6.3（生命周期）。

Dependencies: TASK-001, TASK-002

Acceptance Criteria:

- **六能力断言**：`create` / `update` / `query` / `cancel` / `retry` / `get_status` 各有可判定用例，签名与 §8.1 一致。
- **唯一入口断言**：`ActionManager` 是 Action 生命周期的唯一入口；`app/services/action/manager.py` 外无对 `action_repository.save_record` 状态字段的直接写（静态断言）。
- **职责边界断言（G2/G3）**：`create` 不调 `decision_pipeline`（不决策）、不调 `goal_planning`（不编排）；`retry` 复用原 `dedupe_key`（同 key 断言）。
- **状态约束断言**：`cancel` 对 `executing`/`succeeded`/`failed`/`cancelled` 返回 `False`（仅 `created`/`planned` 可取消）；`retry` 对非 `failed` 返回 `None`；`retry` 达 `action_retry_max_attempts` 后返回 `None`。
- **幂等断言**：`create` 同 `dedupe_key` 重复调用受既有去重闸门约束（不产生重复副作用）；`retry` 复用原 `dedupe_key` 不产生新键。
- **不写世界断言**：`cancel` / `retry` 零 `world_engine` / `memory_policy` / `relationship_bridge` 调用（打桩断言）。
- Flag 全 off 时 `action_engine` 原路径生效，行为与 V2.5.0 逐字节一致。

---

## TASK-004 Action Executor

Priority: P0

Goal: 实现 Action 执行引擎：Executor Interface（分派三种执行方式）、Execution Flow、Error Handling、Result Capture，作为「接收 Action → 选执行方式 → 执行 → 捕获异常 → 返回结果」的统一执行面（architecture §8.2）。

Description:

- **复用既有 `CapabilityExecutor` + `ToolExecutor`，不新建执行器**（对照 architecture §1.2、§8.2）：
  - 新建 `app/services/action/executor.py`：`ActionExecutor` 分派层，统一三种执行方式的接口。
  - `dispatch(action) -> ExecutionKind`：按 `ACTION_EXECUTION_MAP`（TASK-001 交付）查 `action.type` → 执行方式（纯函数，零 IO）。
  - `execute_internal(action, ctx)`：内部动作（写世界/记忆），委托既有 `CapabilityExecutor.run`。
  - `execute_tool(action, ctx)`：工具调用，委托既有 `ToolExecutor.run`（五段短路：resolve → permission → validate → invoke → normalize）。
  - `execute_external(action, ctx)`：外部服务，经 Tool Adapter（**本版本只预留接口，不实现具体外部能力**——architecture §8.4）。
  - `run(action, ctx) -> ActionResult`：统一入口，捕获异常 / 超时 / 归一 → `ActionResult`；**不做重试决策**（重试在 Action 层 / Manager 层）。
- **Executor Interface**：三种执行方式统一为一个接口签名 `execute(action, ctx) -> ActionResult`，`ActionResult.status ∈ {succeeded, failed, partial}`，`failure_kind ∈ {transient, permanent, timeout, unavailable}`。
- **Execution Flow**：`dispatch → execute_* → 捕获异常 → 归一结果`；同步执行（`await` 阻塞）用于前台即时动作，异步执行（挂 `background_jobs`/`outbox`）用于后台自治动作，长任务受 `action_execution_timeout_seconds` 约束（architecture §7.2）。
- **Error Handling（承 V9 + V2.4.0 纪律）**：工具失败永不静默假成功；工具失败永不阻塞回复；所有异常落执行台账；异常归一为 `ActionResult.status=failed`，`failure_kind` 由 `error_map` 决定，默认 `transient`（architecture §8.2）。
- **Result Capture**：`ActionResult`（既有值对象）统一承载结果——`status`/`effects`/`error`/`failure_kind`，本任务只保证「每次执行必产 `ActionResult`」，结构化强化在 TASK-006。
- **明确不做**：不实现具体外部能力（飞书/日历/搜索/API 留给 V2.7.0）；不做重试决策（重试在 Action 层）；不做「要不要做/做哪个」判断（G3）。
- 对应 architecture §8.2、§7.2、§3.3（G3/G5）。

Dependencies: TASK-003

Acceptance Criteria:

- **分派断言**：九个 `ActionType` 经 `dispatch` 正确映射到三种 `ExecutionKind`（`send_notification` → `external`、`query_environment` → `tool`、`create_reminder` → `internal`）；`dispatch` 纯函数（零 IO 静态断言）。
- **三种执行方式断言**：`execute_internal` 委托 `CapabilityExecutor`、`execute_tool` 委托 `ToolExecutor`、`execute_external` 预留接口（占位返回 `unavailable`，不抛异常）。
- **G5 结果必产断言**：`run` 对成功 / 失败 / 超时 / 异常四类输入**均返回非空 `ActionResult`**（无 `None` 返回）；任何执行路径都有结果捕获。
- **G3 不决策断言**：`ActionExecutor` 不调 `decision_pipeline` / `autonomy_policy`（静态断言）；`run` 不做重试（零 `next_retry_at` 写入）。
- **异常归一断言**：工具异常归一为 `status=failed` + 非空 `failure_kind`；`error_map` 覆盖 `timeout` / `permanent` / `unavailable` / 默认 `transient`；无静默假成功（失败必 `failed`）。
- **不阻塞回复断言**：执行失败 / 超时不影响回复链路（对齐 V9「工具失败永不阻塞回复」纪律）。
- **工具治理不绕过断言**：`execute_tool` 经 `ToolExecutor.run` 五段短路，零直调 `Capability.execute`（静态断言，对齐 V2.5.0 G-EXEC）。
- Flag 全 off 时 `action_engine` 原执行路径生效，行为与 V2.5.0 逐字节一致。

---

## TASK-005 Action Scheduler

Priority: P1

Goal: 支持未来主动行为：延迟执行 / 定时执行 / 优先级排序 / 队列管理，统一到 Action 级调度语义（architecture §8.3），复用既有 `trigger_registry` / `background_jobs` / `outbox` 三设施。

Description:

- **新建 `app/services/action/scheduler.py`：`ActionScheduler` 纯函数 + 轻量编排**，统一既有三设施的 Action 级调度语义：
  - `schedule(action, *, when, priority) -> ActionSchedule`：`when = None`（立即）/ `delay`（延迟，`scheduled_at = now + delta`）/ `cron`（定时，`scheduled_at = 下一次触发时刻`）；落 `action_schedules` 表（TASK-002 交付）。
  - `sort_queue(actions) -> list[Action]`：`priority` 降序 + `scheduled_at` 升序 + `id` 字典序（确定性 tiebreak）。
  - `due_actions(now) -> list[Action]`：到期 Action 集（`scheduled_at <= now` 且 `status ∈ {scheduled, due}`）。
  - `next_action() -> Action | None`：队列头（最高优先级最早到期）。
- **调度语义统一（architecture §8.3，B4 关闭点）**：
  - 延迟执行 → `schedule(when=delay)`，到期后经 `trigger_registry`（`action_due`）触发消费。
  - 定时执行 → `schedule(when=cron)`，复用 `background_jobs` / `outbox` 既有循环。
  - 优先级排序 → `sort_queue`（纯函数，唯一排序权威）。
  - 队列管理 → `due_actions` / `next_action`（`action_schedules` 表为队列 SoT）。
- **挂载**：`life_loop` 维护步骤新增 `action_schedule` 一步（`life_loop._step_action_schedule`，与 `world_simulation` 并列，**不改既有步骤序列顺序**，只新增一步）；到期 Action 经既有 `trigger_registry` 投递 `action_due` → `action_engine.run_action_planning`。
- **示例链路落地（architecture §8.3）**：「明天早上提醒我学习」→ `Action{type: create_reminder, target: user, params: {content:"学习", due_at: 明早 8:00}}` → `schedule(when=明早 8:00, priority=100)` → 到期 → `ActionManager.execute` → `ActionResult{status: succeeded}` → 反馈。
- **明确不做**：不新建调度循环 / Worker（挂既有 `life_loop` 维护步）；不实现 cron 表达式解析器（`cron` 语义简单到「下一次时刻」，复杂 cron 留给 V2.7.0 日历工具，architecture §9.7 Q2）。
- 对应 architecture §8.3、§7.2、§9.3（`action_schedules`）、§9.7 Q2。

Dependencies: TASK-002

Acceptance Criteria:

- **调度断言**：`schedule` 三种 `when`（immediate/delay/cron）各有用例；`scheduled_at` 计算正确（`delay` = now + delta，`cron` = 下一次触发）。
- **排序断言**：`sort_queue` 确定性（同输入同输出）；优先级降序 + 时刻升序 + id 字典序 tiebreak 可复现。
- **队列断言**：`due_actions(now)` 只返回到期且未执行 Action；`next_action` 返回队列头；`uq_action_schedules_action` 保证一 Action 一调度。
- **挂载断言**：`life_loop` 维护步骤序列新增 `action_schedule` 一步，既有步骤顺序不变（形状快照对照）；到期 Action 经 `trigger_registry`（`action_due`）投递。
- **示例链路断言**：「明天早上提醒我学习」端到端可复现（Plan → Action → Schedule → 到期执行 → 反馈）。
- **复用断言**：不新建调度循环 / Worker（`main.py` lifespan 零新增）；调度消费经既有 `trigger_registry` / `background_jobs` / `outbox`。
- **cron 简化断言**：`cron` 语义仅「下一次触发时刻」，不引入 cron 解析器（负例：复杂 cron 表达式被拒）。
- Flag 全 off 时 `action_schedules` 不参与调度，行为与 V2.5.0 逐字节一致。

---

## TASK-006 Action Result System

Priority: P1

Goal: 处理执行结果：强化 `ActionResult` 值对象为统一结果契约（id / action_id / status / output / error / metadata / created_at），处理成功 / 失败 / 部分完成 / 重试四类结果，并**兑现 V2.4.0「旧读键退役窗口推到 V2.6.0」承诺**（architecture §8.4）。

Description:

- **强化既有 `ActionResult` 值对象（`models/action.py`，V9 既有），不新建结果模型**：
  - 既有字段 `status`（succeeded/failed/partial）/ `effects` / `error` / `failure_kind` **保留语义**。
  - 新增 `id` / `action_id` / `output`（结构化输出，替代自由 `payload`）/ `metadata`（usage / failure_kind / external_calls）/ `observations`（给下游消费的事实）/ `created_at`（对齐 architecture §8.4）。
  - `status` 值集扩 `timeout`（`succeeded`/`failed`/`partial`/`timeout`，对齐 `CapabilityResult.status` 已有 `timeout` 语义，**不新增冲突值**）。
- **结果处理四类（architecture §8.4）**：
  - **成功结果**：`status=succeeded`，`output` 结构化，`effects` 回写四通道（world/memory/relationship/note）。
  - **失败结果**：`status=failed`，`failure_kind` 决定重试策略（`transient`/`timeout` → 可重试，`permanent` → 不重试）。
  - **部分完成**：`status=partial`，`effects` 含已完成部分，记录不回滚（既有纪律）。
  - **重试**：`retry` 复用原 `dedupe_key`，防重复副作用。
- **统一结果契约（B5/B7 关闭点）**：
  - `CapabilityResult.payload`（V9 自由 dict）→ 退役旧读键，统一为 `ActionResult.output` + `effects` + `observations`。
  - `ToolResult`（V2.4.0 契约）→ 提升为 `ActionResult` 的 Tool 级投影，`PlanStepOutcome`（V2.5.0）→ 映射到 `ActionResult`（Plan 层只读投影）。
  - **兑现 V2.4.0 兼容承诺**：V2.4.0 §5.5「V9 既有读键保留到 V2.5.0，正式退役窗口推到 V2.6.0」——本任务完成退役，双写一个版本窗口（V2.6.0）后退役旧键 `world_event_id` / `memory_id` / `failure_kind` 旧位置（architecture §9.7 Q1、§14 R2）。
- **反馈闭环（B6 关闭点，architecture §10.6）**：`ActionResult` 作为反馈统一入口，下游四系统（World / Memory / Relationship / Autonomy / Reflection）按统一契约消费——本任务只交付 `ActionResult` 契约与投递接口，四系统具体接线在 TASK-007。
- 对应 architecture §8.4、§10.6、§14（R2）、§9.7 Q1。

Dependencies: TASK-004

Acceptance Criteria:

- **结果契约断言**：`ActionResult` 含 `id`/`action_id`/`status`/`output`/`error`/`metadata`/`observations`/`created_at` 字段，`model_dump`/`model_validate` 往返一致；`status` 四值（含 `timeout`）。
- **四类结果断言**：成功 / 失败 / 部分完成 / 重试四类各有用例；`partial` 记录已完成 effects 不回滚；`retry` 复用原 `dedupe_key`。
- **统一契约断言**：`CapabilityResult.payload` 旧读键退役后，`ActionResult.output` 承载结构化输出（旧读键双写一个版本窗口后可读）；`ToolResult` / `PlanStepOutcome` 能映射到 `ActionResult`（映射测试）。
- **兼容承诺兑现断言（G9）**：V9 旧读键（`world_event_id` / `memory_id` / `failure_kind` 旧位置）在 Flag on 且全量测试通过后退役；退役窗口 ≥ 一个版本（双写断言）。
- **反馈入口断言**：`ActionResult` 是下游四系统消费的统一入口（`effects` 含 `world`/`memory`/`relationship`/`note` 四种 kind，对齐既有 `ActionEffect`）。
- **幂等断言**：重复投递不产生重复副作用（`has_memory_effect` 泛化 + `dedupe_key`）。
- Flag 全 off 时 `ActionResult` 仍为三值（succeeded/failed/partial），`timeout` 值不启用，行为与 V2.5.0 逐字节一致。

---

## TASK-007 System Integration

Priority: P1

Goal: 连接已有系统：Planning（Plan Step → Action）、World Simulation（ActionResult → World Update）、Relationship Dynamics（Action Behavior → Relationship Change）、Memory（Important Result → Memory）四路接线（architecture §10）。

Description:

- **Planning System 集成（architecture §10.2）**：`PlanExecutorBridge.to_intent`（V2.5.0 既有）产出的 `ActionIntent` → `ActionManager.create(source="plan")` → `ActionManager.execute` → `ActionResult` → `PlanStepOutcome` 映射回计划层。**Planning 只编排、Action 层只执行**（G2）；PlanStep 与 Action 是 1:1 关系，多步由 Planning 层编排。
- **World Simulation 集成（architecture §10.3）**：`ActionResult.effects(kind=world)` → `deferred_world_op` → outbox → `world_engine`（唯一写面）。示例：`send_message` Action → `last_interaction_time` 世界状态更新。**Action 永不直接改世界**（G-WORLD 纪律延续）。
- **Relationship Dynamics 集成（architecture §10.4）**：`ActionResult.effects(kind=relationship)` → `relationship_bridge`（V9 既有二格映射）→ 关系信号。示例：`help_user` Action → `trust +1`。**行为如何影响关系由 `relationship_bridge` 裁决，Action 层只产出关系信号**。
- **Memory System 集成（architecture §10.5）**：区分「临时执行记录」与「长期记忆」——普通执行结果进 `action_records`（执行台账，不落 `memories`）；重要结果（如帮用户记的提醒、重要关怀送达）经 `memory_bridge` + `memory_policy` R1~R8 进候选。**记忆政策 R1~R8 零豁免**。
- **反馈闭环接线（architecture §10.6，B6 关闭点）**：`ActionResult` → 四通道回写（复用既有 `action_engine.integrate_result` 四通道：world/memory/relationship/note）+ 反馈（Autonomy `action_facts`/`tool_facts`、Reflection 执行证据窗、Planning `PlanStepOutcome`）。**不新建机制，全部复用既有通道**。
- **明确不做**：不新建事件总线 / 消息队列（`outbox_events` 已承担）；不让 Action 层直接写 Memory / Character 域（经 `memory_policy` / `world_engine`）；不让 Reflection 直接改写 Action（反思管认知）。
- 对应 architecture §10（§10.1 ~ §10.7）、§5.4（调用关系）。

Dependencies: TASK-004, TASK-006

Acceptance Criteria:

- **Planning 集成断言**：`PlanStep → Action` 接线成立（`to_intent` → `create(source="plan")` → `execute` → `PlanStepOutcome`）；PlanStep 与 Action 1:1；Planning 层零直调 `ActionExecutor`（静态断言，G2）。
- **World 集成断言**：`ActionResult.effects(kind=world)` 经 outbox → `world_engine`（唯一写面）；`send_message` → `last_interaction_time` 更新用例通过；Action 层零直写 `world_engine`（G-WORLD 静态断言）。
- **Relationship 集成断言**：`help_user` → `trust +1` 经 `relationship_bridge`；Action 层零直写 `relationship_*`（静态断言）。
- **Memory 集成断言**：临时执行记录（如查询天气）不落 `memories`；重要结果（如帮记提醒）经 R1~R8 进候选；R1~R8 零豁免。
- **反馈闭环断言**：`ActionResult` 四通道回写（world/memory/relationship/note）+ 三面反馈（Autonomy/Reflection/Planning）全部接线；不新建机制（复用既有 `integrate_result`）。
- **职责不重叠断言**：Planning 只编排 / Action 只执行 / Tool 只动手 / 世界唯一写面 / 记忆唯一政策闸，五者无交叉写面（静态 + 运行时断言）。
- Flag 全 off 时四系统集成全部走既有路径，行为与 V2.5.0 逐字节一致。

---

## TASK-008 API / Interface Layer

Priority: P1

Goal: 提供内部调用接口：Action API / Executor API / Result API 三组接口契约冻结（architecture §12 Observability + §8 模块接口）。

Description:

- **Action API（`ActionManager` 六能力）**：`create` / `update` / `query` / `cancel` / `retry` / `get_status`（TASK-003 交付，本任务冻结签名并做契约对照）。
- **Executor API（`ActionExecutor` 四能力）**：`dispatch` / `run` / `execute_internal` / `execute_tool` / `execute_external`（TASK-004 交付，本任务冻结签名）。
- **Result API（`ActionResult` 契约）**：`ActionResult` 值对象字段契约 + 四类结果处理（TASK-006 交付，本任务冻结）。
- **可观测面（architecture §12）**：
  - 日志：`Action Created / Scheduled / Started / Completed / Failed / Cancelled / Retried` 七个事件，全部落 `loop_runs.steps`（既有可观测通道，不新建）。
  - 指标：执行次数 / 成功率 / 平均耗时 / 重试率 / 取消率，按 `action_type` / `execution_kind` 分组，投影自 `action_records`（不新建指标表）。
- **管理面调试端点**：沿用既有 `app/api/v1/debug.py` 风格（与 V2.3.0 world 面板、V2.4.0 tools 面板同构）扩 Action 清单 / 单 Action 详情（含 steps + result + schedule）/ 调度队列视图（`action_schedules`）/ 执行指标聚合。全部受 `v26_action_execution_enabled` + 调试总闸门控，Flag off 时端点不可见。
- **明确不做**：不暴露对外 REST API（V2.6.0 是内部执行层，外部 API 留给 V2.7.0 Tool Capability）；调试端点不纳入 `apps/frontend/`（Q5 记录，architecture §13 Future Extension）。
- 对应 architecture §8（模块接口）、§12（Observability）、§9.7 Q5。

Dependencies: TASK-003, TASK-004

Acceptance Criteria:

- **契约冻结断言**：三组接口签名与 §8 逐条一致（契约对照）；任何签名漂移即用例失败。
- **日志断言**：七个日志事件（Created/Scheduled/Started/Completed/Failed/Cancelled/Retried）落 `loop_runs.steps`（可观测断言）。
- **指标断言**：五项指标（执行次数/成功率/平均耗时/重试率/取消率）可从 `action_records` 正确投影（聚合查询断言）。
- **调试端点断言**：Action 清单 / 详情 / 调度队列 / 指标四类端点受总闸 + 调试子闸门控；Flag off 时端点不可见。
- **零新建表断言**：可观测面全部投影自 `action_records` / `action_schedules` / `loop_runs` 三张表（不新建指标表）。
- **不暴露外部 API 断言**：无对外 REST 端点（内部执行层定位）。

---

## TASK-009 Testing & Validation

Priority: P0

Goal: 保证系统稳定：Unit Test / Integration Test / Lifecycle Test / Failure Scenario 四类测试 + Flag 矩阵一致性 + 回归清单 + architecture §3.3 六设计原则与 §14 风险的收口。

Description:

- **四类测试集**：
  - **Unit Test**：Action 值对象（TASK-001）、`action_schedules` 仓储（TASK-002）、`ActionManager` 六能力（TASK-003）、`ActionExecutor` 分派（TASK-004）、`ActionScheduler` 纯函数（TASK-005）、`ActionResult` 值对象（TASK-006）。
  - **Integration Test**：Planning → Action → Tool 全链（TASK-007）；World / Relationship / Memory 三路接线（TASK-007）；调度消费链路（TASK-005）。
  - **Lifecycle Test**：`CREATED → PENDING → RUNNING → SUCCESS/FAILED/CANCELLED` 全生命周期 + `FAILED → PENDING`（retry）+ 终态出度 0。
  - **Failure Scenario**：执行失败 / 超时 / 重试达上限 / 幂等重复 / 状态恢复（进程崩溃后孤儿 `RUNNING` 恢复）/ 部分完成。
- **Flag 矩阵一致性测试**：6 个 `v26_*` Flag（`v26_action_execution_enabled` 总闸 + `v26_action_abstraction` / `v26_action_scheduler` / `v26_action_multistep` / `v26_action_result` / `v26_action_feedback` 五子闸）组合矩阵；总闸 off 时逐字节一致（prompt + 行为快照 + 维护步骤序列）。
- **交付 `docs/version/v2.6.0/regression-checklist.md`**。
- **六设计原则收口（architecture §3.2）**：Action 独立抽象 / Planning 不执行 / Executor 不决策 / Tool 是扩展能力 / 所有执行必产 Result / Result 必支持反馈闭环，六条各有可判定条目。
- **风险收口（architecture §14）**：R1 多步状态一致性（部分失败不回滚）、R2 旧读键退役兼容（双写窗口）、R3 调度与执行一致性（`uq_action_schedules_action` + 幂等）、R4 Action 抽象过度设计（字段最小化）、R5 反馈预算竞争（有界）、R6 新表打破零迁移惯例（唯一新表 `action_schedules` 最小必要）逐条核对留痕。
- **遗留问题收口（architecture 附 Q1~Q5）**：Q1 部分失败回滚语义（本版本只记录不回滚）、Q2 cron 语义（留给 V2.7.0）、Q3 反馈预算（压测后决定）、Q4 外部服务超时（留给 V2.7.0）、Q5 Action 抽象与 MCP 对齐（预留映射）逐条核对，无悬空项。
- 对应 architecture §3.2、§14、附遗留问题、§12（Observability）。

Dependencies: TASK-001 ~ TASK-008

Acceptance Criteria:

- **四类测试断言**：Unit / Integration / Lifecycle / Failure 四类全覆盖，且 Lifecycle 测试覆盖六态全迁移 + retry + 终态出度 0。
- **Flag 矩阵断言**：6 个 Flag 组合矩阵逐条对照；总闸 off 时与 V2.5.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）；既有测试零修改通过。
- **六原则断言**：六条设计原则各有可判定条目，且可追溯到 architecture §3.2 原文。
- **风险收口断言**：R1~R6 六条风险各有裁决结论或记录留痕，无悬空项。
- **遗留收口断言**：Q1~Q5 五项遗留问题各有裁决结论，无悬空项。
- **唯一新表断言**：全版本唯一新表 `action_schedules`；`action_records` 唯一加列 `priority`；无其他表/列/索引/CHECK 变更（迁移链 = 既有链头 + 1）。
- **回归清单断言**：`regression-checklist.md` 覆盖六原则 + 六风险 + Flag 矩阵 + 「零新建 Agent / Memory / Session / Event 系统」复用声明。

---

## 4. 里程碑

| 里程碑 | 含任务 | 出口判定 |
|---|---|---|
| **M1 领域地基** | 001, 002 | Action 统一抽象冻结；六态状态机就位；`action_records` 扩展 + `action_schedules` 新表 |
| **M2 执行核心** | 003, 004 | Action 生命周期可管理；三种执行方式可分派；异常与结果捕获 |
| **M3 增强能力** | 005, 006 | 调度统一到 Action 级；ActionResult 统一契约 + 旧读键退役 |
| **M4 系统集成与验收** | 007, 008, 009 | 四系统接线完成；接口契约冻结；全部 Gate 全绿 |

---

## 5. 遗留问题挂载

Architecture「附：遗留问题登记」五项，按任务归属挂载：

| # | 问题 | 挂载任务 | 裁决时点 |
|---|---|---|---|
| Q1 | 单 Action 多步部分失败回滚语义 | TASK-006（记录，本版本只记录不回滚） | 后续版本 |
| Q2 | `action_schedules` 的 `cron` 语义 | TASK-005（简化到「下一次触发时刻」） | 与 V2.7.0 日历工具一并裁决 |
| Q3 | 反馈闭环 `action_facts` 预算上限 | TASK-007（记录，压测后决定） | 后续版本 |
| Q4 | External Service 超时与重试策略 | TASK-004（预留接口，不实现） | 与 V2.7.0 飞书主动行为一并裁决 |
| Q5 | Action 抽象与 MCP / Function Calling 对齐 | TASK-001（预留 `type → ExecutionKind` 映射） | V2.7.0 |

---

## 6. 与 Architecture 的追溯矩阵

Architecture 14 章与本文档 9 任务的对应关系：

| Architecture 章节 | 本文档任务 | 说明 |
|---|---|---|
| §6 Action Model | TASK-001 | Action 统一抽象 + 六态 + 生命周期 |
| §9 Data Model | TASK-002 | `action_records` 复用 + `action_schedules` 新表 + 迁移 |
| §8.1 Action Manager | TASK-003 | 六能力生命周期管理 |
| §8.2 Action Executor | TASK-004 | 三种执行方式 + 异常捕获 + 结果捕获 |
| §8.3 Action Scheduler | TASK-005 | 延迟/定时/优先级/队列 |
| §8.4 Action Result System | TASK-006 | ActionResult 统一契约 + 旧读键退役 |
| §10 Integration | TASK-007 | Planning / World / Relationship / Memory 四路接线 |
| §12 Observability + §8 模块接口 | TASK-008 | 三组接口 + 日志 + 指标 + 调试端点 |
| §3.2 设计原则 + §14 风险 + 附遗留 | TASK-009 | 验收 + Flag 矩阵 + 回归清单 + 收口 |

**无新增任务声明**：本文档未新增任何超出 TASK-001 ~ TASK-009 的编号。§7 Execution Flow（同步/异步/长任务/重试）并入 TASK-004；§13 Future Extension（Tool Adapter 扩展面）作为 TASK-004 的预留接口，不单独成任务。

---

## 7. 边界与复用声明

本版本所有任务**复用既有系统**，任何任务不得违反下列边界（对照 architecture §1.2 既有资产盘点、§3.3 设计原则、§14 风险）：

**复用的既有系统（禁止新建同类系统）**

| 既有系统 | 复用方式 | 禁止事项 |
|---|---|---|
| Action Engine（V9，`run_action_planning` 六闸门 + 退避 + `integrate_result`） | 唯一执行编排器 + 唯一状态迁移入口 | 不新建执行编排器 |
| Action 域模型（`models/action.py` + `action_repository`） | 复用 + 扩展（`Action` 值对象、`priority` 字段） | 不新建 `actions` / `action_results` 表 |
| Tool System（V2.4.0，`ToolExecutor` 五段短路 + `ToolResult`） | 执行期经 Action 编排器 | 不绕过五段短路、不新增工具选择逻辑 |
| Planning（V2.5.0，`PlanExecutorBridge` + `goal_planning`） | 只编排、不执行 | 不新增第二套计划编排 |
| World Simulation（`world_engine` + `outbox` + `event_bridge`） | 唯一写面 + 延迟写 | 不直写世界表 |
| Memory（`memory_policy` R1~R8 + `memory_bridge`） | 重要结果经政策闸 | 不绕过 R1~R8 |
| Relationship（`relationship_bridge`） | 关系信号经既有通道 | 不直写 `relationship_*` |
| Life Loop（`life_loop` 维护步 + `background_jobs` + `loop_runs`） | 挂既有维护步 | 不新建调度循环 / Worker |

**四条硬纪律（逐任务验收红线）**

1. Action 是独立抽象层——不依赖 Goal / Plan / Tool 语义。
2. Planning 不负责执行、Executor 不负责决策——三者职责不重叠。
3. 所有执行必须产生 Result——无结果台账的执行视为缺陷。
4. Flag 全 off 时与 V2.5.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）。

---

## 8. 执行状态台账

> 状态流转：TODO → DOING → DONE（由 Coding Agent 逐任务更新，记录完成内容 / 修改文件 / commit / 测试结果）。

| Task | 状态 | 完成内容 | 修改文件 | commit | 测试结果 |
|---|---|---|---|---|---|
| TASK-001 | DONE | Action 统一抽象 / ExecutionKind 映射 / ActionSource 五值 / 六态语义表 | `app/models/action.py`、`tests/v26/test_task001_action_core_model.py` | b75ce93 | 47 passed |
| TASK-002 | DONE | action_schedules 新表 / priority 加列 / source 五值 CHECK / 5 个 schedule 仓储函数 | `app/models/action.py`、`app/core/db.py`、`app/repositories/action_repository.py`、`migrations/versions/0047_action_schedules_priority.py`、`tests/v26/test_task002_persistence.py` | 7b4ec1e | 14 passed + 既有仓储 6 passed |
| TASK-003 | DONE | ActionManager 六能力 + v26 Flag 设置 | `app/services/action/manager.py`、`app/core/settings/action_execution.py`、`app/core/settings/__init__.py`、`tests/v26/test_task003_manager.py` | 459cd6a | 22 passed |
| TASK-004 | DONE | ActionExecutor 三分派 + 异常归一 + 结果必产 | `app/services/action/executor.py`、`tests/v26/test_task004_executor.py`、`tests/v24/test_tool003_action_engine.py`（冻结断言同步） | 672cf7f | 37 passed |
| TASK-005 | DONE | ActionScheduler 三种 when + 排序/队列 + life_loop 挂载 | `app/services/action/scheduler.py`、`app/application/life_loop.py`、`tests/v26/test_task005_scheduler.py` | 7313858 | 14 passed |
| TASK-006 | DONE | ActionResult 统一契约 + 投影映射 + 旧读键双写 | `app/models/action.py`、`app/services/action/result.py`、`tests/v26/test_task006_result.py` | 531d1cb | 16 passed |
| TASK-007 | DONE | Planning/World/Relationship/Memory 四路接线 + 反馈闭环 | `app/services/action/integration.py`、`tests/v26/test_task007_integration.py` | fea2713 | 9 passed |
| TASK-008 | DONE | 契约冻结 + 4 调试端点 + 事件日志 | `app/api/v1/action_execution.py`、`app/api/v1/router.py`、`app/services/action/contracts.py`、`tests/v26/test_task008_api.py` | b5e53d0 | 7 passed |
| TASK-009 | DONE | 四类验收 + Flag 矩阵 + 六原则/六风险/遗留收口 | `tests/v26/test_task009_validation.py`、`docs/version/v2.6.0/regression-checklist.md` | d7b4088 | 148 v26 passed |
