# TASK-003 Action Manager — Task Detail

> 上游：[../architecture.md](../architecture.md) §8.1、§3.3（G2/G3）、§6.3；[../tasks.md](../tasks.md) TASK-003
> 状态：TODO
> 范围红线：**Action 生命周期的唯一管理者**——`create`/`update`/`query`/`cancel`/`retry`/`get_status` 六能力；不决策（G3）、不编排（G2）、不写世界/记忆/关系；不绕过 `action_engine` 六闸门。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-003 |
| **Task Name** | Action Manager |
| **Priority** | P0 |
| **Dependencies** | TASK-001, TASK-002 |
| **Phase** | Phase 2 执行核心 |
| **建议提交** | `feat: Action Manager 生命周期六能力` |

## 1.1 Goal

实现 Action 生命周期管理的**唯一入口**：`create` / `update` / `query` / `cancel` / `retry` / `get_status` 六能力，内部委托既有 `action_engine` + `action_repository`，作为 Action 的**唯一生命周期管理者**（architecture §8.1）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**生命周期中枢**。TASK-004（Executor）的 `run` 由本任务的 `execute` 委托触发；TASK-007（Integration）的 Planning 接线经本任务的 `create(source="plan")`；TASK-008（API）冻结本任务六能力签名。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-001（Action 值对象）、TASK-002（仓储） | 消费 |
| 被依赖 | TASK-004 / TASK-007 / TASK-008 | 提供生命周期管理 |
| 委托 | 既有 `action_engine` / `action_repository` | 复用，不绕过 |

---

# 2. Background

## 2.1 当前系统现状

`action_engine.run_action_planning`（V9 既有）已是「创建 → 六闸门 → 计划装配 → 执行 → 四通道投递」的完整编排器；`action_repository`（TASK-002 扩展后）已含 16 个仓储函数。但**缺一个统一的生命周期管理入口**：

- `create` 散落在 `planner` / `goal_execution` 多处；
- `cancel` / `retry` / `get_status` 无统一封装；
- 「谁在什么时候创建 / 取消 / 重试一个 Action」无唯一权威。

## 2.2 为什么需要本任务

architecture §8.1 的核心诉求：Action 的生命周期（创建 → 调度 → 执行 → 终态）需要一个**唯一管理者**，避免散落调用导致的状态迁移不一致。同时必须守住三条纪律：

1. `create` 不决策（那是 `decision_pipeline` 的职责，G3）。
2. `create` 不编排（那是 Planning 的职责，G2）。
3. `cancel` / `retry` 不写世界 / 记忆 / 关系（副作用由既有通道处理）。

一句话：**执行编排器有了（action_engine），生命周期管理者还没有（ActionManager）。**

---

# 3. Scope

## 3.1 In Scope

- 新建 `app/services/action/manager.py`（模块级函数形态，对齐 `services/action/*` 惯例）。
- 六能力：`create` / `update` / `query` / `cancel` / `retry` / `get_status`。
- 唯一写面纪律：`cancel` / `retry` 是对「非执行路径」状态变更的补充入口，不绕过 `action_engine` 六闸门。

## 3.2 Out of Scope

- 执行引擎（属 TASK-004）。
- 调度（属 TASK-005）。
- 结果契约（属 TASK-006）。
- 决策 / 编排逻辑（永不纳入 Manager，G2/G3）。

---

# 4. Technical Design

## 4.1 模块设计

```text
app/services/action/manager.py（新增）
├── create(intent | plan_step, *, source) -> Action
├── update(action_id, **fields) -> Action
├── query(action_id | filters) -> Action | list[Action]
├── cancel(action_id, *, reason) -> bool
├── retry(action_id) -> ActionResult | None
└── get_status(action_id) -> ActionStatus
        │ 内部委托
        ▼
app/application/action_engine.py（既有，唯一编排器）
app/repositories/action_repository.py（TASK-002 扩展后）
```

## 4.2 六能力接口定义

### 4.2.1 `create`

| 项 | 值 |
|---|---|
| 输入 | `intent: ActionIntent \| plan_step: PlanStepSpec` + `source: ActionSource` |
| 输出 | `Action`（`status=created`） |
| 逻辑 | 统一抽象构造（type/target/params/priority/dedupe_key）→ 落 `action_records`；`dedupe_key` 复用 `make_dedupe_key` |
| 纪律 | **不决策**（不调 `decision_pipeline`）、**不编排**（不调 `goal_planning`） |

### 4.2.2 `update`

| 项 | 值 |
|---|---|
| 输入 | `action_id` + 受控字段（仅 `status` / `params` / `priority` / `scheduled_at`） |
| 输出 | `Action` |
| 约束 | `id` / `user_id` / `action_type` / `dedupe_key` 不可变 |

### 4.2.3 `query`

| 项 | 值 |
|---|---|
| 输入 | `action_id` 或过滤条件 |
| 输出 | `Action` 或 `list[Action]` |
| 逻辑 | 委托 `get_record` / `list_records` / `list_by_status` |

### 4.2.4 `cancel`

| 项 | 值 |
|---|---|
| 输入 | `action_id` + `reason` |
| 输出 | `bool`（是否成功取消） |
| 约束 | 仅 `created` / `planned` 可取消；`executing` 不可取消（等自然结束，既有 `transition_action` 语义） |
| 副作用 | 落 `gate_reason=reason`，**不写世界/记忆/关系** |

