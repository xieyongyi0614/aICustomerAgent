# PLAN-001 Task Detail — Goal Model & Lifecycle

> 上游：[../architecture.md](../architecture.md) §3.2（§3.2.1 ~ §3.2.4）、§5.1、§5.4、§7.2；[../tasks.md](../tasks.md) PLAN-001
> 状态：设计稿（未实现）
> 范围红线：**冻结 Goal 域契约为 Planning 的只读消费面 + 单一状态写回面**；零新增字段、零新增状态值、零迁移；不新建第二套 Goal 系统、不新建第二套优先级算法。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-001 |
| **Task Name** | Goal Model & Lifecycle |
| **Priority** | P0 |
| **Dependencies** | 无 |
| **Phase** | Phase 1 规划地基 |
| **建议提交** | `docs: V2.5.0 Goal 域契约冻结与生命周期边界` |

## 1.1 Goal

把 Goal 域散落在 `models/goal.py`、`goal_repository`、`goal_arbitration`、`goal_service`、`goal_observation` 中的**四项契约**收敛为 Planning 的硬边界：

1. **Goal Model**（`GoalRecord` / `GoalPlanRecord` / `SubGoalSpec` + 八个类型域值集）——只读消费，零新增字段。
2. **Goal Lifecycle**（`GOAL_TRANSITIONS` / `goal_transitions` + `goal_repository` 唯一写面）——Planning 只负责「在哪一步调用」。
3. **Goal Priority**（`goal_arbitration.compute_priority` 唯一算法）——Planning 不重算、不引入第二套。
4. **Goal Status**（七态值集与迁移数学）——Planning 不新增状态值，新语义一律经 `failure_reason` 字符串承载。

并把「计划对目标生命周期的介入点」**钉死在三处**，使 Planning 严格成为 **Goal System 的纯只读消费者 + 单一状态写回者**。

## 1.2 Scope

**包含**

- 冻结 `app/models/goal.py` 的模型与值集契约：`GoalRecord` / `GoalPlanRecord` / `SubGoalSpec` 字段集不变；`GoalType`（4）/ `GoalStatus`（7）/ `GoalSource`（3）/ `GoalHorizon`（2）/ `GoalLayer`（3）/ `GoalDomain`（3）/ `GoalPlanStatus`（5）/ `SubGoalStatus`（4）八个 Literal 值集不变。
- 冻结 `GOAL_TRANSITIONS` 与 `goal_transitions(layer, current)` 为唯一迁移权威；冻结 `goal_repository.set_status` / `finish_goal` / `complete_goal` / `fail_goal` / `reactivate_goal` 为唯一写面。
- 冻结 `goal_arbitration.compute_priority(goal, overlay, relationship_params, settings)` 为唯一优先级算法；冻结分层排序由 `goal_arbitration._rank` / `goal_service.select` 的 tier 提升完成。
- 钉死 Planning 的三个生命周期介入点（§4.3 状态机与介入点表）。
- 交付**四条联动不变量**的可判定用例（§10.1）。
- 交付静态断言：`app/services/planning/` 零导入角色优先级资产、零旁路写 `character_goals`。

**不包含（Non-Scope）**

- 任何模型字段新增（`GoalPlanRecord` 4 个新字段与 `SubGoalSpec` 7 个新字段属 **PLAN-002**）。
- 任何 `v25_*` Flag 与参数（属 **PLAN-002**）。
- 计划域运行期值对象（`PlanContext` / `PlanStepOutcome` / `PlanAdvance` / `PlanRevision` 等，属 **PLAN-002**）。
- 计划生成、拆解、调度、执行、观测、修订（属 **PLAN-003 ~ PLAN-005**）。
- `character_goals` 表结构变更（本版本零迁移，见 §7）。
- `failure_reason` 新增取值本身不需要 DDL；本任务只登记取名词表（`plan_exhausted` / `criteria_undecidable`），写入时机由 **PLAN-005** 落地。

## 1.3 本任务解决什么问题

架构 §1.1 与 §1.3 指出的断层中，与本任务直接相关的是两条**越位风险**：

| 风险 | 若不做本任务会怎样 |
|---|---|
| Planning 若不冻结「不重算优先级」，实现期极易在 `PlanScheduler` 里按 `GoalType` tier 重排步骤，产生**第二套优先级**，与 `goal_arbitration.compute_priority` 的裁决结果冲突 |
| Planning 若不冻结「单一写面 + 迁移表守卫」，实现期极易在 `PlanObserver.settle` 里直接 `UPDATE character_goals.status`，绕过 `GOAL_TRANSITIONS`，使「目标已终态但计划仍在跑」成为可能 |

本任务的价值不是写代码，而是**把这两条越位路径在文档与测试层面封死**，让 PLAN-002 ~ PLAN-012 全部有可举证的边界依据（对应 architecture §3.2、§5.4 联动不变量）。

---

# 2. Background

## 2.1 当前系统现状

| 已有能力 | 承载物 | 与 Goal 契约的关系 |
|---|---|---|
| V6 目标选择与生命周期 | `app/services/goal_service.py`（`select` / `review` / `SelectedGoal`） | 产出「哪一个目标本轮生效」 |
| V2.0/V2.1 分层目标 | `app/services/goal_stack.py`（`evaluate_stack` → `GoalStack`）、`app/services/goal_alignment.py`（`score`） | 四层栈排序（`_LAYER_WEIGHT`） |
| V2.1 目标仲裁 | `app/services/goal_arbitration.py`（`compute_priority` / `record_goal_lifecycle` / `check_abandonment` / `_rank`） | 优先级唯一算法 + 归因行 |
| AUT-002/003 规划与观测 | `app/services/goal_planning.py` / `goal_observation.py` / `goal_execution.py` | 已在本契约内运行 |
| V2.4.0 工具系统 | `app/services/tool/*` | 与本任务无直接耦合（工具治理不外溢到 Goal 域） |

