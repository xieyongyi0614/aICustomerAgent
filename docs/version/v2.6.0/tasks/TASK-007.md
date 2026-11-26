# TASK-007 System Integration — Task Detail

> 上游：[../architecture.md](../architecture.md) §10（§10.1 ~ §10.7）、§5.4；[../tasks.md](../tasks.md) TASK-007
> 状态：TODO
> 范围红线：**系统集成**——Planning / World / Relationship / Memory 四路接线 + 反馈闭环；Action 层只动手不裁决、结果只投递不直写；不新建事件总线 / 消息队列。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-007 |
| **Task Name** | System Integration |
| **Priority** | P1 |
| **Dependencies** | TASK-004, TASK-006 |
| **Phase** | Phase 4 系统集成 |
| **建议提交** | `feat: Action 与 Planning/World/Relationship/Memory 四系统集成` |

## 1.1 Goal

连接已有系统：Planning（Plan Step → Action）、World Simulation（ActionResult → World Update）、Relationship Dynamics（Action Behavior → Relationship Change）、Memory（Important Result → Memory）四路接线 + 反馈闭环（architecture §10）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**连接层**，让执行结果真正驱动世界状态、记忆、关系与决策面的更新，形成「执行 → 状态更新 → 反馈」闭环（B6 关闭点）。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-004（Executor）、TASK-006（Result 契约） | 消费 |
| 被依赖 | TASK-008（API）、TASK-009（Testing） | 提供集成能力 |
| 接线 | 既有 Planning / World / Relationship / Memory | 复用既有通道，不新建机制 |

---

# 2. Background

## 2.1 当前系统现状

| 既有通道 | 现状 |
|---|---|
| `action_engine.integrate_result`（四通道：world/memory/relationship/note） | 已有四通道回写 |
| `memory_bridge` + `memory_policy` R1~R8 | 行动 → 记忆候选 |
| `relationship_bridge` | 行动 → 关系信号 |
| `deferred_world_op` → outbox → `world_engine` | 世界唯一写面 |
| `PlanExecutorBridge`（V2.5.0） | Plan Step → Action 翻译 |

**关键事实**：四通道回写已存在（`integrate_result`），但**缺统一反馈入口**——执行结果没有统一契约回写决策面（Autonomy）与反思面（Reflection）（architecture §2.1 B6 断层）。

## 2.2 为什么需要本任务

architecture §10.6 的核心诉求：反馈闭环（ActionResult → 四通道回写 + 三面反馈）**不新建机制，全部复用既有通道**，Action 层新增的只是「统一的 ActionResult 作为反馈入口」。本任务把 TASK-006 的统一契约接到四系统上。

一句话：**四通道回写有了（integrate_result），统一反馈入口还没有（ActionResult 接线）。**

---

# 3. Scope

## 3.1 In Scope

- Planning 集成：`PlanExecutorBridge.to_intent` → `ActionManager.create(source="plan")` → execute → `PlanStepOutcome` 映射。
- World 集成：`ActionResult.effects(kind=world)` → `deferred_world_op` → outbox → `world_engine`。
- Relationship 集成：`ActionResult.effects(kind=relationship)` → `relationship_bridge`。
- Memory 集成：临时执行记录 vs 长期记忆分流。
- 反馈闭环：四通道回写 + 三面反馈（Autonomy / Reflection / Planning）。

## 3.2 Out of Scope

- 新建事件总线 / 消息队列（`outbox_events` 已承担）。
- 直接写 Memory / Character 域（经 `memory_policy` / `world_engine`）。
- Reflection 直接改写 Action（反思管认知）。
- 反馈预算上限（architecture Q3，压测后决定）。

---

# 4. Technical Design

## 4.1 Planning 集成（architecture §10.2）

```text
Plan Step（V2.5.0）
  ↓ PlanExecutorBridge.to_intent → Action{type, params, dedupe_key, plan_step}
ActionManager.create(source="plan")
  ↓
ActionManager.execute → ActionResult
  ↓
ActionResult → PlanStepOutcome → PlanObserver 推进 / 重规划
```

**纪律**：Planning 只编排、Action 层只执行（G2）；PlanStep 与 Action 1:1；多步由 Planning 层编排。

## 4.2 World 集成（architecture §10.3）

```text
Action: send_message
  ↓ ActionResult.effects(kind=world)
deferred_world_op → outbox → world_engine
  ↓
World Update: last_interaction_time
```

**纪律**：Action 永不直接改世界（经 `world_engine` 唯一写面）。

## 4.3 Relationship 集成（architecture §10.4）

```text
Action: help_user
  ↓ ActionResult.effects(kind=relationship)
relationship_bridge
  ↓
Relationship Update: trust +1
```

**纪律**：行为如何影响关系由 `relationship_bridge` 裁决，Action 层只产出关系信号。

## 4.4 Memory 集成（architecture §10.5）

| 层级 | 内容 | 载体 | 机制 |
|---|---|---|---|
| 临时执行记录 | 查询天气、环境查询 | `action_records` | 不落 `memories` |
| 长期记忆 | 帮用户记的提醒、重要关怀送达 | `memories`（经 R1~R8） | `memory_bridge` + `memory_policy` |

