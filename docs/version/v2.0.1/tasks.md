# v2.0.1 Tasks — Autonomy 2.0（Phase 6）

> Schema 与分层约定对齐 [v2.0.0 phase-6](../v2.0.0/phases/phase-6-autonomy/tasks.md)。依赖图见 [../v2.0.0/dependency-graph.md](../v2.0.0/dependency-graph.md)。
> 本文件是 Autonomy 2.0 的**任务注册表**，只定义任务，不生成 Task Detail、不写代码、不展开实现方案。每个任务后续可单独生成 Task Detail。
> 架构依据：[architecture.md](architecture.md)。补丁视角的轻量建议见 [patch-tasks.md](patch-tasks.md)。

---

## 定位与原则

Autonomy 2.0 的目标是让角色从「用户输入 → AI 回复」升级为「角色拥有持续状态，根据世界变化、关系变化、内部目标主动产生行为」。心智模型为：

```text
World State → Perception → Internal Evaluation → Goal / Motivation
→ Action Planning → Execution → Memory / Reflection Update
```

**架构红线（任何任务不得违反）**：

1. 不破坏已有系统：不改 Memory 核心、不改 Character Schema、不改 World 基础模型、不新建第二套 Agent。
2. Action 必须经过统一入口：`Autonomy Engine → Agent Runtime → Action Execution → Channel`，禁止后台任务直接调用 LLM、禁止 `Scheduler → send_message`。
3. 保持可解释性：所有主动行为须记录「为什么产生 / 基于什么状态 / 使用什么目标 / 影响什么系统」。
4. 复用现有基础设施：`proactive_actions`（Action Outbox）、`trigger_registry`（Trigger 持久化）、`life_loop`/`autonomy_worker`（tick）、`ChannelAdapter`（投递）。不新建 `autonomy_jobs`/`autonomy_queue`/`autonomy_scheduler`，不新增表（唯一结构改动是 `proactive_actions` 增一列 `external_message_id`）。

---

## Capability Map

```text
Phase 1 Foundation:        AUTO-001 Runtime 生命周期与调度收敛
Phase 2 Perception:        AUTO-002 感知与 Trigger 求值
Phase 3 Motivation & Goal: AUTO-003 动机与优先级覆盖
Phase 4 Action Planning:   AUTO-004 决策与候选裁决
Phase 5 Autonomous Exec:   AUTO-005 主动消息投递链路闭合
Phase 6 Reflection & Loop: AUTO-006 结果记录与反思集成
Phase 7 Safety & Control:  AUTO-007 频率控制与可暂停
```

> 依赖：AUTO-005（投递链路闭合）为最高优先，是其余任务的投递落点；AUTO-001/002/003 为横向底座，AUTO-004/006/007 依赖其产出。

---

## Phase 1 — Autonomy Runtime Foundation

## AUTO-001 Runtime 生命周期与调度收敛

- **Priority**: P0
- **Goal**: 建立 Autonomy Runtime 的生命周期管理，收敛双 tick 源，保证「何时检查」职责单一、无重复求值。
- **Scope**:
  - 数据模型：复用 `life_loop`（周期编排）与 `autonomy_worker`（asyncio tick），不新增调度组件。
  - 核心逻辑：明确 `life_loop` 为唯一周期入口，`autonomy_worker` 退化为 `v2_life_loop_enabled=False` 时的兜底；统一 Trigger 的 claim 语义避免重复求值。
  - 系统边界：Scheduler 只回答「什么时候检查」，只产 Trigger，不做决策、不发消息。
- **Dependencies**: v2.0.0 phase-5（Life Loop，LIFE-002 编排底座）、`trigger_registry`。
- **Acceptance Criteria**: 给定 `v2_life_loop_enabled=True`，那么 autonomy 决策仅由 life_loop 触发一次；给定 False，那么 autonomy_worker 兜底；同一 Trigger 不被两个 tick 源重复求值。
- **Architecture Reference**: [architecture.md](architecture.md) §15、§24（Gap G4）。

---

## Phase 2 — Perception System

## AUTO-002 感知与 Trigger 求值