**关键事实（已核对真实源码）**

- `app/models/goal.py::GOAL_TRANSITIONS` 为 `dict[str, tuple[str, ...]]`，`active → (completed, failed, abandoned, suspended)`、`suspended → (active, abandoned)`、`failed → (active,)`、其余终态出度为 0；`goal_transitions(layer, current)` 对 `layer is None` 的 v1 行走 `V1_STATUS_TARGETS = ("completed", "expired", "cancelled")`。
- `app/models/goal.py::CRITERION_FACT_SOURCES = ("world", "state", "memory")` 目前为三值（第四值 `"tool"` 属 **PLAN-002**，本任务不改）。
- `app/repositories/goal_repository.py` 已有 `set_status(goal_id, target, arbitration_state=None)` 作为分层目标唯一状态变更入口（迁移表守卫 + 仲裁轨迹原子写入），以及 `finish_goal` / `complete_goal` / `fail_goal` / `reactivate_goal` / `expire_goal` / `cancel_goal`。
- `app/repositories/goal_repository.py` 已有计划面九个函数：`create_plan` / `get_plan` / `list_plans` / `get_latest_plan` / `count_plans` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress` / `list_active_plans`（本任务零改动，PLAN-011 在其上只加三个只读扩展）。
- `app/core/db.py::GoalPlanRow` 的列只有 `id` / `goal_id` / `version` / `status` / `sub_goals` / `rejection_reason` / `created_at` / `updated_at`，另有 `uq_goal_plans_goal_version` / `ck_goal_plans_status`（五值）/ `idx_goal_plans_goal_status`。
- `app/services/goal_observation.py` 已在使用 `REASON_COMPLETED` / `REASON_PERIOD_EXCEEDED` / `REASON_THRESHOLD_EXCEEDED` / `REASON_REPLAN_EXHAUSTED` 四个 `failure_reason` 字符串——**「新语义经 failure_reason 承载」是既有范式，非本版本发明**。

## 2.2 为什么需要本任务

V2.5.0 把 Planning 层插在 Goal 与 Action 之间（architecture §3.1 层图）。插入一层最危险的后果是**权威被稀释**：

- `GoalStatus` 出现了第二个潜在写入者（计划终态结算）；
- 「先做哪个目标」的排序出现了第二个潜在算法（计划步骤顺序）；
- `failure_reason` 出现了新的语义需求（计划耗尽、判据不可判定）。

若不先冻结，PLAN-005 的 `PlanObserver.settle` 与 `PlanScheduler.order` 会在缺少约束的情况下各自发明一套边界。因此本任务作为**全版本第一块地基**（tasks.md §2.1 依赖图根节点），先冻结契约，再让后续 11 个任务在其上生长。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 声明 Goal 四项契约（Model / Lifecycle / Priority / Status）为 Planning 的接口边界 | 契约表（§4.2、§4.3） |
| R2 | 声明 Planning 生命周期介入点（恰好三处）及其调用与约束 | 介入点表（§4.3） |
| R3 | 声明四条联动不变量并给出可判定判据 | 不变量表（§4.4） |
| R4 | 声明 `failure_reason` 的 Planning 侧取名词表（不扩 CHECK） | 词表（§4.5） |
| R5 | 交付零改动断言与静态扫描断言（§10） | 测试指令 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 新增 `GoalPlanRecord` / `SubGoalSpec` 字段 | PLAN-002 |
| N2 | 新增 `PlanContext` / 结果 / 审计值对象 | PLAN-002 |
| N3 | `CRITERION_FACT_SOURCES` 加第四值 `"tool"` | PLAN-002 |
| N4 | `v25_*` Flag 与参数 | PLAN-002 |
| N5 | 计划生成与七道闸 | PLAN-003 |
| N6 | 步骤顺序算法（`PlanScheduler.order`） | PLAN-005 |
| N7 | 终态结算实现（`PlanObserver.settle`） | PLAN-005 |
| N8 | 目标创建 / 暂停 / 恢复的触发逻辑本身 | 既有 `goal_service` / `goal_arbitration`（零改动） |

## 3.3 职责边界一句话

> **Goal System 说「想要什么、谁更重要」；Planning 只说「这件事分几步做」。Planning 对 Goal 只有两个动作：读它，和请求把它转成合法终态。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 模块 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/models/goal.py` | 既有 | **冻结**（零改动） | 被 Planning 只读 |
| `app/repositories/goal_repository.py` | 既有 | **冻结**（既有 9 个计划函数 + 状态写面零改动） | Planning → 唯一写面 |
| `app/services/goal_arbitration.py` | 既有 | **冻结**（`compute_priority` / `record_goal_lifecycle` / `check_abandonment`） | Planning → 只读+调用 |
| `app/services/goal_service.py` | 既有 | **冻结**（`select` / `review`） | Planning 不调用（属 Autonomy/前台侧） |
| `app/services/goal_stack.py` / `goal_alignment.py` | 既有 | **冻结**（四层栈与 `_LAYER_WEIGHT`） | Planning 只读 `GoalStack` |
| `app/services/goal_planning.py` | 既有 | 本任务只冻结其**触发源常量**（`PLANNING_TRIGGERS`） | Planning Engine 包装（PLAN-003） |
| `app/services/goal_observation.py` | 既有 | 本任务只冻结其**终态路径**（`_complete` → `finish_goal`） | PlanObserver 包装（PLAN-005） |

