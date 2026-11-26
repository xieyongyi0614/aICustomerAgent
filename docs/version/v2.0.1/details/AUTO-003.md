# AUTO-003 Task Detail — 动机与优先级覆盖

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 3「Motivation & Goal System」，是 Autonomy 的动机表达层。
- **为什么需要**：角色主动行动需要「为什么想做」的动机表达（Desire），且「用户明确要求的提醒」（P0/P1）不应被普通 check_in 的冷却压制。
- **解决什么问题**：当前所有 trigger 走同一套冷却闸门，高优提醒被普通冷却压制（architecture.md Gap G8）。本任务引入显式优先级覆盖通道，并明确 Desire（动机）与 Trigger（发生了什么）的语义边界。

## 3. Scope

**包含：**

- 新增能力：P0/P1 High Priority Override 语义（覆盖普通冷却，不跨静音时段）。
- 修改模块：`autonomy_policy`（显式优先级 override 通道）。
- 涉及数据结构：复用 `intention` + `reason`（Desire 语义）、`goal_id` + `selected_goal_type`（Goal 语义）、`trigger_registry.priority`。
- 系统边界：Desire 由 `intention` + `reason` 承载，不新增独立 Desire 对象。

**不包含：**

- 不新增独立 Desire 表/对象。
- 不实现 Preference/Commitment → 重复 scheduled action（G6，未来版本）。
- 不破坏静音时段铁律（除非用户明确要求跨静音）。

## 4. Architecture Design

```text
TriggerSignal（发生了什么）
        ↓
Desire（为什么想做）
  → intention（check_in / repair_rapport / ...，由 PROACTIVE_INTENTION_MAP 从 Goal 映射）
  → reason（≤60 字结构化单句）
        ↓
优先级覆盖判定
  ├─ P0 Critical    scheduled_followup + action_due（用户明确要求提醒）→ 覆盖普通冷却
  ├─ P1 Important   未闭环委托 / 关系冲突召回 → 覆盖普通冷却
  ├─ P2 Normal      life_loop / world 事件 → 不覆盖
  └─ P3 Casual      conversation_inactivity check_in → 不覆盖
        ↓
静音时段铁律：即使 P0 也默认尊重静音（除非用户明确要求跨静音）
```

## 5. Data Model

```text
Entity: AutonomyVerdict（复用 models/autonomy.py）
Fields:
- intention     Desire 语义（check_in / repair_rapport / reconciliation_check_in / reconnect_check_in）
- reason        为什么想做的结构化单句
- decision      act / wait / ignore（裁决，AUTO-004 消费）

Entity: TriggerRegistry.priority（复用）
- priority      P0/P1/P2/P3，参与优先级覆盖判定
```

## 6. Core Logic

- **Step 1**：从 Goal 类型经 `PROACTIVE_INTENTION_MAP` 映射出 `intention`（`user_care → check_in`、`relationship → repair_rapport`）。
- **Step 2**：判定 trigger 优先级（`scheduled_followup`/`action_due` → P0/P1；`conversation_inactivity` → P3）。
- **Step 3**：P0/P1 触发 High Priority Override，覆盖普通冷却闸门；P2/P3 不覆盖。
- **Step 4**：静音时段铁律优先——即使 P0 也默认拦截，除非用户明确要求跨静音。

## 7. API / Interface Design

```text
Interface: autonomy_policy.evaluate（扩展）
Input: PolicySnapshot + trigger 优先级
Output: AutonomyVerdict（含优先级 override 判定）
Responsibility: 八步闸门 + 优先级覆盖，输出 act/wait/ignore
```

## 8. Integration Points

- **Autonomy Policy**：`autonomy_policy`（八步闸门，本任务扩展 override 通道）。
- **Trigger Registry**：`trigger_registry.priority` 参与判定。
- **Goal 系统**：`selected_goal_type` / `goal_id` 提供动机来源。

## 9. Implementation Plan

- **Step 1**：在 `autonomy_policy` 引入显式优先级判定，区分 P0/P1 与 P2/P3。
- **Step 2**：P0/P1 override 普通冷却，但保留静音时段铁律。
- **Step 3**：补配置项（优先级/预算相关），并加回归断言。

## 10. Acceptance Criteria

**功能验收：**

- 给定 P0 `scheduled_followup` 且冷却未过，那么仍放行（覆盖普通冷却）。
- 给定 P2/P3 普通 check_in，那么不覆盖冷却。

**架构验收：**

- Desire 由 `intention` + `reason` 承载，不新增独立对象。
- 动机与 Trigger 语义严格区分。

**边界验收：**

- 给定静音时段，那么默认仍拦截（即使 P0），除非用户明确要求跨静音。

## 11. Testing Plan

- **Unit Test**：优先级判定与 override 分支；静音时段铁律。
- **Integration Test**：P0 提醒在冷却期内仍放行；P2/P3 不覆盖。
- **Manual Test**：真实高优提醒 vs 普通 check_in 的冷却行为对比。