- **Priority**: P0
- **Goal**: 让角色感知时间变化、世界变化、用户行为变化、关系变化，并将感知归一为可求值的 Trigger。
- **Scope**:
  - 数据模型：复用 `trigger_registry`（`trigger_type`/`trigger_key`/`priority`/`cooldown_until`）与 `TriggerSignal` 域模型。
  - 核心逻辑：三类既有 Trigger（`conversation_inactivity` / `scheduled_followup` / `action_due`）的求值闭环；事件驱动（用户消息结束）与时间驱动（tick）统一入口为 `AutonomyEngine`。
  - 系统边界：Trigger 只是「机会」，`Trigger ≠ Action`，不携带「该不该做」判断；世界/关系变化只作为动机补充，不单独构成行动条件。
- **Dependencies**: `trigger_evaluator`、`conversation_service.reset_proactive_on_user_message`、World/Relationship 域事实投影。
- **Acceptance Criteria**: 给定用户长时间未发言，那么产出 `conversation_inactivity` TriggerSignal 且不带决策；给定约定到期，那么产出 `scheduled_followup` 并 claim；给定世界变化，那么仅作为 reason 补充而非独立 Trigger（当前版本）。
- **Architecture Reference**: [architecture.md](architecture.md) §6、§16、§17、§26。

---

## Phase 3 — Motivation & Goal System

## AUTO-003 动机与优先级覆盖

- **Priority**: P1
- **Goal**: 建立内部需求 / 长期目标 / 短期目标 / 优先级的表达，为高优先动机引入覆盖通道。
- **Scope**:
  - 数据模型：复用 `intention` + `reason`（Desire 语义）、`goal_id` + `selected_goal_type`（Goal 语义）、`trigger_registry.priority`。
  - 核心逻辑：为 P0/P1（用户明确要求、有时间承诺的提醒）引入 High Priority Override 语义，覆盖普通冷却，但**不跨静音时段**（除非用户明确要求）；P2/P3 不覆盖。
  - 系统边界：Desire/动机是「角色为什么想做」，与 Trigger（发生了什么）严格区分；不新增独立 Desire 对象，由 `intention` + `reason` 承载。
- **Dependencies**: `autonomy_policy`（八步闸门）、`trigger_registry.priority`、`PROACTIVE_INTENTION_MAP`。
- **Acceptance Criteria**: 给定 P0 `scheduled_followup` 且冷却未过，那么仍放行（覆盖普通冷却）；给定静音时段，那么默认仍拦截；给定 P2/P3 普通 check_in，那么不覆盖冷却。
- **Architecture Reference**: [architecture.md](architecture.md) §8、§14（Gap G8）。

---

## Phase 4 — Action Planning System

## AUTO-004 决策与候选裁决

- **Priority**: P0
- **Goal**: 让角色决定「下一步应该做什么」，输出 `act / wait / ignore` 三值裁决，具备明确的「不行动」能力。
- **Scope**:
  - 数据模型：复用 `AutonomyVerdict`（decision + reason + intention）、`decision_records`（决策可观测）、`proactive_actions`（Action 候选 Outbox）。
  - 核心逻辑：保留「Rule 闸门 + 领域增量」裁决模型（八步闸门 + R1~R5 + W1~W3 + A1/A2）；候选评分采用 Rule（硬闸门，0 LLM）+ LLM（软排序）两层，硬闸门先于任何 LLM 参与。
  - 系统边界：Decision 是 Autonomy 核心，必须能输出「不行动」；Opportunity 与 Desire 是短暂派生值对象，不独立成表，由 `TriggerSignal.context` 承载。
- **Dependencies**: `autonomy_policy`（纯函数裁决）、`autonomy_engine`（Context 快照）。
- **Acceptance Criteria**: 给定关系浅 + 用户可能在工作 + 冷却中，那么 decision=ignore 不发送；给定冷却中/对话中，那么 decision=wait 保留候选下轮重评；给定闸门全通过且存在动机，那么 decision=act 产出 ActionIntent。
- **Architecture Reference**: [architecture.md](architecture.md) §9、§13。

---

## Phase 5 — Autonomous Execution

## AUTO-005 主动消息投递链路闭合

- **Priority**: P0（最高优先）
- **Goal**: 让主动行为真实投递到 Channel（Feishu），闭合「Decision → 生成 → 落库 → 真实发送」全链路，且必须经过 Agent Runtime。
- **Scope**:
  - 数据模型：`proactive_actions` 增一列 `external_message_id`（nullable），区分 `internal_message_id`（messages 行 id）与 `external_message_id`（Feishu 侧 id）。
  - 核心逻辑：`proactive_executor` 在生成文本、落库后调用 `delivery.send_proactive`；生成与发送拆两阶段（生成可重试，失败仅重发不重生成、不重新裁决）；发送成功回填 `external_message_id`，状态 = delivered。
  - 系统边界：Autonomy 只产 Action Intent，文本生成走 `proactive_chain`（角色化表达），投递走 `ChannelAdapter`，禁止 `Autonomy → Feishu` 直连、禁止 Autonomy 直接操作 Memory DB。