**分层纪律**：本任务不新建任何 Python 模块。PLAN-002 起的 `app/services/planning/` 包对上述模块只允许**只读导入 + 既有写面调用**，禁止直接持有 `GoalRow` / `GoalPlanRow` 或构造 `update()` 语句。

### 4.1.2 Component 划分

```text
Goal System（既有，本任务冻结其对外契约）
├── 声明层  models/goal.py
│     GoalRecord / GoalPlanRecord / SubGoalSpec + 八个类型域 + 判据白名单
├── 约束层  models/goal.py::GOAL_TRANSITIONS / goal_transitions
│     + repositories/goal_repository.py::set_status（迁移表守卫）
├── 排序层  services/goal_arbitration.py::compute_priority（唯一算法）
│     + goal_service.select（tier 提升）+ goal_stack.evaluate_stack（四层）
└── 归因层  services/goal_arbitration.py::record_goal_lifecycle

Planning System（本任务只声明边界，不实现）
    ├── 只读：get_goal / list_children / list_tree / list_active_plans / get_latest_plan
    └── 写：set_status / finish_goal / complete_goal / fail_goal / reactivate_goal
             + 每次终态调 record_goal_lifecycle 一次
```

### 4.1.3 数据流（Planning 视角的 Goal 契约路径）

```text
① 读目标（规划输入）
   goal_repository.get_goal(goal_id) → GoalRecord
   goal_repository.get_latest_plan(goal_id) → GoalPlanRecord | None
        │ 仅当 goal.status == "active" 才进入规划（见 §4.4 不变量 3）
        ▼
② 规划与执行（PLAN-003 ~ PLAN-006）
   产出 GoalPlanRecord + PlanStepSpec[]（落 goal_plans，既有表）
        │
        ▼
③ 结算终态（PLAN-005 PlanObserver.settle）
   goal_repository.finish_goal(goal_id, status, failure_reason)   ← 唯一写面
        ├─ 内部经 GOAL_TRANSITIONS 校验（非法迁移抛 IllegalGoalTransition）
        └─ goal_arbitration.record_goal_lifecycle(...) 落归因行（decision_records）
```

## 4.2 Core Model

### 4.2.1 GoalRecord（既有，零改动）

字段全部来自 `apps/backend/app/models/goal.py::GoalRecord`。

| 字段 | 类型 | 默认 | Planning 用法 |
|---|---|---|---|
| `id` | str | `uuid4` | 计划外键（`goal_plans.goal_id`） |
| `user_id` | str | — | 装配与检索主体 |
| `character_id` | str | `"asuna"` | 透传 |
| `type` | `GoalType` | — | 优先级 tier 与反思分组键（PLAN-010） |
| `description` | str | — | ≤ `GOAL_DESCRIPTION_MAX_LENGTH`(40)；规划 prompt 主体 |
| `priority` | int | 3 | `[GOAL_PRIORITY_MIN=1, GOAL_PRIORITY_MAX=5]`；**只读** |
| `status` | `GoalStatus` | `"active"` | **进规划的唯一门控**（见 §4.4） |
| `horizon` | `GoalHorizon` | `"current"` | 只读 |
| `source` | `GoalSource` | `"policy"` | 只读 |
| `created_turn` / `expires_at_turn` | int / int? | 0 / None | 只读 |
| `created_at` / `updated_at` | datetime | — | 只读；`updated_at` 参与激活期计算 |
| `parent_goal_id` | str? | None | 祖先链装配（PLAN-003） |
| `layer` | `GoalLayer`? | None | 迁移表选择依据（`goal_transitions(layer, current)`） |
| `domain` | `GoalDomain`? | None | 反思映射与顶层唯一性（§4.4 不变量 4） |
| `origin` | str? | None | 含 `"insight"`；PLAN-010 回环标注 |
| `failure_reason` | str? | None | **Planning 新语义唯一承载位**（§4.5） |
| `arbitration_state` | dict? | None | 经 `set_status` 原子写入 |

### 4.2.2 GoalPlanRecord（既有，本任务只声明语义）

| 字段 | 类型 | 本任务语义 | 新增 |
|---|---|---|---|
| `id` | str | 计划主键 | ❌ |
| `goal_id` | str | 所属目标 | ❌ |
| `version` | int ≥ 1 | 版本号；修订即 `version+1` | ❌ |
| `status` | `GoalPlanStatus` | 五态；**不承载「执行中」语义**（由步骤状态承载） | ❌ |
| `sub_goals` | list[`SubGoalSpec`] | 步骤列表 | ❌ |
| `rejection_reason` | str? | 闸门拒绝理由码 | ❌ |
| `created_at` / `updated_at` | datetime | — | ❌ |
| `trigger` / `context_digest` / `revision_of` / `evidence_refs` | — | **不在本任务**，属 PLAN-002 | ✅（PLAN-002） |

### 4.2.3 SubGoalSpec（既有，本任务只声明语义）

| 字段 | 类型 | 本任务语义 | 新增 |
|---|---|---|---|
| `index` | int ≥ 1 | 序号连续（`validate_sub_goals` 强制） | ❌ |
| `description` | str | ≤ 40 字 | ❌ |
| `capability` | str | 裸能力名；保留可追溯（工具绑定见 PLAN-004） | ❌ |
| `params` | dict | 工具参数 | ❌ |
| `criteria` | dict | 判据树（白名单见 §4.2.4） | ❌ |
| `depends_on` | list[int] | 前驱；禁前向引用 | ❌ |
| `parent_index` | int? | 父步；深度 ≤ 2 | ❌ |
| `status` | `SubGoalStatus` | 四态 | ❌ |
| `attempt_count` | int | 计划层业务性尝试计数（语义见 PLAN-005 §双层重试） | ❌ |
| `last_observed_at` / `last_attempt_at` | datetime? | 观测 / 执行时刻 | ❌ |
| `failure_note` | str? | 失败说明 | ❌ |
| `tool_id` / `kind` / `retry_policy` / `on_failure` / `expected_effects` / `observation_keys` / `binding_reason` | — | **不在本任务**，属 PLAN-002 | ✅（PLAN-002） |

