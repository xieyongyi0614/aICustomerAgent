# TASK-006 Action Result System — Task Detail

> 上游：[../architecture.md](../architecture.md) §8.4、§10.6、§14（R2）、§9.7 Q1；[../tasks.md](../tasks.md) TASK-006
> 状态：TODO
> 范围红线：**结果系统**——强化 `ActionResult` 为统一结果契约；处理成功/失败/部分完成/重试四类；**兑现 V2.4.0「旧读键退役窗口推到 V2.6.0」承诺**；不直接写世界/记忆/关系。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-006 |
| **Task Name** | Action Result System |
| **Priority** | P1 |
| **Dependencies** | TASK-004 |
| **Phase** | Phase 3 增强能力 |
| **建议提交** | `feat: ActionResult 统一契约与旧读键退役` |

## 1.1 Goal

强化既有 `ActionResult` 值对象为统一结果契约（id / action_id / status / output / error / metadata / observations / created_at），处理成功/失败/部分完成/重试四类结果，并**兑现 V2.4.0「旧读键退役窗口推到 V2.6.0」承诺**（architecture §8.4）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**反馈契约层**。TASK-007（Integration）的四系统接线依赖本任务的统一 `ActionResult`；本任务关闭 B5（结果契约统一）与 B7（旧读键退役）两个断层。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-004（Executor 产出 `ActionResult`） | 消费 |
| 被依赖 | TASK-007（Integration 消费结果） | 提供契约 |
| 强化 | 既有 `ActionResult` / `CapabilityResult` / `ToolResult` / `PlanStepOutcome` | 统一 |

---

# 2. Background

## 2.1 当前系统现状

| 既有契约 | 现状 | 本任务动作 |
|---|---|---|
| `ActionResult`（`models/action.py`） | `status`（succeeded/failed/partial）/ `effects` / `error` / `failure_kind` | 强化（保留语义，新增字段） |
| `CapabilityResult`（V9） | `status` / `payload`（自由 dict）/ `usage` / `error` | 退役旧读键 |
| `ToolResult`（V2.4.0） | 结果契约 | 提升为 ActionResult 的 Tool 级投影 |
| `PlanStepOutcome`（V2.5.0） | 步骤结果契约 | 映射到 ActionResult |

**关键事实**：V2.4.0 §5.5 明确「V9 既有读键（`world_event_id` / `memory_id` / `failure_kind` 旧位置）保留到 V2.5.0，正式退役窗口推到 V2.6.0」——这是本任务必须兑现的承诺（architecture §2.1 B7、G9）。

## 2.2 为什么需要本任务

architecture §8.4 的核心诉求：执行结果需要一个**统一契约**，让下游 Memory / Reflection / Autonomy / Planning 按统一结构消费，而非面对三份语义（`payload` / `ToolResult` / `PlanStepOutcome`）。同时兑现 V2.4.0 的退役承诺。

一句话：**结果值对象有了（三份散落），统一结果契约还没有（ActionResult 强化）。**

---

# 3. Scope

## 3.1 In Scope

- 强化 `ActionResult` 值对象：新增 `id` / `action_id` / `output` / `metadata` / `observations` / `created_at`；`status` 扩 `timeout`。
- 四类结果处理：成功 / 失败 / 部分完成 / 重试。
- 统一契约：`CapabilityResult.payload` → `ActionResult.output`；`ToolResult` → Tool 级投影；`PlanStepOutcome` → 映射。
- 旧读键退役：双写一个版本窗口（V2.6.0）后退役。

## 3.2 Out of Scope

- 四系统具体接线（属 TASK-007）。
- 反馈闭环的预算上限（architecture Q3，压测后决定）。
- 单 Action 多步部分失败回滚语义（architecture Q1，本版本只记录不回滚）。

---

# 4. Technical Design

## 4.1 模块设计

```text
app/models/action.py::ActionResult（强化）
├── 既有：status / effects / error / failure_kind
└── 新增：id / action_id / output / metadata / observations / created_at
        │
        ▼
app/services/action/executor.py（TASK-004，产出 ActionResult）
app/services/action/memory_bridge.py（既有，消费 effects）
app/services/tool/normalizer.py（既有，ToolResult → ActionResult 投影）
```

## 4.2 ActionResult 字段（架构 §8.4）

| 字段 | 类型 | 状态 | 说明 |
|---|---|---|---|
| `id` | str | 新增 | 结果 id |
| `action_id` | str | 新增 | 关联 Action |
| `status` | `succeeded/failed/partial/timeout` | 扩值 | 扩 `timeout` |
| `output` | dict | 新增 | 结构化输出（替代自由 `payload`） |
| `error` | str \| None | 既有 | 可读错误 |
| `metadata` | dict | 新增 | usage / failure_kind / external_calls |
| `effects` | list[ActionEffect] | 既有 | 结构化效果清单 |
| `observations` | dict | 新增 | 给下游消费的事实 |
| `failure_kind` | FailureKind \| None | 既有 | |
| `created_at` | datetime | 新增 | 结果产生时刻 |

## 4.3 四类结果处理（架构 §8.4）

