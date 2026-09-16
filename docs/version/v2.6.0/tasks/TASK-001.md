# TASK-001 Action Core Model — Task Detail

> 上游：[../architecture.md](../architecture.md) §6（§6.1 ~ §6.4）、§3.1（G1）；[../tasks.md](../tasks.md) TASK-001
> 状态：TODO
> 范围红线：**冻结 Action 域为独立抽象层**——统一 `Action` 值对象（六问可答）、`ActionType → ExecutionKind` 映射、六态状态机语义强化；零新增状态值、零新增 ActionType 值、零迁移；不新建模型模块、不落库 `Action` 值对象。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-001 |
| **Task Name** | Action Core Model |
| **Priority** | P0 |
| **Dependencies** | 无 |
| **Phase** | Phase 1 领域地基 |
| **建议提交** | `feat: Action 统一抽象与六态状态机冻结` |

## 1.1 Goal

把散落在 `ActionIntent`（决策产物）/ `ActionRecord`（台账）/ `ActionStep`（执行步骤）三处的字段，收敛为一个可回答「是什么（type）/ 做什么（target + parameters）/ 什么状态（status）/ 什么结果（result）/ 什么时候创建（created_at）/ 什么时候执行（scheduled_at / executed_at）」**六问**的统一 `Action` 值对象；并建立 `ActionType → ExecutionKind` 映射与六态状态机语义强化，使 Action 成为**独立于 Goal / Plan / Tool 语义的抽象层**（architecture §6、§3.1 G1）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是全版本**第一块地基**（tasks.md §2.1 依赖图根节点）。后续 8 个任务全部在 `Action` 值对象、`ACTION_EXECUTION_MAP` 映射、六态状态机之上生长：

- TASK-002（Persistence）依赖本任务的 `Action` 字段集与六态；
- TASK-003（Manager）依赖本任务的生命周期定义；
- TASK-004（Executor）依赖本任务的 `ACTION_EXECUTION_MAP` 分派；
- TASK-006（Result）依赖本任务的结果字段。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 被依赖 | TASK-002 ~ TASK-006 | 消费 `Action` 值对象 / 映射 / 状态机 |
| 只读消费 | 既有 `models/action.py` | 复用并强化，不新建模型模块 |
| 不依赖 | Goal / Plan / Tool | Action 抽象独立于三者语义（G1） |

---

# 2. Background

## 2.1 当前系统现状

`app/models/action.py`（V9 既有）已含：

| 既有资产 | 现状 | 本任务动作 |
|---|---|---|
| `ActionType`（9 值）/ `ACTION_TYPES` | `create_reminder` / `cancel_reminder` / `remember_fact` / `create_object` / `move_object` / `use_object` / `query_environment` / `query_search` / `send_notification` | 冻结（零新增值） |
| `ActionStatus`（6 值）/ `ACTION_STATUSES` / `TERMINAL_STATUSES` | `created` / `planned` / `executing` / `succeeded` / `failed` / `cancelled` | 冻结（零新增值） |
| `GateReason`（10 值）/ `FailureKind`（4 值） | 既有 | 冻结 |
| `transition_action`（六态迁移纯函数）+ `_TRANSITIONS` | 非法迁移返回 `None` | 冻结（零行为变更） |
| `ActionIntent` | `action_type` / `confidence` / `params` / `missing_params` / `evidence` / `dedupe_key` / `trigger_source` | 决策产物，保留 |
| `ActionRecord` | 已含 `id` / `user_id` / `action_type` / `intent` / `params` / `status` / `gate_reason` / `steps` / `result` / `attempt` / `next_retry_at` / `scheduled_at` / `executed_at` / `dedupe_key` / `source` / `goal_id` | 台账，保留 |
| `ActionResult` | `status`（succeeded/failed/partial）/ `effects` / `error` / `failure_kind` | 结果值对象，保留（强化属 TASK-006） |

**关键事实**：`ActionRecord` 已有 `scheduled_at` / `executed_at` 字段；`ActionSource` 为 `Literal["conversation", "autonomy", "cancel"]` 三值——**缺 `plan` / `event_driven` 两个来源，缺 `priority` 字段**（后者属 TASK-002 加列）。