### 4.2.4 判据白名单（既有四元组，本任务冻结、不扩值）

| 常量 | 现有取值 | 本任务 |
|---|---|---|
| `CRITERION_TYPES` | `action_succeeded` / `field_equals` / `threshold_reached` / `all_of` / `any_of` | 冻结（5 值） |
| `CRITERION_FACT_SOURCES` | `world` / `state` / `memory` | 冻结（**三值**；第四值 `"tool"` 属 PLAN-002） |
| `CRITERION_METRIC_PATHS` | `tension` / `intimacy` / `mood` / `salient_memory_count` | 冻结（4 值） |
| `CRITERION_OPS` | `>=` / `<=` | 冻结（2 值） |
| `COMPOSITE_CRITERION_TYPES` | `all_of` / `any_of` | 冻结（嵌套仅一层） |

### 4.2.5 八个类型域（冻结，零新增值）

| 类型域 | 取值数 | 取值 |
|---|---|---|
| `GoalType` | 4 | `user_care` / `relationship` / `conversation` / `scene` |
| `GoalStatus` | 7 | `active` / `completed` / `expired` / `cancelled` / `failed` / `suspended` / `abandoned` |
| `GoalSource` | 3 | `definition` / `policy` / `scene` |
| `GoalHorizon` | 2 | `persistent` / `current` |
| `GoalLayer` | 3 | `short_term` / `medium` / `long_term` |
| `GoalDomain` | 3 | `personal` / `relationship` / `world` |
| `GoalPlanStatus` | 5 | `draft` / `validated` / `active` / `rejected` / `superseded` |
| `SubGoalStatus` | 4 | `pending` / `in_progress` / `done` / `failed` |

## 4.3 State Machine

### 4.3.1 GoalStatus 迁移（既有，零改动）

```text
        created ──► active ──completed──► completed
                      │  ──failed────► failed      （终态，出度 0）
                      │  ──abandoned─► abandoned   （终态）
                      │  ──suspended─► suspended
                      ▼
                 suspended ──active────► active（revive）
                           ──abandoned─► abandoned

        failed ──active──► active（单次 replan 成功边，reactivate_goal）

        v1 行（layer is None）：active ──► completed / expired / cancelled
```

迁移表权威：`app/models/goal.py::GOAL_TRANSITIONS` + `goal_transitions(layer, current)`；非法迁移抛 `IllegalGoalTransition`。**本版本不新增任何一条边、不新增任何状态值。**

| 状态 | 语义 | 进 Planning 输入 | Planning 可写 |
|---|---|---|---|
| `active` | 有效目标 | ✅ | ✅（经 `finish_goal` 转终态） |
| `suspended` | 被他目标压制 | ❌（不规划） | ✅（revive 后恢复规划） |
| `completed` / `failed` / `abandoned` / `expired` / `cancelled` | 终态 | ❌ | ❌ |

### 4.3.2 Planning 对生命周期仅三个介入点

| # | 介入点 | 时机 | 调用（既有 API） | 约束 |
|---|---|---|---|---|
| 1 | 目标创建后 | `goal_planning.materialize` 之后 | 既有行为：`enqueue_planning(TRIGGER_CREATED)` | 既有行为不变，不改签名 |
| 2 | 步骤执行被阻塞 | `PlanObserver` 判定不可推进 | `enqueue_planning(TRIGGER_BLOCKED)` | 既有常量，**新增判定来源**（PLAN-005） |
| 3 | 重规划裁决通过 | `PlanRevisionPolicy.should_replan` | `enqueue_planning(TRIGGER_REPLAN)` | 既有常量，**新增 Reflection 触发源**（PLAN-010） |

计划终态**不新增介入点**：全步达成走既有 `goal_observation._complete` → `finish_goal`（PLAN-005 的 `PlanObserver` 只做包装）。

### 4.3.3 触发源常量（冻结）

`app/services/goal_planning.py` 既有三常量，`PLANNING_TRIGGERS` 为三元组：

| 常量 | 值 | 本版本 |
|---|---|---|
| `TRIGGER_CREATED` | `"goal_created"` | 复用，行为不变 |
| `TRIGGER_BLOCKED` | `"goal_blocked"` | 复用，新增判定来源 |
| `TRIGGER_REPLAN` | `"goal_replan"` | 复用，新增 Reflection 触发源 |

**无新增值。** `GoalPlanRecord.trigger`（PLAN-002）取值即此三常量，因此不产生新的枚举域。

### 4.3.4 优先级层级（冻结，唯一算法）

| 层级 | 排序依据 | 权威函数 | 本任务裁决 |
|---|---|---|---|
| 目标间 | `GoalType` tier（`GOAL_TIER`）+ 调制分 | `goal_service.select` / `goal_arbitration.compute_priority` | 唯一算法，Planning 只读结果 |
| 四层栈内 | `_LAYER_WEIGHT`（short_term 1.0 / medium 0.6 / long_term 0.3） | `goal_alignment.score` / `goal_stack.evaluate_stack` | 唯一算法，Planning 只读 `GoalStack` |
| 计划版本间 | `version` 降序（最新有效） | `goal_repository.get_latest_plan` | 复用 |
| **计划步骤间** | **`depends_on` DAG + `index` 升序（结构序）** | **`PlanScheduler.order`（PLAN-005 新增纯函数）** | **不是优先级算法**，Goal priority 只决定「先规划哪个目标」 |

