# AUTO-004 Task Detail — 决策与候选裁决

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 4「Action Planning System」，是 Autonomy 的决策核心。
- **为什么需要**：角色「主动」不等于「每次都行动」，必须有明确的「不行动」能力，才能既主动又不骚扰。
- **解决什么问题**：建立 `act / wait / ignore` 三值裁决，让角色决定「下一步应该做什么」，并保留「Rule 闸门 + 领域增量」的确定性裁决模型。

## 2. Goal

本 Task 完成后，`AutonomyEngine` 能在给定 Trigger 与 Context 下输出三值裁决：`act`（产出 ActionIntent）、`wait`（保留候选下轮重评）、`ignore`（明确不行动），且裁决可解释、可观测。

## 3. Scope

**包含：**

- 新增能力：三值裁决闭环；候选评分的 Rule（硬闸门）+ LLM（软排序）两层模型（当前单候选短路）。
- 修改模块：`autonomy_policy`（纯函数裁决）、`autonomy_engine`（Context 快照）。
- 涉及数据结构：复用 `AutonomyVerdict`（decision + reason + intention）、`decision_records`（决策可观测）、`proactive_actions`（Action 候选 Outbox）。
- 系统边界：Opportunity 与 Desire 是短暂派生值对象，不独立成表，由 `TriggerSignal.context` 承载。

**不包含：**

- 不实现多候选 LLM 软排序（G5，未来版本；当前单候选短路）。
- 不新增决策相关表（复用 `decision_records`）。
- 不直接生成自然语言（AUTO-005 的角色化生成职责）。

## 4. Architecture Design

```text
TriggerSignal + AutonomyContext（PolicySnapshot）
        ↓
autonomy_policy.evaluate（八步闸门，按序短路）
  generating? → 静音时段? → 冷却通过? → 集期上限? → 已有 active?
  → 关系深度? → 角色状态不宜? → 有无主动动机?
  + R1~R5（relationship）+ W1~W3（world，只追加理由）+ A1/A2（action，只追加理由）
        ↓
AutonomyVerdict
  ├─ act     → ActionIntent
  ├─ wait    → 保留候选下轮重评
  └─ ignore  → 明确不行动
        ↓
decision_records（kind=proactive_autonomy，决策可观测）
```

## 5. Data Model

```text
Entity: AutonomyVerdict（复用 models/autonomy.py）
Fields:
- decision      act / wait / ignore
- reason        结构化单句（为什么这么裁决）
- intention     Desire 语义（AUTO-003 供给）

Entity: DecisionRecord（复用 decision_records 表）
Fields:
- kind          proactive_autonomy
- input_snapshot / decision / reason / outcome
```

## 6. Core Logic

- **Step 1**：`autonomy_engine` 构建有界 Context（`PolicySnapshot`：角色态/关系/近期对话尾/World·Action facts/近期主动行为）。
- **Step 2**：`autonomy_policy.evaluate` 按序短路执行八步闸门，叠加 R/W/A 领域增量（只追加 reason，不拆闸门）。
- **Step 3**：输出三值裁决——硬闸门命中即 `ignore`/`wait`（0 LLM）；闸门全通过且存在动机 → `act`。
- **Step 4**：裁决结果写入 `decision_records` 保证可观测。

## 7. API / Interface Design

```text
Interface: autonomy_policy.evaluate
Input: TriggerSignal + PolicySnapshot
Output: AutonomyVerdict{ decision, reason, intention }
Responsibility: 纯函数三值裁决

Interface: autonomy_engine.tick
Input: user_id
Output: 决策结果 + 入队 ActionIntent
Responsibility: 单用户 Autonomy 决策编排
```

## 8. Integration Points

- **Autonomy Policy**：`autonomy_policy`（纯函数闸门）。
- **Autonomy Engine**：`autonomy_engine`（Context 快照 + 编排）。
- **Decision Records**：`decision_records`（决策可观测）。
- **Proactive Repository**：`proactive_actions`（act 时入队候选）。

## 9. Implementation Plan

- **Step 1**：确认八步闸门 + R/W/A 领域增量的短路顺序与三值输出完整。
- **Step 2**：候选评分 Rule 层（硬闸门 0 LLM）与 LLM 软排序（后续 G5）边界固化，当前单候选短路。
- **Step 3**：决策结果写入 `decision_records`，补可观测断言。

## 10. Acceptance Criteria

**功能验收：**

- 给定关系浅 + 用户可能在工作 + 冷却中，那么 decision=ignore 不发送。
- 给定冷却中/对话中，那么 decision=wait 保留候选下轮重评。
- 给定闸门全通过且存在动机，那么 decision=act 产出 ActionIntent。

**架构验收：**

- 硬闸门先于任何 LLM 参与，Rule 裁决 0 LLM。
- 决策可观测（decision_records）。

**边界验收：**

- Opportunity/Desire 不独立成表，由 context/intention+reason 承载。

## 11. Testing Plan

- **Unit Test**：八步闸门逐条；三值裁决分支。
- **Integration Test**：ignore/wait/act 三场景端到端。
- **Manual Test**：真实「不行动」场景（关系浅 + 工作中）验证不发消息。