**纪律**：记忆政策 R1~R8 零豁免。

## 4.5 反馈闭环（architecture §10.6，B6 关闭点）

```text
ActionResult
  ├─ World：状态更新（outbox → world_engine）
  ├─ Memory：记忆候选（memory_policy R1~R8）
  ├─ Relationship：关系信号（relationship_bridge）
  ├─ Autonomy：action_facts / tool_facts → 决策面
  ├─ Reflection：执行证据窗 → Insight
  └─ Planning：PlanStepOutcome → 推进 / 重规划
```

## 4.6 逐系统契约表（architecture §10.7）

| 系统 | 提供给 Action 层 | 从 Action 层接收 | 永不改变 |
|---|---|---|---|
| Planning | `PlanStepSpec` | `ActionResult` → `PlanStepOutcome` | 计划编排权威；不执行 |
| Tool | `ToolExecutor` | `Action`（type → 执行方式） | 工具治理权威；不重试决策 |
| World | `world_engine` 写函数 | `deferred_world_op` | 世界唯一写面 |
| Memory | `memory_policy` R1~R8 | 执行结果记忆候选 | R1~R8 零豁免 |
| Relationship | `relationship_bridge` | 关系信号 | 单向 boost 方向 |
| Autonomy | `decision_pipeline` | `action_facts` / `tool_facts` | 决策权威 |
| Reflection | 三道闸、证据窗 | 执行证据窗 | 防幻觉纪律 |
| Life Loop | 维护步骤 | 调度消费 | 唯一调度器 |

## 4.7 异常处理

| 场景 | 处理 |
|---|---|
| 下游投递失败（memory_bridge / outbox） | 只 log，不回滚执行；outbox 自身退避 |
| 关系信号异常 | 只 log，不影响执行结果 |
| 世界写入失败 | outbox 重试 |

---

# 5. Implementation Plan

## Step 1 — Planning 接线

1. `PlanExecutorBridge.to_intent` → `ActionManager.create(source="plan")` → execute → `PlanStepOutcome` 映射。

## Step 2 — World 接线

1. `ActionResult.effects(kind=world)` → `deferred_world_op` → outbox → `world_engine`。

## Step 3 — Relationship 接线

1. `ActionResult.effects(kind=relationship)` → `relationship_bridge`。

## Step 4 — Memory 接线

1. 临时执行记录 / 长期记忆分流（`memory_bridge` + `memory_policy` R1~R8）。

## Step 5 — 反馈闭环接线

1. 四通道回写 + 三面反馈（复用 `integrate_result`）。

## Step 6 — 断言用例

1. 四系统集成断言、反馈闭环断言、职责不重叠断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- Planning 集成：`PlanStep → Action` 成立，1:1，Planning 层零直调 `ActionExecutor`（G2 静态断言）。
- World 集成：`send_message → last_interaction_time` 用例通过；Action 层零直写 `world_engine`。
- Relationship 集成：`help_user → trust +1` 经 `relationship_bridge`；零直写 `relationship_*`。
- Memory 集成：临时记录不落 `memories`；重要结果经 R1~R8 进候选。

## 6.2 数据正确性

- 反馈闭环四通道回写（world/memory/relationship/note）+ 三面反馈全部接线。

## 6.3 异常场景

- 下游投递失败不回滚执行（只 log）。

## 6.4 职责不重叠

- Planning 只编排 / Action 只执行 / Tool 只动手 / 世界唯一写面 / 记忆唯一政策闸，五者无交叉写面。

## 6.5 与已有系统兼容性

- Flag 全 off 时四系统集成全部走既有路径，行为与 V2.5.0 逐字节一致。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | Planning 接线 | `to_intent → create(source="plan")` |
| U2 | Memory 分流 | 临时 vs 长期 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | World 集成 | `send_message → last_interaction_time` |
| I2 | Relationship 集成 | `help_user → trust +1` |
| I3 | Memory 集成 | R1~R8 零豁免 |
| I4 | 反馈闭环 | 四通道 + 三面 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 「明天提醒我学习」全链 | Plan → Action → Execute → World/Memory/Relationship → Feedback |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-004（Executor）、TASK-006（Result 契约）。

## 8.2 后续依赖模块

- TASK-008（API）、TASK-009（Testing）。

## 8.3 需要修改的已有代码

- `app/services/planning/executor_bridge.py`（接 `ActionManager.create`）。
- `app/application/action_engine.py`（`integrate_result` 接统一 `ActionResult`）。
- 既有 `memory_bridge` / `relationship_bridge` / `world_engine` 零改动（只复用）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 集成越权直写 | 架构风险 | 职责不重叠断言 + 静态扫描 |
| R2 | 反馈淹没决策候选 | 架构风险 | 有界（architecture R5/Q3） |
| R3 | 双源一致性 | 数据风险 | outbox 一致性模型 |
| R4 | 下游投递失败连锁 | 技术风险 | 只 log 不回滚 |