> **评审红线**：计划步骤顺序**不得**按 `GoalType` tier 或 `goal.priority` 重排。高 tier 目标的后继步骤不越过其前驱。
> 结构序常量：`GOAL_TIER = {"scene": 0, "user_care": 1, "relationship": 2, "conversation": 3}`——只用于**目标**排序，不参与步骤排序。

## 4.4 四条联动不变量（评审红线，逐条可判定）

| # | 不变量 | 判定方式 | 违反后的表现 |
|---|---|---|---|
| I1 | 计划状态**不得**单独改写 `GoalStatus`——必须经 `goal_repository.set_status` / `finish_goal` 且符合 `GOAL_TRANSITIONS` | 静态：`services/planning/` 零 `UPDATE` 语句 / 零直构 `GoalRow`；运行时：非法迁移抛 `IllegalGoalTransition` | 目标处于 `completed` 但计划仍 `active` |
| I2 | `GoalStatus` 终态时，其 active 计划**必须**同时进终态（`superseded`）或被标记冻结，不得留下「目标已终、计划仍在跑」的悬空态 | 用例：目标转终态后 `get_latest_plan(goal_id).status != "active"` | 计划在目标终态后继续产生步骤执行 |
| I3 | 同一 `goal_id` 同一时刻**最多一个** `active` 计划 | 由 `get_latest_plan` + `set_plan_status` 保证；用例断言计数 ≤ 1 | 两个版本同时被调度，幂等键冲突 |
| I4 | 同一 `(layer, domain)` 顶层 `active` 目标 ≤ 1 | 既有 `GoalArbitrationRule`（`services/evaluation_rules/goal.py::GoalArbitrationRule`）强制；本任务只引用不重写 | 仲裁评估规则告警 |

## 4.5 `failure_reason` 取名词表（Planning 侧，不扩 CHECK）

**约束**：`GoalStatus` 的新增语义一律通过 `failure_reason` **字符串**承载——这是既有范式（`REASON_COMPLETED="goal_completed"`、`REASON_PERIOD_EXCEEDED="exec_period_exceeded"`、`REASON_THRESHOLD_EXCEEDED="subgoal_threshold_exceeded"`、`REASON_REPLAN_EXHAUSTED="replan_exhausted"` 均已在用）。

| 词条 | 含义 | 触发者 | 落点 |
|---|---|---|---|
| `plan_exhausted` | 计划达修订预算仍不可行 | PLAN-005 `PlanRevisionPolicy` | `character_goals.failure_reason`（String 列，无 CHECK） |
| `criteria_undecidable` | 判据连续不可判定，重规划亦无改善 | PLAN-005 | 同上 |

**不新增列、不扩 CHECK**：`app/core/db.py::GoalRow.failure_reason` 是 `String` 可空列，无需 DDL。

## 4.6 计划被拒时的目标状态（既有语义确认）

| 计划结果 | `GoalPlanStatus` | `GoalStatus` | 依据 |
|---|---|---|---|
| 任一闸门拒绝 | `rejected` | **不变**（仍 `active`） | 「尚无有效计划」不等于「目标失败」 |
| 全部步骤达成 | `completed` | `completed` | `goal_observation._complete` 既有路径 |
| 全步失败且达放弃阈值 | `rejected` + `rejection_reason` | `failed`（`failure_reason="plan_exhausted"`） | 经 `finish_goal` |
| 被判「不值得继续」 | — | `abandoned` | `goal_arbitration.check_abandonment` 双信号 |

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 |
|---|---|
| 谁决定「此刻做什么」 | `autonomy_policy.evaluate` + `decision_pipeline`（既有，**本任务不涉及**） |
| 本任务的角色 | 只确认：Autonomy 消费的 `GoalStack` / `SelectedGoal` 出自本任务冻结的排序层，Planning 不改其数学 |
| `plan_facts` | 属 **PLAN-007**，本任务不涉及 |

**为什么不涉及**：本任务只冻结 Goal 契约，不接入自治侧任何接线（`PolicySnapshot` 改造与候选面复用均属 PLAN-007）。

## 5.2 与 Tool System

**本任务不涉及。** 原因：Goal 契约与工具治理正交——`GoalRecord` / `SubGoalSpec` 的既有字段不含任何工具语义，工具绑定（`tool_id`）的引入与校验属 PLAN-002（字段）与 PLAN-004 / PLAN-006（绑定与治理闸）。

## 5.3 与 World Simulation

| 关注点 | 关系 |
|---|---|
| 世界事实 | 属 **PLAN-008**（进 `PlanContext`）与 **PLAN-002**（`PlanContext` 字段） |
| 计划本体是否影响世界 | 本任务确认：`GOAL_TRANSITIONS` 与世界四表**无耦合**，目标终态不直写世界 |

**为什么不涉及**：`character_goals` 与 `worlds` / `world_entities` / `world_events` 分属 Character 域与世界域（architecture §7.4 边界表），本任务只冻结 Character 域内状态机。

## 5.4 与 Memory

**不涉及读写通道**，仅确认一条既有事实：`memory2.ingest.ingest_from_goal_completion(user_id, goal_id, description)` 已存在，其 `source` 取自目标本身——PLAN-009 将复用它构造计划终态候选，本任务不改 `memory_policy` R1~R8。

## 5.5 与 Reflection

**不涉及。** 原因：计划证据窗（`EVIDENCE_CHANNEL_PLAN`）与 `PlanningRevisionListener` 属 PLAN-010；本任务只确认 `goal_planning.enqueue_planning(TRIGGER_REPLAN)` 是**既有 API**，PLAN-010 只是给它接一个新触发源。