## 2.2 为什么需要本任务

前九个版本把"执行"分散在三个概念里：`ActionIntent`（决策层想做什么）、`ActionRecord`（台账记了什么）、`ActionStep`（执行层怎么做）。三者字段重叠却不统一，导致：

1. **无法回答"一个 Action 的完整生命周期是什么"**——六态散落，无统一语义对照。
2. **执行方式与 Action Type 无映射**——`send_notification`（外部）与 `query_environment`（工具）走同一条无差别路径（architecture §2.1 B1 断层）。
3. **来源缺失**——计划驱动的 Action 与事件驱动的 Action 无法在 `source` 上区分。

一句话：**角色有动作（ActionRecord）、有意图（ActionIntent）、有步骤（ActionStep），但没有一个统一的"Action"作为独立抽象层。**

---

# 3. Scope

## 3.1 In Scope

- 新增 `Action` 值对象（运行期，不落库）：收敛 `ActionIntent` / `ActionRecord` / `ActionStep` 三处字段为六问可答的统一抽象（architecture §6.1）。
- 新增 `ExecutionKind = Literal["internal", "tool", "external"]`。
- 新增 `ACTION_EXECUTION_MAP`（角色资产层纯数据）：九个 `ActionType` → `ExecutionKind` 全覆盖映射（architecture §6.2）。
- 扩展 `ActionSource` 为五值：既有 `conversation` / `autonomy` / `cancel` + 新增 `plan` / `event_driven`。
- 六态状态机语义强化：补「语义对照表」与「`failed → planned`（retry）唯一终态回退边」说明（architecture §6.4）。
- 交付零改动断言 + 模型层纯值对象断言 + 状态机纯函数断言（§6）。

## 3.2 Out of Scope

- `priority` 字段加列（属 TASK-002 Persistence）。
- `ActionResult` 字段强化（`id`/`output`/`metadata`/`observations`/`created_at`，属 TASK-006）。
- 具体执行方式实现（Internal/Tool/External，属 TASK-004）。
- 调度（属 TASK-005）。
- 任何 DDL / 迁移 / 落库（本任务纯值对象层）。
- 新增 `ActionStatus` 值（六态已完备）、新增 `ActionType` 值（九能力已完备）。

---

# 4. Technical Design

## 4.1 模块设计

| 模块 | 性质 | 本任务关系 | 依赖方向 |
|---|---|---|---|
| `app/models/action.py` | 既有 | **强化**（新增 `Action` / `ExecutionKind` / `ACTION_EXECUTION_MAP`，扩展 `ActionSource`） | 被 Planning / Action 层只读 |
| `app/character/asuna/action.py` | 既有（角色资产） | `ACTION_EXECUTION_MAP` 放此处或 `models/action.py`（实现期裁决，纯数据无 IO） | 被 Executor 只读 |

**分层纪律**：本任务不新建 Python 模块，只在既有 `models/action.py` 上做**值对象强化**；`Action` 值对象零 `app.repositories` / `app.application` / `app.services` 依赖（同 `models/action.py` 既有纪律）。

## 4.2 Action 值对象字段（架构 §6.1）

| 字段 | 类型 | 必填 | 来源 | 说明 |
|---|---|---|---|---|
| `id` | str | ✅ | uuid | 唯一 id |
| `type` | `ActionType` | ✅ | 冻结 9 值 | 动作类型 |
| `target` | str \| None | ⭕ | — | 动作目标（user_id / object_id / channel） |
| `parameters` | dict | ⭕ | 规范化后 | 动作参数 |
| `priority` | int | ⭕ | 默认 100 | 调度排序用（落库字段属 TASK-002） |
| `status` | `ActionStatus` | ✅ | 默认 `created` | 生命周期状态 |
| `result` | `ActionResult` \| None | ⭕ | 终态必填 | 结果 |
| `created_at` | datetime | ⭕ | — | 创建时刻 |
| `scheduled_at` | datetime \| None | ⭕ | — | 计划执行时刻 |
| `executed_at` | datetime \| None | ⭕ | — | 实际执行时刻 |
| `source` | `ActionSource` | ⭕ | 默认 `conversation` | 来源（五值） |
| `goal_id` | str \| None | ⭕ | — | 关联目标 |
| `plan_step` | str \| None | ⭕ | — | 关联计划步骤 |
| `dedupe_key` | str | ⭕ | `make_dedupe_key` | 幂等键 |
| `run_id` | str \| None | ⭕ | — | 所属 Run |

