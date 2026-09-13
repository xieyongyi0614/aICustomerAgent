# AUTO-002 Task Detail — 感知与 Trigger 求值

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 2「Perception System」，是 Autonomy 的感知输入层。
- **为什么需要**：角色要能「主动」行动，必须先能感知时间变化、世界变化、用户行为变化、关系变化，并把感知归一为可求值的 Trigger。
- **解决什么问题**：把分散的感知来源（对话尾、时间 idle、约定到期）统一为三类 Trigger（`conversation_inactivity` / `scheduled_followup` / `action_due`）的求值闭环，并明确 Trigger 只是「机会」而非「行动」。

## 2. Goal

本 Task 完成后，角色具备归一化的感知能力：事件驱动（用户消息结束）与时间驱动（tick）统一入口为 `AutonomyEngine`，产出不含决策语义的 `TriggerSignal`。

## 3. Scope

**包含：**

- 新增能力：三类既有 Trigger 的求值闭环与 claim。
- 修改模块：`trigger_evaluator`（求值）、`conversation_service.reset_proactive_on_user_message`（事件驱动复位）。
- 涉及数据结构：复用 `trigger_registry` 与 `TriggerSignal` 域模型。
- 系统边界：Trigger 不携带「该不该做」判断；世界/关系变化只作为动机补充，不单独构成行动条件（当前版本）。

**不包含：**

- 不扩展 `TriggerType` 枚举（`world_change`/`life_loop_event` 等属未来版本 G7）。
- 不实现感知后的决策（AUTO-004 职责）。
- 不新增独立 Opportunity 表（Opportunity 是值对象，`context` 承载）。

## 4. Architecture Design

```text
感知来源
  ├─ 事件驱动：用户消息结束 → reset_proactive_on_user_message
  ├─ 时间驱动：life_loop tick → autonomy_engine.tick
  └─ 约定到期：register_followup → poll_due_followup
        ↓
trigger_evaluator
  ├─ evaluate_inactivity（对话尾 + idle 时长）
  ├─ poll_due_followup（约定到期）
  └─ poll_due_actions（reminder/appointment 到期）
        ↓
TriggerSignal（机会，无决策）
        ↓
Autonomy Engine（决策层，AUTO-004）
```

## 5. Data Model

```text
Entity: TriggerSignal（复用 models/autonomy.py）
Fields:
- trigger_type    conversation_inactivity / scheduled_followup / action_due
- trigger_key     幂等键（unique）
- context         机会摘要（承载 Opportunity 语义）

Entity: TriggerRegistry（复用 trigger_registry 表）
Fields:
- trigger_type / trigger_key(unique) / priority / cooldown_until / attempt_count
- status          pending/due/fired/done/cancelled
```

## 6. Core Logic

- **Step 1**：事件驱动——用户发言结束触发 `reset_proactive_on_user_message`（复位主动行为），对话尾作为 `conversation_inactivity` 的求值输入。
- **Step 2**：时间驱动——`life_loop` tick 进入 `autonomy_engine.tick`，对每个用户求值 idle 时长。
- **Step 3**：约定到期——`register_followup` 写 `trigger_registry`（`due_at` 未来），到点 `poll_due_followup` claim 产出 `scheduled_followup`。
- **Step 4**：产出 `TriggerSignal`（只含机会，不含决策），交决策层。

## 7. API / Interface Design

```text
Interface: trigger_evaluator.evaluate_inactivity
Input: user_id, 近期对话尾 + idle 时长
Output: TriggerSignal | None
Responsibility: 用户不活跃触发求值

Interface: trigger_evaluator.poll_due_followup / poll_due_actions
Input: 当前时间
Output: 到期 TriggerSignal（claim）
Responsibility: 约定/reminder 到期求值
```

## 8. Integration Points

- **Conversation Service**：`reset_proactive_on_user_message`（用户发言复位）。
- **Life Loop**：tick 入口（AUTO-001）。
- **World / Relationship 域**：事实投影作为动机补充（reason），非独立 Trigger。
- **Autonomy Engine**：感知结果的下游消费方。

## 9. Implementation Plan

- **Step 1**：确认三类 Trigger 求值与 claim 语义完整。
- **Step 2**：事件驱动（对话尾）与时间驱动（idle）的求值入口统一到 `AutonomyEngine`。
- **Step 3**：验证世界/关系变化仅追加 reason、不拆闸门、不独立触发。

## 10. Acceptance Criteria

**功能验收：**

- 给定用户长时间未发言，那么产出 `conversation_inactivity` TriggerSignal 且不带决策。
- 给定约定到期，那么产出 `scheduled_followup` 并 claim。

**架构验收：**

- `Trigger ≠ Action`，TriggerSignal 不携带「该不该做」判断。
- 感知统一入口为 `AutonomyEngine`，不另建感知框架。

**边界验收：**

- 给定世界变化，那么仅作为 reason 补充而非独立 Trigger（当前版本）。

## 11. Testing Plan

- **Unit Test**：三类 Trigger 求值函数；claim 幂等。
- **Integration Test**：事件驱动复位 + 时间驱动求值；约定到期 claim。
- **Manual Test**：真实 idle / 约定到期场景验证 Trigger 产出与不复位。