## 5.6 与既有 Goal 模块（本任务的核心交互面）

| 既有设施 | 本任务的关系 | 是否改动 |
|---|---|---|
| `models/goal.py`（模型 + 值集 + 迁移表 + 判据白名单） | 冻结为契约 | ❌ 零改动 |
| `repositories/goal_repository.py`（状态写面 + 计划面九函数） | 冻结为唯一写面 | ❌ 零改动 |
| `services/goal_arbitration.py`（`compute_priority` / `record_goal_lifecycle` / `check_abandonment`） | 冻结为唯一算法与归因入口 | ❌ 零改动 |
| `services/goal_service.py` / `goal_stack.py` / `goal_alignment.py` | 冻结排序层 | ❌ 零改动 |
| `services/evaluation_rules/goal.py`（六条规则，含 `GoalArbitrationRule` / `GoalPlanningBudgetRule`） | 引用为不变量 I4 的强制者 | ❌ 零改动 |
| `services/goal_planning.py::PLANNING_TRIGGERS` | 冻结触发源常量集 | ❌ 零改动 |

---

# 6. API / Interface Design

本任务的「接口」是**契约声明**，非新增函数。下表即为该契约的可核对形态。

## 6.1 只读消费面（Planning 允许调用的读接口）

| 接口 | 返回 | 用途 | 异常 |
|---|---|---|---|
| `goal_repository.get_goal(goal_id)` | `GoalRecord \| None` | 规划主体（唯一硬依赖） | — |
| `goal_repository.list_children(goal_id)` | `list[GoalRecord]` | 祖先/子目标链 | — |
| `goal_repository.list_tree(user_id, root_goal_id)` | `list[dict]` | 层级视图 | — |
| `goal_repository.get_latest_plan(goal_id)` | `GoalPlanRecord \| None` | 当前生效计划 | — |
| `goal_repository.list_plans(goal_id)` | `list[GoalPlanRecord]` | 版本链 | — |
| `goal_repository.count_plans(goal_id)` | `int` | 修订预算判定 | — |
| `goal_repository.list_active_plans(user_id)` | `list[tuple[GoalRecord, GoalPlanRecord]]` | 推进候选集 | — |
| `goal_arbitration.compute_priority(goal, overlay, relationship_params, settings)` | 分数 | **只读**，Planning 不重算 | — |
| `goal_stack.evaluate_stack(...)` | `GoalStack` | 四层栈 | — |
| `goal_transitions(layer, current)` | `tuple[str, ...]` | 合法迁移目标查询（诊断用） | — |

## 6.2 写回面（Planning 允许调用的写接口，共 5 个）

| 接口 | 参数 | 返回 | 异常 |
|---|---|---|---|
| `goal_repository.set_status(goal_id, target, arbitration_state=None)` | 目标 id / 目标状态 / 仲裁快照 | `GoalRecord \| None` | 非法迁移 → 抛（内部经 `goal_transitions` 守卫） |
| `goal_repository.finish_goal(goal_id, status, failure_reason=None, arbitration_state=None)` | — | `GoalRecord \| None` | 同上 |
| `goal_repository.complete_goal(goal_id)` | — | `GoalRecord \| None` | 同上 |
| `goal_repository.fail_goal(goal_id, failure_reason)` | — | `GoalRecord \| None` | 同上 |
| `goal_repository.reactivate_goal(goal_id)` | — | `GoalRecord \| None` | `failed → active` 单边 |

## 6.3 归因面（每次计划终态调一次）

| 接口 | 参数 | 返回 | 约束 |
|---|---|---|---|
| `goal_arbitration.record_goal_lifecycle(record, decision, reason, snapshot)` | 目标记录 / 决策名 / 理由 / 快照 | 无 | 写 `decision_records`，复用既有 `DecisionKind.GOAL_LIFECYCLE`；**不新增 kind** |

## 6.4 触发面（三常量，`PLANNING_TRIGGERS` 无新值）

| 接口 | 参数 | 返回 | 异常 |
|---|---|---|---|
| `goal_planning.enqueue_planning(user_id, goal_id, trigger)` | trigger ∈ `PLANNING_TRIGGERS` | `bool`（是否新入队） | 未知 trigger → 视为编程缺陷（既有行为） |
| `goal_planning.plan_goal(goal_id, trigger, world_facts=None)` | — | `dict` | — |

## 6.5 异常契约

| 异常 | 来源 | Planning 的处置 |
|---|---|---|
| `IllegalGoalTransition` | `models/goal.py` | **不吞**：向上暴露为计划终态结算失败（PLAN-005 记录审计，不改状态） |
| `ValueError`（`validate_sub_goals` / `validate_criteria`） | `models/goal.py` | 规划期转为 `rejected` + `rejection_reason="invalid_sub_goal_shape"`（PLAN-003），不抛给调用方 |
| 迁移必然失败（终态 → 任何态） | `goal_transitions` 返回空元组 | 视为业务结果（前置已终态），不重试 |

---

# 7. Database Design

**本任务无任何数据库变更。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | architecture §2.3 红线 1：计划/步骤/审计/证据全部落在 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表 |
| 新列 | 无 | `GoalRecord` 的 20 个字段与 `GoalPlanRow` 的 8 个列已覆盖本任务全部语义；`failure_reason` 是既有 `String` 可空列，新词条无需 DDL |
| 改 CHECK | 无 | `GoalStatus` 不新增值 → `ck_character_goals_status` 不变；`ck_goal_plans_status`（五值）不变；`ck_decision_records_kind`（五值）不变 |
| 新索引 | 无 | 既有 `idx_goal_plans_goal_status` / `uq_goal_plans_goal_version` 覆盖计划查询面 |
| 迁移 | 无 | 迁移链保持 **0046**（`apps/backend/migrations/versions/0046_tool_insight_types.py` 为当前链头） |