### 4.2.5 `retry`

| 项 | 值 |
|---|---|
| 输入 | `action_id` |
| 输出 | `ActionResult \| None`（不可重试时 `None`） |
| 约束 | 仅 `failed` 可重试；受 `action_retry_max_attempts` 约束；`attempt+1` 回填 |
| 幂等 | 复用原 `dedupe_key`（防重复副作用） |

### 4.2.6 `get_status`

| 项 | 值 |
|---|---|
| 输入 | `action_id` |
| 输出 | `ActionStatus` |
| 逻辑 | 读 `action_records` 当前态 |

## 4.3 状态变化

| 能力 | 状态变化 |
|---|---|
| `create` | `（无）→ created` |
| `cancel` | `created/planned → cancelled` |
| `retry` | `failed → planned`（受 `attempts_exceeded` 约束） |
| `execute`（委托 TASK-004） | `created → planned → executing → 终态` |

## 4.4 异常处理

| 场景 | 处理 |
|---|---|
| `cancel` 对不可取消状态 | 返回 `False`，不改状态 |
| `retry` 对非 `failed` / 达上限 | 返回 `None` |
| 未知 `action_id` | 返回 `None` / 空（`get_status` 返回 `None`） |
| `update` 尝试改不可变字段 | 拒绝（忽略或抛 `ValueError`） |

---

# 5. Implementation Plan

## Step 1 — 建 manager 模块骨架

1. 新建 `app/services/action/manager.py`，声明六能力函数签名 + 文档字符串。

## Step 2 — 实现 create

1. `create`：从 `ActionIntent` / `PlanStepSpec` 构造 `Action`，`dedupe_key = make_dedupe_key(...)`，委托 `action_repository.save_record`（`status=created`）。

## Step 3 — 实现 query / get_status

1. `query` 委托 `get_record` / `list_records` / `list_by_status`；`get_status` 委托 `get_record` 读 `status`。

## Step 4 — 实现 update

1. `update`：受控字段白名单校验 + 委托 `save_record`。

## Step 5 — 实现 cancel

1. `cancel`：校验 `status ∈ {created, planned}` → 委托 `save_record`（`status=cancelled`，`gate_reason=reason`）。

## Step 6 — 实现 retry

1. `retry`：校验 `status=failed` + `attempt < action_retry_max_attempts` → 复用原 `dedupe_key`，`attempt+1`，委托 `save_record`（`status=planned`）。

## Step 7 — 断言用例

1. 六能力断言、唯一入口断言、职责边界断言（G2/G3）、状态约束断言、幂等断言、不写世界断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- 六能力各有可判定用例，签名与 §4.2 一致。
- `ActionManager` 是唯一生命周期入口（静态断言：`manager.py` 外无对 `action_repository.save_record` 状态字段直接写）。

## 6.2 数据正确性

- `create` 同 `dedupe_key` 重复调用受去重闸门约束（无重复副作用）。
- `retry` 复用原 `dedupe_key`（不产生新键）。

## 6.3 异常场景

- `cancel` 对 `executing`/`succeeded`/`failed`/`cancelled` 返回 `False`。
- `retry` 对非 `failed` 返回 `None`；达 `action_retry_max_attempts` 返回 `None`。

## 6.4 职责边界（G2/G3）

- `create` 不调 `decision_pipeline`（不决策）、不调 `goal_planning`（不编排）。
- `cancel` / `retry` 零 `world_engine` / `memory_policy` / `relationship_bridge` 调用（打桩断言）。

## 6.5 与已有系统兼容性

- Flag 全 off 时 `action_engine` 原路径生效，行为与 V2.5.0 逐字节一致。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | `create` | 构造 `Action`，`status=created`，`dedupe_key` 正确 |
| U2 | `update` | 受控字段更新成功；不可变字段被拒 |
| U3 | `query` | 单查/列表/按状态过滤 |
| U4 | `cancel` | 仅 `created/planned` 可取消 |
| U5 | `retry` | 仅 `failed` 可重试，`attempt+1` |
| U6 | `get_status` | 正确读态 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | 唯一入口 | `manager.py` 外无状态字段直接写 |
| I2 | 职责边界 | `create` 不决策不编排（静态） |
| I3 | 不写世界 | `cancel`/`retry` 零世界/记忆/关系调用（打桩） |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 「明天提醒我学习」Action 创建 → 查询 → 取消 | 生命周期可追踪 |
| S2 | 执行失败 → retry → 成功 | `failed → planned → succeeded` |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-001（`Action` 值对象）、TASK-002（仓储）。

## 8.2 后续依赖模块

- TASK-004（Executor 依赖 `execute` 委托）、TASK-007（Integration）、TASK-008（API 冻结签名）。

## 8.3 需要修改的已有代码

- 新增 `app/services/action/manager.py`。
- 既有 `action_engine` / `action_repository` 零改动（只委托）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | Manager 越权做决策/编排 | 架构风险 | G2/G3 静态断言 + 打桩断言 |
| R2 | `cancel`/`retry` 绕过六闸门直写状态 | 架构风险 | 唯一写面纪律（`action_engine` 仍唯一编排器） |
| R3 | `retry` 重复副作用 | 数据风险 | 复用原 `dedupe_key` |
| R4 | 六能力签名漂移 | 技术风险 | TASK-008 契约冻结兜底 |