- **Dependencies**: FEISHU-005（`delivery.send_proactive` 已交付）、`channel_identity_service.resolve_recipient`、`proactive_chain`、`conversation_service.save_proactive_turn`。
- **Acceptance Criteria**: 给定 approved action，当执行，那么文本生成后真实调用 `send_proactive` 且成功回填 `external_message_id`；给定 Feishu 429/超时，那么仅重发、不重新生成、不重新裁决；给定发送前用户已回来，那么 `_recheck` 后 discarded 不投递。
- **Architecture Reference**: [architecture.md](architecture.md) §21、§28、§20（Gap G1/G2/G3）。

---

## Phase 6 — Reflection & Learning Loop

## AUTO-006 结果记录与反思集成

- **Priority**: P1
- **Goal**: 主动行为结束后产生结果记录、经验总结与后续调整，与 Reflection System 集成但与之解耦。
- **Scope**:
  - 数据模型：复用 `decision_records`（`kind=proactive_autonomy`）、`reflection_runs`/`insights`（长期总结）、trace（`external_message_id` + `channel`）。
  - 核心逻辑：主动行为结果经可观测字段记录「为什么产生 / 基于什么状态 / 使用什么目标 / 发送到哪个 channel / 是否成功」；Reflection 由 `life_loop._step_reflection_check` 独立频控触发，不随每次 autonomy tick 执行。
  - 系统边界：`Reflection → Insight → Context → Autonomy Decision`，禁止 `Autonomy → Reflection → 每次主动行为都反思`；不记录 token/open_id（脱敏）。
- **Dependencies**: `decision_records`、`_step_reflection_check`（REF-003 日桶幂等）、trace 体系。
- **Acceptance Criteria**: 任一 active action 可回答「内部消息 id / 外部消息 id / 发送到哪个 channel / 是否成功 / 为什么产生」；Reflection 执行频率与 autonomy decision 解耦，不随每次 tick 触发。
- **Architecture Reference**: [architecture.md](architecture.md) §25、§31。

---

## Phase 7 — Safety & Control

## AUTO-007 频率控制与可暂停

- **Priority**: P1
- **Goal**: 保证行为频率限制、用户控制、防止无限行动、可暂停，让角色「既能主动又不骚扰」。
- **Scope**:
  - 数据模型：复用 `proactive_actions`（`attempt`/`next_retry_at`/`dedupe_key`）、`trigger_registry.cooldown_until`、静音时段配置。
  - 核心逻辑：Interruption Policy 四档判定（Hard Block → ignore / Soft Block → wait / Allowed → act / High Priority Override → act）；重试上限封顶（`attempt` 超限 → failed 终态，禁止无限重试）；`dedupe_key` + `idempotency_key` 抑制重复发送。
  - 系统边界：核心不变量为「Channel 失败绝不回退到 Character Decision」——Decision 一次、生成可重试、发送可重试，三者状态解耦；用户发言即复位主动行为（`reset_proactive_on_user_message`）。
- **Dependencies**: `autonomy_policy`（闸门）、`proactive_repository`（状态机 + 幂等）、`proactive_executor`（重试模型）。
- **Acceptance Criteria**: 给定今天主动消息达集期上限，那么后续候选被 ignore；给定同主题重复，那么被 dedupe/惩罚抑制；给定重试耗尽，那么 failed 终态不无限重试；给定用户发言，那么候选被复位。
- **Architecture Reference**: [architecture.md](architecture.md) §14、§19、§20、§21、§34。

---

## Milestone（交付序）

```text
M1 Foundation:        AUTO-005（投递链路闭合，最高优先）
M2 横向底座:          AUTO-001 + AUTO-002 + AUTO-003（可并行）
M3 决策与执行:        AUTO-004 → AUTO-006
M4 Safety & Control:  AUTO-007
M5 Acceptance:        回归 + 评估 Gate（对齐 patch-tasks.md PATCH-AUT-05）
```

> 依赖：AUTO-005 先行闭合投递链路，其余任务在此基础上收敛调度、感知、动机、决策、反思与安全控制。AUTO-001/002/003 为横向底座可并行；AUTO-004/006/007 依赖其产出。