**落点裁决（本任务声明，后续任务遵守）**

| 数据 | 落点 | 是否新列 |
|---|---|---|
| 目标本体与状态 | `character_goals`（既有全部列） | ❌ |
| 计划本体 + 步骤 | `goal_plans.sub_goals`（既有 JSON） | ❌ |
| 计划状态 / 拒绝理由 | `goal_plans.status` / `goal_plans.rejection_reason` | ❌ |
| 终态归因行 | `decision_records`（`kind='goal_lifecycle'` + 差异化 `decision`） | ❌（复用既有 CHECK 值） |
| 计划终态语义字符串 | `character_goals.failure_reason`（String） | ❌ |

> **零迁移是本任务的强断言**：若实现期出现「为 Planning 加一张计划表 / 给 `character_goals` 加一列」的需求，说明本契约已被违背，必须回退重审 architecture §3.1 与 §4.1 两条裁决并留痕（对应 architecture §4.9、§9.6 G-ZERO-MIGRATION）。

---

# 8. Implementation Plan

> 本任务为**契约冻结与验证**任务，不含功能代码。交付物为「约束声明 + 可判定断言」。

## Step 1 — 契约冻结（文档与声明层）

1. 在 `app/services/planning/` 包（PLAN-002 建立）内声明 Goal 契约模块文档字符串：允许的读接口、允许的 5 个写接口、禁止事项。**不新增函数**。
2. 把三个生命周期介入点写成模块级常量注释（介入点名称 → 既有 `PLANNING_TRIGGERS` 常量），使「介入点只有三处」在代码中可 grep。
3. 登记 `failure_reason` 词表为模块级常量（`plan_exhausted` / `criteria_undecidable`），**不写入 DB、不加 CHECK**。

## Step 2 — 差量对照（零改动证明）

1. 对 `models/goal.py` 生成契约快照（八个值集 + `GOAL_TRANSITIONS` + `LAYER_DEPTH` + `GOAL_TIER` + `GOAL_ORIGINS` + 判据白名单四元组），与 V2.4.0 状态逐条对照，差异必须为空。
2. 对 `repositories/goal_repository.py` 的计划面九函数与状态写面五函数生成签名快照（函数名 + 参数名 + 参数默认值 + 返回注解），差异必须为空。

## Step 3 — 静态扫描断言

1. 断言 `app/services/planning/` 零导入角色优先级资产：零 `from app.character.asuna.goals import` 中的 tier 权重常量、零重复实现 `GOAL_TIER` 排序。
2. 断言 `app/services/planning/` 零直构 `GoalRow` / 零直接 `session.execute(update(...))` 写 `character_goals`。
3. 断言 `app/services/planning/` 对 `goal_repository` 的调用名集合 ⊆ §6.1 ∪ §6.2 白名单。

## Step 4 — 联动不变量用例

1. I1：构造「计划 `rejected`」与「计划 `superseded`」两种场景，断言 `GoalStatus` 未变。
2. I2：构造目标转终态场景，断言其最新计划不再 `active`。
3. I3：对同一 `goal_id` 连续创建两个版本，断言 `active` 计划数 ≤ 1。
4. I4：对同一 `(layer, domain)` 创建第二个顶层 `active` 目标，断言 `GoalArbitrationRule` 报告违规（既有规则，本任务只引用）。

## Step 5 — 结构序用例（优先级 vs 结构序）

1. 构造一个高 `GoalType` tier 的目标，其计划含「step 2 `depends_on=[1]`」且 step 1 未完成。
2. 断言 `PlanScheduler.order`（PLAN-005）返回的序中 step 2 不越过 step 1——**结构序优先于目标优先级**。
3. 反例守卫：断言 Planning 侧不存在按 `goal.priority` / `GOAL_TIER` 对步骤排序的代码路径（静态）。

## Step 6 — Flag 全 off 回归

