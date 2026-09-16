# TASK-004 Action Executor — Task Detail

> 上游：[../architecture.md](../architecture.md) §8.2、§7.2、§3.3（G3/G5）；[../tasks.md](../tasks.md) TASK-004
> 状态：TODO
> 范围红线：**执行引擎**——接收 Action → 选执行方式 → 执行 → 捕获异常 → 返回结果；分派三种执行方式（Internal / Tool / External）；不决策（G3）、不做重试决策、不实现具体外部能力。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-004 |
| **Task Name** | Action Executor |
| **Priority** | P0 |
| **Dependencies** | TASK-003 |
| **Phase** | Phase 2 执行核心 |
| **建议提交** | `feat: Action Executor 三种执行方式分派` |

## 1.1 Goal

实现 Action 执行引擎：`ActionExecutor` 分派三种执行方式（Internal Action / Tool Call / External Service）、统一执行流程、异常捕获与结果捕获，作为「接收 Action → 选执行方式 → 执行 → 捕获异常 → 返回结果」的统一执行面（architecture §8.2）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**动手层**。TASK-003（Manager）的 `execute` 委托本任务的 `run`；TASK-006（Result）消费本任务产出的 `ActionResult`；TASK-007（Integration）经本任务执行工具调用。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-003（Manager） | 被委托执行 |
| 被依赖 | TASK-006 / TASK-007 | 提供执行能力 |
| 复用 | 既有 `CapabilityExecutor` / `ToolExecutor` | 委托，不新建执行器 |

---

# 2. Background

## 2.1 当前系统现状

| 既有资产 | 现状 |
|---|---|
| `CapabilityExecutor.run`（`services/action/executor.py`） | 已做超时包裹 / 异常归一 / usage 计时 |
| `ToolExecutor.run`（`services/tool/executor.py`，V2.4.0） | 五段短路：resolve → permission → validate → invoke → normalize，产出 `ToolResult` |
| `action_engine.run_action_planning` | 唯一编排器，但 `assemble_plan` 恒产单步 |

**关键事实**：内部动作（`CapabilityExecutor`）与工具调用（`ToolExecutor`）两条执行路径已存在，但**缺一个统一分派层**按 `ActionType` 选择执行方式；`send_notification`（外部）目前与内部动作走同一条无差别通道。

## 2.2 为什么需要本任务

architecture §8.2 的核心诉求：Action 的执行方式（Internal / Tool / External）需要按 `ACTION_EXECUTION_MAP`（TASK-001 交付）**统一分派**，而非散落在 `assemble_plan` 的 if-else 里。同时守住三条纪律：

1. Executor **不决策**（G3）：不做「要不要做 / 做哪个」判断。
2. Executor **不做重试决策**：重试在 Action 层 / Manager 层。
3. **所有执行必产 Result**（G5）：成功/失败/超时/异常都返回非空 `ActionResult`。

一句话：**执行器有了（CapabilityExecutor/ToolExecutor），统一分派层还没有（ActionExecutor）。**

---

# 3. Scope

## 3.1 In Scope

- 新建 `app/services/action/executor.py`：`ActionExecutor` 分派层。
- `dispatch(action) -> ExecutionKind`：按 `ACTION_EXECUTION_MAP` 查 `action.type`（纯函数，零 IO）。
- `execute_internal` / `execute_tool` / `execute_external` 三种执行方式。
- `run(action, ctx) -> ActionResult`：统一入口，捕获异常 / 超时 / 归一。
- 同步/异步/长任务三种执行模式（architecture §7.2）。

## 3.2 Out of Scope

- 实现具体外部能力（飞书/日历/搜索/API，属 V2.7.0）。
- 重试决策（属 Action 层 / TASK-003 Manager）。
- 决策判断（G3，永不纳入 Executor）。
- 结果契约强化（属 TASK-006）。

---

# 4. Technical Design

## 4.1 模块设计

```text
app/services/action/executor.py（新增）
├── dispatch(action) -> ExecutionKind          # 纯函数，零 IO
├── execute_internal(action, ctx) -> ActionResult   # 委托 CapabilityExecutor
├── execute_tool(action, ctx) -> ActionResult       # 委托 ToolExecutor（五段短路）
├── execute_external(action, ctx) -> ActionResult   # 经 Tool Adapter（预留）
└── run(action, ctx) -> ActionResult                # 统一入口 + 异常捕获
        │
        ▼
app/services/action/capabilities/*（既有，内部动作实现）
app/services/tool/executor.py（既有，ToolExecutor 五段短路）
```

## 4.2 分派逻辑（`dispatch`）

| 输入 | 输出 | 说明 |
|---|---|---|
| `action.type` | `ExecutionKind` | 查 `ACTION_EXECUTION_MAP`（TASK-001）；未知返回 `None`（调用方视为编程缺陷） |

```text
ACTION_EXECUTION_MAP 九个 ActionType：
  internal（6）：create_reminder / cancel_reminder / remember_fact / create_object / move_object / use_object
  tool（2）：query_environment / query_search
  external（1）：send_notification
```

## 4.3 三种执行方式

| 执行方式 | 实现 | 复用 | 说明 |
|---|---|---|---|
| `execute_internal` | 内部动作（写世界/记忆） | `CapabilityExecutor.run` | 直接执行，不经过工具治理 |
| `execute_tool` | 工具调用 | `ToolExecutor.run`（五段短路） | 受工具治理约束 |
| `execute_external` | 外部服务 | Tool Adapter（预留接口） | 占位返回 `unavailable`，不抛异常 |

