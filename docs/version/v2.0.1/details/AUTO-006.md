# AUTO-006 Task Detail — 结果记录与反思集成

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 6「Reflection & Learning Loop」，是 Autonomy 的行为后学习层。
- **为什么需要**：主动行为结束后，需要产生结果记录、经验总结与后续调整，形成闭环学习；同时不能让反思随每次 autonomy tick 触发（避免性能浪费与语义混淆）。
- **解决什么问题**：让「为什么产生 / 基于什么状态 / 使用什么目标 / 发送到哪个 channel / 是否成功」全程可答，且 Reflection 与 Autonomy 决策解耦。

## 2. Goal

本 Task 完成后，任一主动行为都可回答「内部消息 id / 外部消息 id / 发送到哪个 channel / 是否成功 / 为什么产生」，且 Reflection 由独立频控触发、与 autonomy decision 解耦。

## 3. Scope

**包含：**

- 新增能力：主动行为结果的可观测记录闭环。
- 修改模块：trace 体系补 `external_message_id` + `channel` 字段关联（与 AUTO-005 同步）。
- 涉及数据结构：复用 `decision_records`（`kind=proactive_autonomy`）、`reflection_runs`/`insights`（长期总结）。
- 系统边界：`Reflection → Insight → Context → Autonomy Decision`；禁止 `Autonomy → Reflection → 每次主动行为都反思`。

**不包含：**

- 不改 Reflection System 核心逻辑。
- 不新增结果记录表（复用 `decision_records`）。
- 不记录 token/open_id（脱敏）。

## 4. Architecture Design

```text
主动行为结束
        ↓
结果记录
  → decision_records（kind=proactive_autonomy，decision/reason/outcome）
  → trace（external_message_id + channel）
        ↓
Reflection（独立频控，非每次 tick）
  → life_loop._step_reflection_check（v2_life_loop_reflection_check_interval_minutes + REF-003 日桶幂等）
  → reflection_runs / insights（长期总结）
        ↓
Insight → Context → Autonomy Decision（下一轮决策注入）
```

## 5. Data Model

```text
Entity: DecisionRecord（复用 decision_records）
Fields:
- kind          proactive_autonomy
- input_snapshot / decision / reason / outcome

Entity: ReflectionRun / Insight（复用 reflection_runs / insights）
- 长期总结，供后续决策 Context 注入
```

## 6. Core Logic

- **Step 1**：主动行为结束（delivered/acked/discarded/failed/expired）时，记录 outcome 到 `decision_records`。
- **Step 2**：trace 补齐 `external_message_id` + `channel`，使投递结果可审计。
- **Step 3**：`life_loop._step_reflection_check` 按独立频控触发 Reflection（REF-003 日桶幂等），产生长期 insight。
- **Step 4**：insight 经显著度门槛注入下一轮决策 Context（`memory_digest_var` 通道），完成学习闭环。

## 7. API / Interface Design

```text
Interface: _step_reflection_check（已存在，复用）
Input: 周期触发 + 频控状态
Output: reflection_runs / insights
Responsibility: 独立频控的反思触发

Interface: trace 记录（扩展）
Input: external_message_id + channel + outcome
Output: 可观测 trace
Responsibility: 投递结果审计
```

## 8. Integration Points

- **Decision Records**：`decision_records`（决策可观测）。
- **Reflection System**：`_step_reflection_check`（REF-003 日桶幂等，独立频控）。
- **Trace 体系**：`TurnTraceSession`（`TraceKind.AUTONOMY_TICK` / `TraceKind.PROACTIVE`）。
- **Life Loop**：反思触发宿主。

## 9. Implementation Plan

- **Step 1**：主动行为 outcome 落 `decision_records`（`kind=proactive_autonomy`）。
- **Step 2**：trace 补 `external_message_id` + `channel` 字段（与 AUTO-005 联动）。
- **Step 3**：确认 Reflection 频控与 autonomy decision 解耦，验证 insight 注入路径。

## 10. Acceptance Criteria

**功能验收：**

- 任一 active action 可回答「内部消息 id / 外部消息 id / 发送到哪个 channel / 是否成功 / 为什么产生」。

**架构验收：**

- `Reflection → Insight → Context → Autonomy Decision`，禁止反向「每次主动行为都反思」。
- 不记录 token/open_id（脱敏）。

**边界验收：**

- Reflection 执行频率与 autonomy decision 解耦，不随每次 tick 触发。

## 11. Testing Plan

- **Unit Test**：outcome 记录；trace 字段补齐。
- **Integration Test**：主动行为结束 → 记录 → insight 注入下一轮决策的闭环。
- **Manual Test**：真实反思触发频率观察（不随 tick 高频触发）。
