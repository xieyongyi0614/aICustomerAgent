# AUTO-007 Task Detail — 频率控制与可暂停

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 7「Safety & Control」，是 Autonomy 的安全闸。
- **为什么需要**：角色不能「每隔 5 分钟：你在干嘛呀？」。主动行为必须受频率限制、用户控制、防止无限行动、可暂停。
- **解决什么问题**：建立 Interruption Policy 四档判定与重试上限封顶，保证「既能主动又不骚扰」，并守住「Channel 失败绝不回退到 Character Decision」的核心不变量。

## 2. Goal

本 Task 完成后，主动行为受频率限制（集期上限、冷却、静音时段）、可被用户发言复位、重试有上限、可暂停，且 Decision/生成/发送三者状态解耦。

## 3. Scope

**包含：**

- 新增能力：Interruption Policy 四档判定；重试上限封顶；重复抑制。
- 修改模块：`autonomy_policy`（闸门）、`proactive_repository`（状态机 + 幂等）、`proactive_executor`（重试模型）。
- 涉及数据结构：复用 `proactive_actions`（`attempt`/`next_retry_at`/`dedupe_key`）、`trigger_registry.cooldown_until`、静音时段配置。
- 系统边界：用户发言即复位主动行为（`reset_proactive_on_user_message`）。

**不包含：**

- 不新增状态（现有状态机已足够，`rejected`/`cancelled` 由 `discarded` 承载）。
- 不新增表/队列。

## 4. Architecture Design

```text
Interruption Policy（四档判定）
  ├─ Hard Block            → ignore（静音/关系浅/无动机/R1 冲突期克制）
  ├─ Soft Block            → wait（冷却中/对话中/上一条未处理）
  ├─ Allowed               → act（闸门全通过 + 存在动机）
  └─ High Priority Override → act（P0/P1 覆盖普通冷却，AUTO-003 供给）
        ↓
重试上限封顶
  → attempt 超限 → failed 终态（禁止无限重试）
        ↓
重复抑制
  → dedupe_key + idempotency_key 抑制双发
        ↓
用户发言复位
  → reset_proactive_on_user_message（delivered→acked，candidate→discarded）
```

## 5. Data Model

```text
Entity: ProactiveAction（复用 proactive_actions）
Fields（关键）:
- attempt / next_retry_at   重试计数与调度（上限封顶）
- dedupe_key                幂等键
- status                    状态机 candidate/approved/delivered/acked/discarded/failed/expired

Entity: TriggerRegistry.cooldown_until（复用）
- 冷却时间戳，参与 Soft Block 判定
```

## 6. Core Logic

- **Step 1**：四档判定——硬闸门命中 `ignore`，软闸门命中 `wait`，全通过 `act`，P0/P1 覆盖普通冷却 `act`。
- **Step 2**：重试上限封顶——`attempt` 超限 → `failed` 终态，禁止无限重试。
- **Step 3**：重复抑制——`dedupe_key` 已处理过则拒绝入队；`idempotency_key` 兜底发送级幂等。
- **Step 4**：用户发言复位——`reset_proactive_on_user_message` 复位候选/已投递，进入正常 Chat Pipeline。
- **Step 5**：核心不变量——Channel 失败绝不回退到 Character Decision（Decision 一次、生成可重试、发送可重试）。

## 7. API / Interface Design

```text
Interface: autonomy_policy.evaluate（复用）
Input: PolicySnapshot
Output: AutonomyVerdict（四档判定结果）
Responsibility: 打扰策略裁决

Interface: proactive_repository.enqueue / _fail_for_retry
Input: ProactiveAction
Output: 状态迁移 + 重试调度
Responsibility: 状态机 + 幂等 + 重试上限
```

## 8. Integration Points

- **Autonomy Policy**：`autonomy_policy`（闸门）。
- **Proactive Repository**：`proactive_repository`（状态机 + 幂等）。
- **Proactive Executor**：`proactive_executor`（重试模型）。
- **Conversation Service**：`reset_proactive_on_user_message`（用户发言复位）。

## 9. Implementation Plan

- **Step 1**：固化四档判定（Hard/Soft/Allowed/Override）与对应闸门。
- **Step 2**：重试上限封顶 + `dedupe_key`/`idempotency_key` 重复抑制验证。
- **Step 3**：用户发言复位与「Channel 失败不重裁决」不变量补回归断言。

## 10. Acceptance Criteria

**功能验收：**

- 给定今天主动消息达集期上限，那么后续候选被 ignore。
- 给定同主题重复，那么被 dedupe/惩罚抑制。
- 给定重试耗尽，那么 failed 终态不无限重试。

**架构验收：**

- Channel 失败绝不回退到 Character Decision，Decision/生成/发送三者状态解耦。
- 不新增状态、不新增表。

**边界验收：**

- 给定用户发言，那么候选被复位（`reset_proactive_on_user_message`）。

## 11. Testing Plan

- **Unit Test**：四档判定；重试上限；dedupe 幂等。
- **Integration Test**：集期上限 ignore；重试耗尽 failed；用户发言复位。
- **Manual Test**：真实高频触发观察骚扰抑制与暂停行为。