## 4.4 执行流程（`run`）

```text
run(action, ctx)
  ① dispatch(action) → ExecutionKind
  ② 按 kind 分派 execute_internal / execute_tool / execute_external
  ③ 捕获异常 / 超时 → 归一为 ActionResult{status, failure_kind}
  ④ 返回 ActionResult（非空，G5）
```

## 4.5 三种执行模式（architecture §7.2）

| 模式 | 场景 | 实现 | 状态流转 |
|---|---|---|---|
| 同步 | 前台即时动作 | `await run()` 阻塞 | created → executing → 终态 |
| 异步 | 后台自治动作 | 挂 `background_jobs` / `outbox` | created → planned → executing → 终态 |
| 长任务 | 外部服务调用 | `asyncio.wait_for(timeout)` + 超时归一 | executing → failed(timeout) 或 succeeded |

## 4.6 异常处理（承 V9 + V2.4.0 纪律）

| 纪律 | 落地 |
|---|---|
| 工具失败永不静默假成功 | 失败必 `status=failed` |
| 工具失败永不阻塞回复 | 执行失败/超时不影响回复链路 |
| 所有异常落执行台账 | `action_records.result` |
| 异常归一 | `failure_kind` 由 `error_map` 决定，默认 `transient` |

```text
error_map：
  TimeoutError → timeout
  PermissionDenied → permanent
  ValidationError → permanent
  （默认）→ transient
```

---

# 5. Implementation Plan

## Step 1 — 建 executor 模块骨架

1. 新建 `app/services/action/executor.py`，声明 `dispatch` / `run` / `execute_*` 签名。

## Step 2 — 实现 dispatch

1. `dispatch`：查 `ACTION_EXECUTION_MAP`，纯函数，零 IO。

## Step 3 — 实现 execute_internal / execute_tool

1. `execute_internal` 委托 `CapabilityExecutor.run`。
2. `execute_tool` 委托 `ToolExecutor.run`（五段短路），零直调 `Capability.execute`。

## Step 4 — 实现 execute_external（预留）

1. `execute_external` 占位：返回 `ActionResult{status=unavailable}`，不抛异常。

## Step 5 — 实现 run（统一入口）

1. `run`：dispatch → 分派 → 异常捕获 → 归一 → 返回非空 `ActionResult`。
2. 长任务超时：`asyncio.wait_for(action_execution_timeout_seconds)`。

## Step 6 — 断言用例

1. 分派断言、三种执行方式断言、G5 结果必产断言、G3 不决策断言、异常归一断言、不阻塞回复断言、工具治理不绕过断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- 九个 `ActionType` 经 `dispatch` 正确映射（`send_notification → external`、`query_environment → tool`、`create_reminder → internal`）；`dispatch` 纯函数（零 IO 静态断言）。
- 三种执行方式各有实现：`execute_internal` 委托 `CapabilityExecutor`、`execute_tool` 委托 `ToolExecutor`、`execute_external` 预留占位。

## 6.2 数据正确性（G5 结果必产）

- `run` 对成功/失败/超时/异常四类输入**均返回非空 `ActionResult`**（无 `None`）。

## 6.3 异常场景

- 工具异常归一为 `status=failed` + 非空 `failure_kind`；`error_map` 覆盖 timeout/permanent/transient；无静默假成功。

## 6.4 职责边界（G3 不决策）

- `ActionExecutor` 不调 `decision_pipeline` / `autonomy_policy`（静态断言）；`run` 不做重试（零 `next_retry_at` 写入）。

## 6.5 与已有系统兼容性

- `execute_tool` 经 `ToolExecutor.run` 五段短路，零直调 `Capability.execute`。
- Flag 全 off 时 `action_engine` 原执行路径生效，行为与 V2.5.0 逐字节一致。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | `dispatch` 九键 | 全覆盖 + 关键映射值 |
| U2 | `dispatch` 纯函数 | 零 IO 静态断言 |
| U3 | `run` 成功 | 返回 `status=succeeded` |
| U4 | `run` 异常 | 返回 `status=failed` + `failure_kind` |
| U5 | `run` 超时 | 返回 `status=failed` + `failure_kind=timeout` |
| U6 | `execute_external` 占位 | 返回 `unavailable`，不抛异常 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | `execute_tool` 经五段短路 | 零直调 `Capability.execute`（静态） |
| I2 | G3 不决策 | 零 `decision_pipeline` 调用（静态） |
| I3 | 不阻塞回复 | 执行失败不影响回复链路 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 查询天气（tool）→ 失败 → 捕获 | `ActionResult{failed, transient}` |
| S2 | 发通知（external）→ 占位 | `ActionResult{unavailable}` |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-001（`ACTION_EXECUTION_MAP`）、TASK-003（Manager）。

## 8.2 后续依赖模块

- TASK-006（Result 消费 `ActionResult`）、TASK-007（Integration）。

## 8.3 需要修改的已有代码

- 新增 `app/services/action/executor.py`。
- 既有 `CapabilityExecutor` / `ToolExecutor` 零改动（只委托）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | Executor 越权决策 | 架构风险 | G3 静态断言 |
| R2 | 执行方式分派遗漏 ActionType | 技术风险 | 九键全覆盖断言 |
| R3 | 长任务超时阻塞回复 | 技术风险 | `asyncio.wait_for` + 异步挂 `background_jobs` |
| R4 | External 占位误当真实能力 | 架构风险 | 占位返回 `unavailable`，不抛异常，V2.7.0 才实现 |