1. 全量既有 Goal 域测试（`goal_service` / `goal_arbitration` / `goal_stack` / `goal_planning` / `goal_observation` / `goal_execution`）**零修改通过**。
2. Prompt 快照对照：本任务不得引入任何 prompt 差异（零 prompt 影响即为正确）。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 八个类型域值集快照 | 与 §4.2.5 逐条一致，取值数与取值全等 |
| U2 | `GOAL_TRANSITIONS` 全枚举（状态 × 目标态） | 与 §4.3.1 逐条一致；终态出度 0；`failed → active` 唯一 |
| U3 | `goal_transitions(layer, current)` 分层与 v1 分支 | `layer=None` 走 `V1_STATUS_TARGETS`；分层走 `GOAL_TRANSITIONS` |
| U4 | `IllegalGoalTransition` 触发条件 | 终态 → 任何态、反向边（如 `completed → active`）均抛 |
| U5 | 判据白名单四元组 | 5 / 3 / 4 / 2 值；组合判据嵌套仅一层 |
| U6 | `failure_reason` 词表常量 | 两词条存在；`GoalRow.failure_reason` 无 CHECK 约束（结构性断言） |
| U7 | `PLANNING_TRIGGERS` | 恰三值，与 §4.3.3 一致 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | 计划 `rejected` 后读目标 | `goal.status == "active"`（计划被拒不改目标） |
| I2 | 计划全步 `done` → `goal_observation._complete` | `goal.status == "completed"`，且 `decision_records` 有 `kind='goal_lifecycle'` 行 |
| I3 | 达修订预算 → `finish_goal(failed, "plan_exhausted")` | `goal.status == "failed"` 且 `failure_reason == "plan_exhausted"`；未扩 CHECK 仍写成功 |
| I4 | 目标转终态后最新计划状态 | 不再为 `active`（I2 不变量） |
| I5 | 同 `goal_id` 双版本 | `active` 计划数 ≤ 1 |
| I6 | 优先级调用点唯一性 | 全仓 `compute_priority` 调用方不含 `services/planning/`（静态） |
| I7 | 写面唯一性 | 运行时打桩：`services/planning/` 触达 `character_goals` 的写操作只经 §6.2 五个函数 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | 「帮我准备后天的面试」全链契约视角 | 目标成熟（`active`）→ 规划 → 计划 `validated`→`active` → 4 步全 `done` → 终态 | `goal.status` 从 `active` 直达 `completed`，中间无任何非法迁移；归因行 1 条 |
| S2 | 计划不可行终止 | 目标 `active` → 计划 3 个版本均 `rejected` → 达 `v25_plan_revision_budget` | 计划终态 `rejected`；目标 `failed` 且 `failure_reason="plan_exhausted"` |
| S3 | 目标被 suspend 时计划冻结 | 目标 `suspended` | 计划不被调度推进（`PlanScheduler` 无可执行步），计划状态不被单独改写 |
| S4 | 结构序 vs 优先级 | 高 tier 目标 + 依赖链计划 | 后继步骤不越过前驱 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- **契约零改动断言（差异对照为空）**：`GoalType` / `GoalStatus` / `GoalSource` / `GoalHorizon` / `GoalLayer` / `GoalDomain` / `GoalPlanStatus` / `SubGoalStatus` 八个值集；`GOAL_TRANSITIONS` / `goal_transitions` / `V1_STATUS_TARGETS` / `LAYER_DEPTH` / `LAYER_VALUES` / `DOMAIN_VALUES` / `PLAN_STATUS_VALUES` / `SUB_GOAL_STATUS_VALUES` / `GOAL_TIER` / `GOAL_ORIGINS` / `CRITERION_TYPES` / `CRITERION_FACT_SOURCES` / `CRITERION_METRIC_PATHS` / `CRITERION_OPS` / `COMPOSITE_CRITERION_TYPES` / `GOAL_DESCRIPTION_MAX_LENGTH` / `GOAL_PRIORITY_MIN` / `GOAL_PRIORITY_MAX` 全部零变化。
- **`character_goals` 表结构与既有列语义未动**：`GoalRow` 列集与 CHECK 名未变。
- **单一写面断言**：Planning 路径对 `character_goals` 的写入只经 `goal_repository.set_status` / `finish_goal` / `complete_goal` / `fail_goal` / `reactivate_goal`，零旁路（静态与运行时断言）。
- **不重算优先级断言**：优先级计算调用点唯一（`goal_arbitration.compute_priority`）；`app/services/planning/` 零导入角色优先级资产（静态）。
- 计划步骤顺序按 `depends_on` DAG + `index` 升序排列；用例：高 `GoalType` tier 目标的后继步骤不越过其前驱（结构序优先于优先级）。
- 计划被拒时目标仍为 `active`；计划全步达成时目标为 `completed`；计划全步失败且达放弃阈值时目标为 `failed` 且 `failure_reason="plan_exhausted"`；计划被判不值得继续时经 `goal_arbitration.check_abandonment` 双信号转 `abandoned`。
- 四条联动不变量各有可判定用例，含「目标已终态不得留下仍在推进的计划」与「同一 `goal_id` 同时刻最多一个 active 计划」。
- 计划触发入队只用既有三个 `PLANNING_TRIGGERS` 常量，无新增值（快照断言）。
- Planning 介入点恰三处，逐一可 grep 到调用点，无第四处。

## 10.2 Integration Acceptance

- Flag 全 off 时既有 Goal 域全量测试**零修改通过**（`goal_service` / `goal_arbitration` / `goal_stack` / `goal_alignment` / `goal_planning` / `goal_observation` / `goal_execution` / `evaluation_rules/goal`）。
- `app/services/evaluation_rules/goal.py` 六条规则（`GoalConsistencyRule` / `GoalSemanticRule` / `GoalArbitrationRule` / `GoalPlanningBudgetRule` / `GoalExecutionCapRule` / `GoalSupplyMalformedRule`）在契约冻结后零失败。
- 计划面九个既有函数（`create_plan` / `get_plan` / `list_plans` / `get_latest_plan` / `count_plans` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress` / `list_active_plans`）签名与行为零改动（差异对照为空）。
- `decision_records.kind` 仍为五值（`proactive_autonomy` / `turn_goal` / `turn_intention` / `turn_behavior` / `goal_lifecycle`），未新增 CHECK 值。
- 本任务不引入任何 prompt 差异（prompt 快照对照零差异）。

## 10.3 Quality Acceptance

- **零迁移**：无新表、无新列、无新索引、无新 CHECK 值；迁移链头仍为 `0046`。
- **无代码骨架污染**：本任务不在 `app/services/planning/` 引入任何业务逻辑实现（该包的实现自 PLAN-002 / PLAN-003 起）。
- **可举证**：每条不变量（I1~I4）与每个介入点均可指向具体调用点或断言用例，无「口头约定」项。
- **文档一致**：本文件与 architecture §3.2 / §5.1 / §5.4 / §7.2、tasks.md PLAN-001 Acceptance Criteria 逐条对应，无自相矛盾。
- 静态断言：`app/services/planning/` 对 `goal_repository` 的调用名集合 ⊆ §6.1 ∪ §6.2 白名单（新增调用即失败）。