| 结果类型 | 处理 | 后续 |
|---|---|---|
| 成功 | `status=succeeded`，`output` 结构化，`effects` 回写四通道 | 反馈闭环（TASK-007） |
| 失败 | `status=failed`，`failure_kind` 决定重试策略 | `retry`（受 max_attempts） |
| 部分完成 | `status=partial`，`effects` 含已完成部分 | 记录不回滚 |
| 重试 | 复用原 `dedupe_key` | 防重复副作用 |

## 4.4 统一契约（B5/B7 关闭点）

| 既有契约 | 本任务动作 |
|---|---|
| `CapabilityResult.payload`（V9 自由 dict） | 退役旧读键（`world_event_id` / `memory_id` / `failure_kind` 旧位置），统一为 `output` + `effects` + `observations` |
| `ToolResult`（V2.4.0） | 提升为 ActionResult 的 Tool 级投影 |
| `PlanStepOutcome`（V2.5.0） | 映射到 ActionResult（Plan 层只读投影） |

## 4.5 旧读键退役（兑现 V2.4.0 承诺）

```text
双写窗口（V2.6.0）：
  旧读键 world_event_id / memory_id / failure_kind 旧位置 继续双写
  新契约 output / effects / observations 同时生效
  ↓ Flag on 且全量测试通过后
退役：旧读键下线，统一为新契约
```

## 4.6 状态变化

`ActionResult.status` 四态：`succeeded` / `failed` / `partial` / `timeout`。由 TASK-004 Executor 写入。

## 4.7 异常处理

| 场景 | 处理 |
|---|---|
| 失败结果 | `failure_kind` 决定重试（`transient`/`timeout` → 可重试，`permanent` → 不重试） |
| 部分完成 | 记录不回滚 |
| 重复投递 | `dedupe_key` + `has_memory_effect` 泛化 |

---

# 5. Implementation Plan

## Step 1 — 强化 ActionResult 值对象

1. `models/action.py::ActionResult` 新增 `id` / `action_id` / `output` / `metadata` / `observations` / `created_at`；`status` 扩 `timeout`。

## Step 2 — 四类结果处理

1. 成功 / 失败 / 部分完成 / 重试四类的归一逻辑（复用 TASK-004 的 `run`）。

## Step 3 — 统一契约映射

1. `CapabilityResult.payload` → `output`；`ToolResult` → Tool 级投影；`PlanStepOutcome` → 映射函数。

## Step 4 — 旧读键双写

1. 双写窗口：旧读键 + 新契约同时生效。

## Step 5 — 断言用例

1. 结果契约断言、四类结果断言、统一契约断言、兼容承诺兑现断言、反馈入口断言、幂等断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- `ActionResult` 含全部新字段，序列化往返一致；`status` 四值（含 `timeout`）。
- 四类结果各有用例；`partial` 记录已完成 effects 不回滚；`retry` 复用原 `dedupe_key`。

## 6.2 数据正确性

- `CapabilityResult.payload` 旧读键退役后，`output` 承载结构化输出；`ToolResult` / `PlanStepOutcome` 能映射到 `ActionResult`（映射测试）。

## 6.3 异常场景

- 重复投递不产生重复副作用（`has_memory_effect` + `dedupe_key`）。

## 6.4 兼容承诺兑现（G9）

- V9 旧读键在 Flag on 且全量测试通过后退役；退役窗口 ≥ 一个版本（双写断言）。

## 6.5 与已有系统兼容性

- Flag 全 off 时 `ActionResult` 仍为三值（succeeded/failed/partial），`timeout` 不启用，行为与 V2.5.0 逐字节一致。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | `ActionResult` 字段 | 全字段 + 往返 |
| U2 | `status` 四值 | 含 `timeout` |
| U3 | `payload` → `output` 映射 | 旧读键退役后结构化输出 |
| U4 | `ToolResult` / `PlanStepOutcome` 映射 | 投影一致 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | 双写窗口 | 旧读键 + 新契约同时生效 |
| I2 | 反馈入口 | `effects` 四 kind（world/memory/relationship/note） |
| I3 | 幂等 | 重复投递无重复副作用 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 执行失败 → 重试 → 成功 | 结果链完整可追踪 |
| S2 | 部分完成 | `partial` 记录已完成 effects |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-004（Executor 产出 `ActionResult`）。

## 8.2 后续依赖模块

- TASK-007（Integration 消费统一契约）。

## 8.3 需要修改的已有代码

- `app/models/action.py`（`ActionResult` 强化）。
- 既有 `CapabilityResult` / `ToolResult` / `PlanStepOutcome` 的映射处。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 旧读键退役破坏 V9 下游 | 架构风险 | 双写一个版本窗口 + Flag on 全量测试通过后退役（architecture R2） |
| R2 | 契约过度设计 | 架构风险 | 字段最小化 + 可选项明确 |
| R3 | `partial` 回滚语义不明 | 数据风险 | 本版本只记录不回滚（architecture Q1） |
| R4 | `timeout` 值与其他契约冲突 | 技术风险 | 对齐 `CapabilityResult` 已有 `timeout` 语义 |