## 4.3 ActionType → ExecutionKind 映射（架构 §6.2）

```text
ACTION_EXECUTION_MAP = {
    "create_reminder":    "internal",
    "cancel_reminder":    "internal",
    "remember_fact":      "internal",
    "create_object":      "internal",
    "move_object":        "internal",
    "use_object":         "internal",
    "query_environment":  "tool",
    "query_search":       "tool",
    "send_notification":  "external",   # 经 Tool Adapter（预留，TASK-004）
}
```

**扩展点**：新增 Action Type = 在 `ACTION_EXECUTION_MAP` 加一行 + 注册对应执行方式，不改 `Action` 抽象、不改 Executor。

## 4.4 ActionSource 扩展

```text
ActionSource = Literal["conversation", "autonomy", "cancel", "plan", "event_driven"]
```

- 既有三值语义不变：`conversation`（前台对话）、`autonomy`（后台自治）、`cancel`（取消）。
- 新增：`plan`（计划驱动，V2.5.0 PlanExecutorBridge）、`event_driven`（事件驱动，V2.1 event_driven Run Profile）。

## 4.5 六态状态机语义对照（架构 §6.4，不改值集）

| ActionStatus | 语义 | 可迁移到 |
|---|---|---|
| `created` | 已创建，未调度 | `planned` / `executing` / `cancelled` |
| `planned` | 已排期，等待执行 | `executing` / `cancelled` |
| `executing` | 执行中 | `succeeded` / `failed` / `cancelled` |
| `succeeded` | 成功（终态，出度 0） | — |
| `failed` | 失败（终态，可 retry 回 `planned`） | `planned`（retry） |
| `cancelled` | 已取消（终态，出度 0） | — |

**关键裁决**：既有 `transition_action` 的 `_TRANSITIONS` 迁移数学**零改动**；本任务只补语义对照，不新增迁移边。`failed → planned`（retry）是唯一从终态回退的边，受 `action_retry_max_attempts` 约束（既有 `attempts_exceeded` 参数已表达）。

## 4.6 异常处理

| 场景 | 处理 |
|---|---|
| 非法状态迁移 | `transition_action` 返回 `None`（既有纪律） |
| 未知 `ActionType` | 映射查表返回 `None`（调用方视为编程缺陷，TASK-004 处理） |
| `ActionSource` 未知值 | Pydantic Literal 校验抛 `ValidationError` |

---

# 5. Implementation Plan

## Step 1 — 冻结值集快照

1. 对 `models/action.py` 的 `ActionType` / `ActionStatus` / `GateReason` / `FailureKind` / `ACTION_TYPES` / `ACTION_STATUSES` / `TERMINAL_STATUSES` / `GATE_REASONS` / `FAILURE_KINDS` / `_TRANSITIONS` / `transition_action` 生成契约快照，与 V2.5.0 状态逐条对照，差异必须为空。

## Step 2 — 新增 Action 值对象

1. 在 `models/action.py` 新增 `Action(BaseModel)`：字段集对齐 §4.2；`is_terminal()` 方法（复用 `TERMINAL_STATUSES`）。
2. 保证零 `app.repositories` / `app.application` / `app.services` 依赖。

## Step 3 — 新增 ExecutionKind 与映射

1. 新增 `ExecutionKind = Literal["internal", "tool", "external"]`。
2. 新增 `ACTION_EXECUTION_MAP: dict[ActionType, ExecutionKind]`，九键全覆盖（§4.3）。

## Step 4 — 扩展 ActionSource

1. `ActionSource` 扩为五值（§4.4）；确认 `ActionRecord.source` 读取新值时 Pydantic 校验通过。

