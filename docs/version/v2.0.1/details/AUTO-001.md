# AUTO-001 Task Detail — Runtime 生命周期与调度收敛

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 1「Autonomy Runtime Foundation」，是 Autonomy 的横向调度底座。
- **为什么需要**：当前系统存在两个 tick 源——`autonomy_worker`（独立 asyncio tick 循环）与 `life_loop`（V2.0.0 统一周期编排，其 `decision` 步骤内部调用 `autonomy_engine.tick`）。两者可能对同一 Trigger 重复求值（architecture.md Gap G4），带来重复风险与性能损耗。
- **解决什么问题**：收敛「何时检查」的职责到单一入口，保证 Scheduler 只产 Trigger、不做决策、不发消息，避免双 tick 源重复求值。

## 2. Goal

本 Task 完成后，Autonomy Runtime 具备单一、明确的生命周期调度入口：`life_loop` 为唯一周期入口，`autonomy_worker` 退化为 `v2_life_loop_enabled=False` 时的兜底；同一 Trigger 不被重复求值。

## 3. Scope

**包含：**

- 新增能力：明确双 tick 源的主从关系与兜底语义。
- 修改模块：`life_loop`（主驱动）、`autonomy_worker`（兜底）的启动/启用关系。
- 涉及数据结构：复用 `trigger_registry`（claim 语义）与 `background_jobs`，不新增表。
- 系统边界：Scheduler 只回答「什么时候检查」，只产 Trigger，不做决策、不发消息。

**不包含：**

- 不新建 `autonomy_scheduler`/`autonomy_queue`/`autonomy_jobs`。
- 不改 `autonomy_engine` 本体、不改 `autonomy_policy` 裁决逻辑。
- 不涉及投递链路（AUTO-005 职责）。

## 4. Architecture Design

```text
v2_life_loop_enabled=True
        ↓
life_loop.run_life_loop_worker（唯一周期入口）
  → _collect_work_users → _run_user_cycle
      → _step_decision → autonomy_engine.tick（Trigger 求值，claim 语义）
        ↓
autonomy_worker（退化为兜底，仅在 v2_life_loop_enabled=False 时启动）
```

```text
Scheduler（职责受限）
  → Trigger（只产机会）
  → Autonomy Engine（决策）
  → Action Execution（行为）
  → Channel（投递）
```

## 5. Data Model

```text
Entity: TriggerRegistry（复用 trigger_registry 表）
Fields（关键）:
- trigger_type / trigger_key(unique)   幂等与去重（claim）
- priority / cooldown_until / attempt_count
- status  pending/due/fired/done/cancelled

本 Task 无新增字段、无新增表。
```

## 6. Core Logic

- **Step 1**：判定 `v2_life_loop_enabled` 开关，决定主驱动是 `life_loop` 还是 `autonomy_worker`。
- **Step 2**：主驱动按周期 tick，经 `_collect_work_users` 枚举候选用户（含 Idle 短路 + 预算闸）。
- **Step 3**：对每个用户，`_step_decision` 调用 `autonomy_engine.tick`，经 `trigger_registry` claim 语义保证同一 Trigger 至多被一个 tick 源求值一次。
- **Step 4**：`autonomy_worker` 仅在 `v2_life_loop_enabled=False` 时作为轻量兜底 tick 源启动。

## 7. API / Interface Design

```text
Interface: life_loop.run_life_loop_worker
Input: 无（内部周期）
Output: 周期内执行用户决策步骤
Responsibility: 唯一周期编排入口

Interface: autonomy_engine.tick
Input: user_id
Output: Trigger 求值结果（TriggerSignal / 决策）
Responsibility: 单用户 Autonomy 决策，claim 语义去重
```

## 8. Integration Points

- **Life Loop**：`life_loop`（phase-5，LIFE-002 编排底座）作为主驱动。
- **Autonomy Worker**：`autonomy_worker` 作为兜底 tick 源。
- **Trigger Registry**：`trigger_registry` claim 语义承载跨重启持久化与去重。
- **Autonomy Engine**：`autonomy_engine.tick` 是被调用的单用户决策入口。

## 9. Implementation Plan

- **Step 1**：明确 `life_loop` 与 `autonomy_worker` 的启动条件与主从关系。
- **Step 2**：`autonomy_worker` 增加 `v2_life_loop_enabled=False` 兜底判定，避免与 `life_loop` 并存双 tick。
- **Step 3**：验证 `trigger_registry` claim 语义在单 tick 源下的正确性，补充重复求值防护断言。

## 10. Acceptance Criteria

**功能验收：**

- 给定 `v2_life_loop_enabled=True`，那么 autonomy 决策仅由 `life_loop` 触发一次。
- 给定 `v2_life_loop_enabled=False`，那么 `autonomy_worker` 兜底启动。

**架构验收：**

- Scheduler 只产 Trigger，不直接发消息、不直接调 LLM。
- 不新建任何队列/调度基础设施。

**边界验收：**

- 同一 Trigger 不被两个 tick 源重复求值（claim 语义 + dedupe_key 生效）。

## 11. Testing Plan

- **Unit Test**：启动条件判定（`v2_life_loop_enabled` 两分支）。
- **Integration Test**：单 tick 源下同一 Trigger 只求值一次；双源并存的重复防护。
- **Manual Test**：开关切换下观察 tick 行为与重复消息抑制。