## Step 5 — 语义对照表落地

1. 以模块级常量/文档字符串登记六态语义对照表（§4.5），使「retry 唯一回退边」可 grep。

## Step 6 — 断言用例

1. 零改动断言：值集与迁移数学零变化。
2. 六问可答断言：`Action` 序列化往返（`model_dump` / `model_validate`）。
3. `ACTION_EXECUTION_MAP` 全覆盖断言：九键无遗漏，`send_notification → external`。
4. 状态机纯函数断言：非法迁移 `None`，`failed → planned` 仅在重试路径。
5. Flag 全 off 回归：既有 `models/action.py` 测试零修改通过。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- **零改动断言（差异对照为空）**：`ActionType` / `ActionStatus` / `GateReason` / `FailureKind` 值集与 `_TRANSITIONS` / `transition_action` 行为零变化。
- **六问可答断言**：`Action` 值对象可回答「是什么/做什么/什么状态/什么结果/什么时候创建/什么时候执行」六问，且序列化往返一致。
- **`ACTION_EXECUTION_MAP` 全覆盖断言**：九个 `ActionType` 全部有映射，`send_notification → external`、`query_environment → tool`、`create_reminder → internal`。
- **`ActionSource` 扩展断言**：五值含 `plan` / `event_driven`，不破坏既有三值。

## 6.2 数据正确性

- 状态机非法迁移返回 `None`（`succeeded → 任意事件 = None`）。
- `failed → planned` 仅受 `attempts_exceeded` 约束发生。

## 6.3 异常场景

- 未知 `ActionType` 映射返回 `None`。
- 未知 `ActionSource` 抛 `ValidationError`。

## 6.4 与已有系统兼容性

- 模型层零 `app.repositories` / `app.application` / `app.services` 依赖（静态断言）。
- Flag 全 off 时既有 `models/action.py` 测试零修改通过。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | 值集快照 | 与 §4.3/§4.4 逐条一致 |
| U2 | `transition_action` 全枚举 | 迁移数学零变化；终态出度 0；`failed → planned` 唯一回退 |
| U3 | `Action` 六问可答 | 字段集 + 序列化往返 |
| U4 | `ACTION_EXECUTION_MAP` 九键 | 全覆盖 + 关键映射值 |
| U5 | `ActionSource` 五值 | Pydantic 校验 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | `ActionRecord.source` 读新值 | Pydantic Literal 校验通过 |
| I2 | 模型层零上层依赖 | 静态断言 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 从 `ActionIntent` 构造 `Action` 再落 `ActionRecord` | 六问字段无丢失，生命周期可追踪 |

---

# 8. Dependencies

## 8.1 前置完成模块

- 无（全版本根节点）。

## 8.2 后续依赖模块

- TASK-002（`Action` 字段集 + `priority` 加列）、TASK-003（生命周期）、TASK-004（`ACTION_EXECUTION_MAP` 分派）、TASK-006（结果字段）。

## 8.3 需要修改的已有代码

- `app/models/action.py`（新增 `Action` / `ExecutionKind` / `ACTION_EXECUTION_MAP`，扩展 `ActionSource`）。
- 角色资产层（`ACTION_EXECUTION_MAP` 落点，若放 `app/character/asuna/action.py`）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | `Action` 值对象字段过度设计，与 `ActionRecord` 重复 | 架构风险 | 字段最小化（§4.2 可选项明确标注）；`Action` 是运行期投影，落库的是 `ActionRecord` |
| R2 | 扩展 `ActionSource` 破坏既有三值语义 | 数据风险 | 只新增 `plan`/`event_driven`，不改三值；Pydantic Literal 校验 |
| R3 | `ACTION_EXECUTION_MAP` 落点不明确（models vs 角色资产） | 架构风险 | 实现期裁决：纯数据无 IO，放 `models/action.py` 与角色资产均可，但须唯一落点 |
| R4 | 六态语义对照与既有 `transition_action` 不一致 | 技术风险 | 只补语义不改变迁移数学；零改动断言兜底 |
