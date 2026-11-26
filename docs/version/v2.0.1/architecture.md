# Autonomy 2.0 — Architecture Design

> 状态：Architecture Design（本阶段只做架构，不实现）
> 版本归属：**v2.0.1 补丁**（对 `docs/version/v2.0.0/` 的投递链路收尾）
> 角色系统通用，不绑定 Asuna 专用逻辑
> 关联：`docs/version/v2.0.0/phases/phase-5-life-loop/`（调度底座）、`phase-6-autonomy/`（Goal 追求）、`docs/version/v1.0.0/v7/autonomy-model.md`、`autonomy-policy.md`

---

## 1. Background（背景）

当前系统已完成 Character / Memory 2.0 / Reflection / Development / Relationship / Life Loop / World / Action / Feishu 集成（FEISHU-001~006）。在此基础上，V7 已落地第一代 Autonomy（`autonomy_engine` + `autonomy_policy` + `proactive_executor` + `trigger_evaluator`），V8/V8.5/V9 追加 World / Relationship / Action 域闸门规则，v2.0.0 通过 `life_loop`（phase-5）统一了周期编排、通过 Goal 层级（phase-6）实现了目标追求。

本设计的目标，是把这套已运行但分散在多个版本增量里的能力，**收敛为一套清晰、边界明确、可扩展、可观测的 Autonomy 2.0 心智模型**，并找出「目标架构」与「当前架构」之间的 Gap。

**核心命题**：角色不是因为用户发消息才存在，而是角色自身也拥有持续运行的生活与行为循环——从"自身状态 → 机会 → 欲望 → 决策 → 行动 → 世界更新 → 主动消息"，但**只有经过严格决策与打扰控制后，才允许触碰 Channel**。

**本补丁的重点**：v2.0.0 已把「何时触发、何时决策、何时生成」设计并实现，但「主动消息真正发到 Feishu」这条投递链路尚未闭环（详见 §28 与 §38 Gap Analysis）。

---

## 2. Goals（目标）

1. 建立从 `Trigger → Opportunity → Desire → Decision → Action` 的清晰心智模型，严格区分每层职责。
2. 复用现有 `proactive_actions` / `autonomy_engine` / `life_loop` / `ChannelAdapter`，**不新建第二套** Proactive Action 系统。
3. 打通"主动决策 → 主动消息 → Feishu 真实投递"这条**尚未闭合**的链路（§28 / Gap G1）。
4. 明确 `internal_message_id` 与 `external_message_id` 语义边界，消除 `proactive_actions.message_id` 混用隐患。
5. 建立轻量候选评分 + 打扰策略（Interruption Policy），让角色既能主动又不骚扰。
6. 保持多用户隔离、幂等、可恢复、可观测、多 Channel 可扩展。

---

## 3. Non-Goals（非目标）

- 不引入 Multi-Agent / MCP / Event Bus / Kafka / Temporal / Celery / Redis Streams / 大规模 Workflow Engine。
- 不为 Autonomy 新建 `autonomy_jobs` / `autonomy_queue` / `autonomy_scheduler`（优先复用 `background_jobs` / `trigger_registry` / `life_loop` worker）。
- 不实现任何新 Channel（只依赖 `app.channels.base`）。
- 不让 Autonomy 直接生成自然语言（角色化表达交给现有 Character / Response Generation）。
- 不让 Autonomy 直接操作 Memory DB（只读经 Application/Service 边界）。
- 本阶段不写代码、不迁移、不加表、不改现有 Service。

---

## 4. Current System（当前系统现状）

### 4.1 已存在模块（代码审计结论）

| 模块 | 位置 | 职责 |
|---|---|---|
| Autonomy Engine | `app/application/autonomy_engine.py` | tick：候选用户枚举 → Trigger 求值 → Policy 裁决 → 入队 → 同 tick 执行 |
| Autonomy Worker | `app/application/autonomy_worker.py` | lifespan 内 asyncio tick 循环 |
| Autonomy Policy | `app/services/autonomy_policy.py` | 纯函数裁决：八步闸门 + R1~R5 + W1~W3 + A1/A2 |
| Trigger Evaluator | `app/services/trigger_evaluator.py` | 三类 Trigger：`conversation_inactivity` / `scheduled_followup` / `action_due` |
| Proactive Executor | `app/services/proactive_executor.py` | approved → 锁内二次校验 → 生成文本 → 落库 → delivered |
| Proactive Repository | `app/repositories/proactive_repository.py` | Outbox 语义 + 状态机 + dedupe 幂等 |
| Proactive Chain | `app/chains/proactive_chain.py` | 主动消息文本生成（角色化表达） |
| Life Loop | `app/application/life_loop.py` | V2.0.0 统一周期编排（phase-5，LIFE-002） |
| Autonomy 域模型 | `app/models/autonomy.py` | `TriggerSignal` / `AutonomyVerdict` / `ProactiveAction` |
| Channel 契约 | `app/channels/base.py` | `InboundMessage` / `OutboundMessage` / `ChannelAdapter` / `SendResult` |
| Feishu Adapter | `app/channels/feishu/adapter.py` | 入站编排 |
| Feishu Delivery | `app/channels/feishu/delivery.py` | 出站：`deliver_reply` / `send_proactive` |
| Trigger Registry | `trigger_registry` 表 | 跨重启持久化 Trigger（`pending/due/fired/done/cancelled`） |

### 4.2 已存在数据库表

- `proactive_actions`：单用户深度 1 主动行为 Outbox，状态机 `candidate/approved/delivered/acked/discarded/failed/expired`。
- `background_jobs`：通用后台任务（`pending/running/done/failed` + `idempotency_key` + `run_at`）。
- `trigger_registry`：Trigger 登记表（`trigger_type` / `trigger_key` unique / `priority` / `cooldown_until` / `attempt_count`）。
- `channel_identities`：`(channel, external_id)` → `internal_user_id` + `session_id`。
- 其余：`conversations` / `messages` / `memories` / `memory_candidates` / `memory_links` / `worlds` / `world_events` / `action_records` / `insights` / `reflection_runs` / `decision_records` / `loop_runs` 等。

### 4.3 现有链路（已在运行）

```
autonomy_worker / life_loop (tick)
    ↓
autonomy_engine.tick
    ↓ 对每个 user
trigger_evaluator（inactivity / scheduled_followup / action_due）
    ↓ TriggerSignal
autonomy_policy.evaluate（八步闸门 + R1~R5 + W + A）
    ↓ AutonomyVerdict(act)
proactive_repository.enqueue → ProactiveAction(candidate)
    ↓ 同 tick
proactive_executor.execute
    ↓ proactive_chain.generate（角色化文本）
conversation_service.save_proactive_turn（落库 messages，is_proactive=True）
    ↓ delivered（message_id = 内部 message row id）
```

**关键断点**：`proactive_executor` 在 `delivered` 之后**没有调用 `delivery.send_proactive`**。主动消息在内部被标记为"已投递"，但 Feishu 真实发送尚未接通。`delivery.send_proactive` 已作为独立能力交付（FEISHU-005），当前**无生产调用方**（grep 仅测试调用）。

---

## 5. Autonomy Mental Model（心智模型）

Autonomy 2.0 的核心，是把"角色什么时候主动行动"拆成五层严格分离的语义：

```text
┌─────────────────────────────────────────────────────────────┐
│ Character Layer（personality / emotion / relationship / desire）│
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Autonomy Engine                                              │
│   Trigger（为什么现在有一个值得考虑的事件）                  │
│   → Opportunity（当前可能值得关注的机会）                    │
│   → Desire（角色为什么想做这件事）                           │
│   → Decision（现在是否应该行动）                             │
│   → Action Intent（决定执行什么行为，不含自然语言）          │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Action Execution（World / Character / Message Generation）    │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Channel Adapter（Feishu / Web / Future）                     │
└─────────────────────────────────────────────────────────────┘
```

**四个禁止**（架构红线，任何阶段不得违反）：

1. 禁止 `Autonomy → Feishu`（绕过 ChannelAdapter 与角色生成）。
2. 禁止 `Autonomy → new Chat Pipeline`（形成第二套角色生成系统）。
3. 禁止 `Scheduler → send_message`（Scheduler 只产 Trigger）。
4. 禁止 `Autonomy → 直接操作 Memory DB`（只能经 Application/Service 边界）。

---

## 6. Trigger（触发器）

**回答**："为什么现在有一个值得考虑的事件？"

Trigger 只是**机会**，`Trigger ≠ Action`。不携带"该不该做"判断，更不携带"说什么"。

当前三类 Trigger（`models/autonomy.py` 的 `TriggerType`）：

| Trigger | 语义 | 现有来源 |
|---|---|---|
| `conversation_inactivity` | 用户长时间未发言 | `trigger_evaluator.evaluate_inactivity` |
| `scheduled_followup` | 约定时间/事件到期 | `trigger_evaluator.poll_due_followup` |
| `action_due` | 世界中的 reminder/appointment 到期 | `trigger_evaluator.poll_due_actions` |

**目标扩展的 Trigger 类型**（后续版本，非本补丁实现）：

```text
time_reached / user_inactive / memory_recall / relationship_change
world_change / life_loop_event / unfinished_action / scheduled_reminder
```

Trigger 只回答"现在是否值得考虑一次"，输出 `TriggerSignal`。是否扩展枚举取决于未来 Phase 是否需要新触发源，**不应为枚举完整而一次性全加**。

---

## 7. Opportunity（机会）

**回答**："当前可能值得角色关注的一个机会。"

Opportunity 是对 Trigger 的一层**语义化包装**——把"裸信号"转成"一件具体的事"。Opportunity **不能直接发消息**。

```
Trigger: scheduled_time_reached → Opportunity: "现在可能需要提醒用户"
Trigger: user_inactive(8h)      → Opportunity: "是否应该主动联系用户？"
```

**架构决策**：Opportunity **不独立成表或持久化对象**。理由：它是 Trigger + Context 的短暂派生，生命周期极短（一次 Decision 内消费完），无"待办/重试/跨进程恢复"语义（跨重启恢复由 `trigger_registry` 兜底）。因此 Opportunity 是 `AutonomyEngine` 内部的值对象，由 Trigger + 最小 Context 就地组装，`TriggerSignal.context` 承载"机会摘要"。

---

## 8. Desire（欲望）

**回答**："角色为什么想做这件事？"

必须与 Trigger 严格区分：

```
Trigger: 用户 8 小时没说话
Desire:  想知道用户现在怎么样        ← 正确
```
```
❌ 错误：Trigger = 给用户发消息
```

当前 Desire 表达是**隐式**的——藏在 `AutonomyVerdict.intention` 里（`check_in` / `repair_rapport` / `reconciliation_check_in` / `reconnect_check_in` 等），由 `PROACTIVE_INTENTION_MAP` 从 Goal 类型映射：

```
user_care    → check_in
relationship → repair_rapport
```

**架构决策**：Desire 用 `intention` 字段承载（语义等价），不新增独立对象；"为什么想做"由 `AutonomyVerdict.reason`（≤60 字结构化单句）表达。当前 `intention` 白名单偏窄，**扩展方向**是覆盖"想继续昨天话题 / 想分享刚发生的事 / 想确认用户是否回来 / 想推进生活计划"，属后续版本的 intention 白名单扩充，非本补丁表结构改动。

---

## 9. Decision（决策）

**回答**："现在是否应该行动？为什么？收益？打扰成本？是否已做过类似？是否有更好行动？"

Decision 是 Autonomy 的**核心**，必须能输出三种结果，尤其是"不行动"：

```text
AutonomyVerdict.decision ∈ { act, wait, ignore }
```

- `act`：现在行动，产出 `ActionIntent`。
- `wait`：条件未满足，保留候选下轮再评（冷却中、用户正在对话、上一条未处理）。
- `ignore`：明确不行动（静音时段、关系尚浅、无主动动机、R1 冲突期克制）。

> **Autonomy ≠ 定时任务系统**。Scheduler 只产 Trigger，真正决定是否行动的是 `autonomy_policy.evaluate`。

当前 `autonomy_policy.py` 已实现**纯函数八步闸门**（按序短路）：

```
generating? → 静音时段? → 冷却通过? → 集期上限? → 已有 active? →
关系深度? → 角色状态不宜? → 有无主动动机?
```
再叠加 V8.5 R1~R5（relationship 域）、V8 W1~W3（world 域，只追加理由不拆闸门）、V9 A1/A2（action 域，只追加理由不拆闸门）。

这套"Rule 闸门 + 领域增量"模型正确、应保留。§13/§14 在此之上补充 Interruption Policy 与候选评分。

---

## 10. Action（行动）

**回答**："Decision 最终决定执行什么行为？"

```
Decision: "应该提醒用户"   →   Action: send_message("该起来啦")
```

当前 `ProactiveAction` 模型（`models/autonomy.py`）：

```python
class ProactiveAction:
    id / user_id / character_id / session_id
    type            # 目前仅 "send_message"
    trigger_type / dedupe_key / goal_id / intention / reason
    payload_text    # 生成后的文本（执行期回填）
    status          # candidate/approved/delivered/acked/discarded/failed/expired
    attempt / next_retry_at
    created_at / updated_at / delivered_at
    message_id      # ⚠️ 当前存内部 message row id，非 external message id
    acked_at
```

**关键结论**：`proactive_actions` 这一张表**同时承载 Desire / Decision / Action / Execution / Delivery 五个阶段的记录**，是当前模型最大的职责混合点。

**架构定性**：

| 概念 | 在 `proactive_actions` 的体现 | 建议 |
|---|---|---|
| Desire | `intention` + `reason` | ✅ 保留 |
| Decision | `status`（approved 即已裁决）+ `reason` | ⚠️ 决策快照已进 `decision_records`，表内仅存结果 |
| Action | `type` + `payload_text` | ✅ 保留 |
| Execution | `status` 流转 + `attempt`/`next_retry_at` | ✅ 保留 |
| Delivery | `delivered_at` + `message_id` + `acked_at` | ⚠️ 语义需澄清（见 §20） |

**结论**：`proactive_actions` 作为"主动行为 Outbox 生命周期表"合理，**不需拆多表**。需做的是：明确它属"Action 及之后 Execution/Delivery 层"，而 Trigger/Opportunity/Desire/Decision 的**过程态**由 `trigger_registry`（Trigger）+ `decision_records`（Decision 可观测）分别承载。

---

## 11. Autonomy Engine（自治引擎）

独立引擎，职责边界：

```text
Trigger → Context → Opportunity → Desire → Decision → Action Intent
```

它**不负责**：生成自然语言、直接发消息、操作 Memory DB。

引擎内部对象与持久化策略：

| 对象 | 是否独立成表 | 理由 |
|---|---|---|
| `AutonomyTrigger`（=`TriggerSignal`） | 过程态进 `trigger_registry`，快照在 `context` | 需跨重启恢复 |
| `AutonomyOpportunity` | ❌ 不建表 | 短暂派生值对象，`context` 承载 |
| `AutonomyDesire` | ❌ 不建表 | 由 `intention` + `reason` 承载 |
| `AutonomyDecision`（=`AutonomyVerdict`） | 可观测进 `decision_records` | 复用现有决策记录 |
| `AutonomyAction`（=`ProactiveAction`） | ✅ 复用 `proactive_actions` | 需 Outbox + 状态机 + 重试 |

**结论**：不为了抽象而抽象。现有 `TriggerSignal` / `AutonomyVerdict` / `ProactiveAction` 已覆盖引擎所需全部对象，Opportunity 与 Desire 是值对象/字段，无需新表。

---

## 12. Context（上下文）

Autonomy 做 Decision 不能只看 Trigger，需 `AutonomyContext`。但**禁止每次 tick 把整个数据库和全部 Memory 加载进 LLM**。

当前 `_snapshot_for`（`autonomy_engine.py`）已构建 `PolicySnapshot`，含：

```text
Character State（mood / intensity）
Relationship（intimacy / tension / trust / comfort / respect / stage / conflict / neglect）
Scene（current_activity）
Goal（selected_goal_type / goal_id）
Recent Conversation（session tail）
World facts（world_engine.collect_facts）
Action facts（action_engine.collect_facts）
Recent Proactive（last_proactive_at / attempt_count）
Relationship unlocks / patterns
```

**目标设计**：Context 明确三层选择机制，避免无界加载：

```text
AutonomyContext
  ├─ Context Selection（选哪些域）
  ├─ Context Budget（总量上限）
  └─ Priority（域的优先级与截断顺序）
```

**优先级建议**（高→低，超预算即截断）：

1. **硬信号**：当前时间、是否静音、用户是否对话中、是否有 active action（闸门必需）。
2. **关系与角色态**：intimacy / tension / mood / current_activity。
3. **近期对话尾**：最近 N 条消息。
4. **World / Action 事实**：只取 salient events（`collect_facts` 已过滤）。
5. **显著记忆**：仅当 Life Loop `memory_retrieval` 产出 digest 时注入（`memory_digest_var` contextvar 已实现）。

**现有实现已基本满足**：`PolicySnapshot` 就是"预选择、有界"的 Context；Memory 通过 `life_loop_context.memory_digest_var` 按显著度注入。目标只需**显式化**预算与优先级，不引入新 Context 检索框架。

---

## 13. Candidate Scoring（候选评分）

同一 tick 存在多候选时，轻量评分。设计为 **Rule（过滤）+ LLM（主观判断）** 两层：

### 13.1 Rule 层（过滤明显不该做的）

```text
candidate
├─ urgency             # 紧急度
├─ relevance           # 相关度
├─ relationship_value  # 关系价值
├─ expected_value      # 预期收益
├─ interruption_cost   # 打扰成本
├─ repetition_penalty  # 同主题重复惩罚
├─ recent_action_penalty # 近期主动行为惩罚
└─ confidence          # 置信度
```

最终得到 `score`，但**不做纯数学规则**。

### 13.2 两层配合（推荐）

```text
Rules → 过滤明显不该做的（硬闸门，0 LLM）
LLM   → 判断角色主观上是否值得做（软判断，1 次 LLM）
```

- **Rule 硬闸门**：静音时段、冷却中、对话中、关系尚浅、角色状态不宜——确定性规则直接 `ignore`/`wait`，不让 LLM 参与（否则不可预测、不可测试）。
- **LLM 软判断**：规则闸门全通过、存在多候选时，用 LLM 在"角色主观更想做哪个"间做一次选择，输出带 `confidence` 的排序。

**现有状态**：`autonomy_policy` 已是纯 Rule 闸门（0 LLM）。**目标缺口**是"多候选 LLM 软排序"——当前单候选短路（一个 tick 至多一个 intention）。属后续版本增强（G5），非本补丁表结构问题。

---

## 14. Interruption Policy（打扰策略）

**核心体验问题**：角色不能"每隔 5 分钟：你在干嘛呀？"。

**输入维度**（`PolicySnapshot` + `autonomy_policy` 已覆盖大部分）：

```text
用户最近是否活跃        → generating / user_active
用户是否刚刚回复        → autonomy_min_user_reply_gap_minutes
距离上次主动消息多久    → last_proactive_at + effective_interval_minutes
今天主动消息次数        → attempt_count + max_attempts_per_episode
相同主题是否重复        → dedupe_key（部分覆盖）
当前时间                → in_quiet_hours
用户是否休息时间        → in_quiet_hours
当前行为重要程度        → selected_goal_type + goal_degraded
关系阶段                → stage / intimacy / tension
```

**四档判定**：

```text
Hard Block             → ignore（静音、关系尚浅、无动机、R1 冲突期克制）
Soft Block             → wait（冷却中、对话中、上一条未处理）
Allowed                → act（闸门全通过且存在动机）
High Priority Override → act（用户明确要求的提醒 P0/P1，覆盖普通冷却）
```

**优先级定义**（结合当前系统）：

| 优先级 | 含义 | 现有映射 |
|---|---|---|
| **P0 Critical** | 用户明确要求、有时间承诺的提醒 | `scheduled_followup` + `action_due`（reminder） |
| **P1 Important** | 未闭环重要委托、关系冲突召回、疏远召回 | `action_due`、R1/R5 放行 |
| **P2 Normal** | Life Loop 生活事件、World 事件 | world/action facts 追加理由的普通 proactive |
| **P3 Casual** | "突然想和用户聊天" | `conversation_inactivity` 触发的 check_in |

**现状缺口**：现有 `autonomy_policy` 有静音/冷却/集期上限三档闸门，但**无显式优先级 override 通道**——所有 trigger 走同一套冷却。P0/P1 的"用户明确要求提醒"目前依赖 `trigger_type` 区分（`scheduled_followup`/`action_due` 先于 `inactivity` 被 poll），但冷却闸门对它们一视同仁。**目标**：为 P0/P1 引入"高优覆盖"语义，但即使 P0 也要尊重静音时段（除非用户明确要求跨静音提醒）。对应 Gap G8。

---

## 15. Scheduler（调度器）

Scheduler 职责**严格受限**——只回答"什么时候检查？"。

```text
正确：Scheduler → Trigger → Autonomy Engine
错误：Scheduler → send_message()
```

**现有实现**：

- `autonomy_worker.run_autonomy_worker`：独立 asyncio tick 循环（`autonomy_tick_seconds`）。
- `life_loop.run_life_loop_worker`：V2.0.0 统一周期（`v2_life_loop_tick_seconds`），其 `decision` 步骤内部调用 `autonomy_engine.tick`。

**架构结论**：Scheduler 已存在且职责正确。目标架构中 Scheduler 是"时间驱动 tick 源"，非新组件。需厘清 `autonomy_worker` 与 `life_loop` 两个 tick 源的关系（见 §24），避免同一 Trigger 被重复求值（当前已通过 `trigger_registry` claim 语义 + `dedupe_key` 部分缓解）。

---

## 16. Event-driven Trigger（事件驱动）

```
用户发送消息 → 对话结束 → 产生新的 Opportunity
```

现有：`conversation_service.reset_proactive_on_user_message`（用户发言复位）+ `chat_pipeline` 结束后的 goal review。事件驱动不单独建表，复用"用户消息结束"钩子点，产出的 Trigger 走同一 `trigger_registry` 或就地求值。当前 `evaluate_inactivity` 已是事件驱动（对话尾）与时间驱动（idle 时长）的混合。

---

## 17. Time-driven Trigger（时间驱动）

```
Scheduler → Life Loop Tick → 检查是否有新 Opportunity
```

现有：`life_loop._collect_work_users` → `_run_user_cycle` → `_step_decision` → `autonomy_engine.tick`。

Delayed Action（"一个小时后提醒我"）：`register_followup`（写 `trigger_registry`，`due_at` 未来）→ 到点 `poll_due_followup` claim → `scheduled_followup` TriggerSignal → Decision → send。**已闭环**（LIFE-001 表通道）。

---

## 18. Lifecycle（生命周期）

```text
Event-driven（用户消息结束）+ Time-driven（Scheduler/Life Loop tick）+ Delayed Action（约定到期）
```

三者统一入口都是 `AutonomyEngine`，区别只在 Trigger 的**来源**与**到达时机**。已由 §16/§17 覆盖。

---

## 19. State Machine（状态机）

当前 `proactive_repository._TRANSITIONS`：

```text
candidate ──approved──▶ approved ──delivered──▶ delivered ──acked──▶ acked
    │                     │                          │
    └──discarded          ├──failed──▶ failed        └──expired
                          │   │
                          │   ├──retry▶ approved（failed 到期）
                          │   └──discarded
                          └──candidate（回滚）
```

异常态：`rejected`（归入 `discarded`）、`cancelled`（用户发言时 `discarded` 承担）、`failed`、`expired`（delivered 超 24h 未 acked）。

**架构结论**：**现有状态机已足够，无需新增状态**。`rejected` 与 `cancelled` 语义已由 `discarded` 统一承载，再拆 `rejected` 只会增加无意义状态与迁移分支。**不要为完整而增加状态。**

唯一需明确的是 `delivered` 语义：当前表示"内部消息已落库"，**不表示"Feishu 已送达"**。此缺口在 §20/§28 处理。

---

## 20. Idempotency（幂等）

异步系统核心：同一 Trigger 可能被求值两次，同一主动行为不能重复发送。

**现有机制**：

| 字段 | 作用 | 充分性 |
|---|---|---|
| `proactive_actions.dedupe_key` | 同 key 已处理过则拒绝入队 | ✅ 充分 |
| `proactive_actions.attempt` | 重试计数 | ✅ |
| `proactive_actions.next_retry_at` | 重试调度 | ✅ |
| `proactive_actions.message_id` | 投递后消息 id | ⚠️ **语义混用** |
| `trigger_registry.trigger_key` unique | Trigger 级幂等（claim） | ✅ |
| `delivery._delivered` 内存去重 | Feishu 发送级幂等（TTL） | ⚠️ 进程内存，重启丢失 |
| `OutboundMessage.idempotency_key` | 出站幂等键 | ✅ 契约已定义 |

**关键澄清（`internal_message_id` vs `external_message_id`）**：

```text
internal_message_id  = messages 表主键 id（save_proactive_turn 返回）
external_message_id  = Feishu 侧 message_id（client.send_message 返回）
```

当前 `proactive_actions.message_id` 存的是 **internal message row id**，两个概念不能混用。

**目标设计**（本补丁最小改动）：

1. 保留 `proactive_actions.message_id` 为 **internal_message_id**（指向 messages 行）。
2. 新增 `proactive_actions.external_message_id`（nullable），存 Feishu 发送成功后 `SendResult.external_message_id`。
3. `delivery._delivered` 内存去重有重启丢失风险——对 Feishu 而言，`idempotency_key`（= `dedupe_key`）作为 `OutboundMessage.idempotency_key` 传递即可在 Feishu 侧兜底幂等，内存去重作为进程内快速路径。

> 结论：`dedupe_key` + `attempt` + `next_retry_at` 已基本足够；**唯一缺口是 `external_message_id` 缺失**。

---

## 21. Retry / Failure Model（重试与失败模型）

五类失败分别处理，**核心原则：Channel 失败不得重新执行 Character Decision**。

```text
1. Decision Failed     → 本次不产 action，下轮重评（无副作用，自然恢复）
2. Action Failed       → _fail_for_retry：attempt+1，超限 → failed 终态
3. Generation Failed   → 文本为空 → _fail_for_retry，重试生成（不重跑 Decision）
4. Channel Failed      → Feishu 429/超时 → 仅重发，不重新生成、不重新裁决
5. Retry Exhausted     → failed 终态，记 observability outcome
```

**现有实现的正确部分**：

- `proactive_executor._fail_for_retry`：生成失败/目标消失 → 重试，超限终态 failed。
- `_recheck_failed_reason`：执行前二次校验（用户是否已回来/是否静音）。
- `_goal_description`：目标消失 → 视同生成失败，不发送。

**目标缺口（与 §28 强相关）**：当前 `proactive_executor` 把"生成文本 + 落库"当作一次原子执行，一旦加入 Feishu 发送，需把"生成"与"发送"拆成两阶段：

```text
生成阶段（可重试，失败 → 回 candidate/failed）
  ↓ 成功 → 落库 internal_message_id → 状态 = generated（或 delivered 内部语义）
发送阶段（可重试，失败 → 仅重发，不重生成）
  ↓ 成功 → external_message_id 回填 → 状态 = delivered
```

> 现有 `delivered` 若继续表示"内部落库"，则需在 `delivered` 与 Feishu 成功间新增可辨别的中间态；**或**重定义 `delivered` = "Feishu 已成功投递"，另设内部落库为独立字段。具体采用哪种，属本补丁落地时的最小重构决策，本架构记录分歧点，不直接改。

---

## 22. Character Integration（角色集成）

**Character 不能被 Autonomy 绕过**。禁止 `Autonomy → LLM → Feishu` 形成第二套角色生成系统。

```text
正确：Autonomy → Action Intent → Existing Character/Response Generation → Channel Adapter
```

现有 `proactive_chain.generate(goal_description, intention, recent, ...)` 已走角色化主动消息生成链，`proactive_executor` 只产 Action、文本由 chain 生成——**方向正确**。需确保后续任何新 Action 类型（如 `perform_world_action`）也走"Action Intent → 现有执行层"，而非 Autonomy 直接调 LLM。

---

## 23. Memory Integration（记忆集成）

Autonomy 可**读取**相关记忆，但主动行为本身**是否写入 Memory 需明确**。

**五种语义必须区分**：

```text
Event            → 世界/对话中发生的事（world_events / messages）
Memory           → 值得长期记住的事实（memories / memory_candidates）
Preference       → 用户持续偏好（"每天 9 点提醒我"）
Commitment       → 角色对用户承诺（"我答应提醒你"）
Scheduled Action → 一次性定时行动（trigger_registry 的 scheduled_followup）
```

**规则**：

- "我今天主动提醒了用户"这一**事件**通常**不应**成为长期 Memory（transient）。
- "用户明确说'你每天早上 9 点提醒我'"应形成 **Preference / Commitment**，据此生成**可重复的 Scheduled Action**（而非一次性 followup）。
- 主动行为**读取**记忆：经 Life Loop `memory_retrieval`（显著度门槛）注入，非每次 tick 全量检索。

**现状缺口**：`register_followup` 只登记**一次性** followup；"可持续偏好/commitment → 重复 scheduled action"链路**尚未建立**（G6，后续版本，不在本补丁）。

---

## 24. Life Loop Integration（生活循环集成）

**Life Loop ≠ Autonomy**。

```text
Life Loop → 产生生活事件 / 状态变化
Autonomy  → 判断是否需要主动行为
```

```
早晨到来 → Life Loop → morning state → Autonomy："今天是否值得说早安？" → Decision
```

**现有实现**：`life_loop`（phase-5）是编排层，其 `decision` 步骤**内部调用** `autonomy_engine.tick`。同时 `autonomy_worker` 也作为独立 tick 源存在。

**架构结论**（需在本补丁明确，标记为 G4）：

- **目标形态**：`autonomy_worker` 与 `life_loop` **二选一作为主驱动**，避免双 tick 源重复求值。推荐以 `life_loop` 为唯一周期入口（已含 Idle 短路 + 预算闸 + 维护步骤），`autonomy_worker` 退化为 `v2_life_loop_enabled=False` 时的轻量兜底。
- Life Loop 负责"生活时刻/状态变化"的**产生**，Autonomy 负责"是否因此主动行动"的**判断**——职责已分离，但 tick 源去重需收敛。

---

## 25. Reflection Integration（反思集成）

Reflection **不应每次 Autonomy tick 都执行**。

```text
Reflection → 长期总结 / Insight
Autonomy   → 当前是否行动
```

正确：`Reflection → Insight → Context → Autonomy Decision`；错误：`Autonomy → Reflection → 每次主动行为都反思`。

**现有实现已正确**：`life_loop._step_reflection_check` 有独立频控（`v2_life_loop_reflection_check_interval_minutes` + REF-003 日桶幂等），与 Autonomy decision 解耦。

---

## 26. World Integration（世界集成）

World 产出 `World Event`（鸡蛋吃完、天气变化、料理完成、行动完成），可成为 Autonomy Opportunity。

**现有实现**：`autonomy_policy._apply_world_adjustments`（W1~W3）与 `_apply_action_adjustments`（A1/A2）**只追加 reason、不拆闸门**——正确设计：World 事件提供"动机补充"，但**不单独构成行动条件**。

**目标**：World 事件驱动的主动行为（做完饭→想告诉用户）目前只体现在 reason 追加，尚未有显式 `world_change` Trigger 类型（`trigger_registry` 仅三类）。需扩展 `TriggerType` 枚举（G7，后续版本）。

---

## 27. Channel Integration（通道集成）

Autonomy **只能依赖 `app.channels.base`**，禁止 `from app.channels.feishu import ...`。

```text
Autonomy → ChannelAdapter → FeishuAdapter
未来：Autonomy → ChannelAdapter → { Feishu / Web / Telegram / Discord }
```

现有 `channels/base.py` 已定义：`InboundMessage` / `OutboundMessage` / `RecipientRef` / `SendResult` / `ChannelAdapter(Protocol)`。`FeishuChannelAdapter` 已实现 `ChannelAdapter.send`。**契约已满足**。Autonomy 侧只需把"主动消息"表达为 `OutboundMessage`（无 `reply_ref`、带 `idempotency_key`）交由 ChannelAdapter 发送，`delivery.send_proactive` 已做此事。

---

## 28. Feishu Integration（飞书集成）

**主动消息目标解析**：

```text
internal_user_id → Channel Identity → channel → external_id
```

现有 `channel_identity_service.resolve_recipient(internal_user_id, channel)` 已实现：

```text
internal_user_id → channel_identities 表 → (channel=feishu, external_id=open_id)
```

Autonomy **不知道** open_id / Feishu message API / token——全部封装在 `channel_identity_service` 与 `client` 之后。

**Feishu Proactive Message 接入链路（目标）**：

```text
Autonomy Decision(act)
  → Action Intent（type=send_message，dedupe_key）
  → proactive_executor 生成文本（proactive_chain）
  → save_proactive_turn → internal_message_id
  → delivery.send_proactive(internal_user_id, text, idempotency_key=dedupe_key)
     → resolve_recipient → FeishuChannelAdapter.send → client.send_message
     → SendResult(external_message_id)
  → 回填 external_message_id → 状态 = delivered
```

**当前断点（Gap 核心）**：`proactive_executor.execute` 在 `save_proactive_turn` 后**未调用 `delivery.send_proactive`**。主动消息已落库、标记 delivered，但 Feishu 未实际发送。`delivery.send_proactive` 作为能力已交付（FEISHU-005），当前**无生产调用方**。

这是 Autonomy 2.0 需要闭合的**首要链路**，也是 §20/§21 中 internal/external message_id 区分、生成/发送两阶段拆分的落点。

---

## 29. Database（数据库设计）

| 表 | 结论 | 说明 |
|---|---|---|
| `proactive_actions` | **Modify** | 加 `external_message_id`（nullable），其余复用 |
| `background_jobs` | **Reuse** | 通用后台任务，见 §30 |
| `memories` / `memory_candidates` / `memory_links` | **Reuse** | 只读 |
| `conversations` / `messages` | **Reuse** | 主动消息落库 messages（is_proactive=True） |
| `channel_identities` | **Reuse** | 目标解析 |
| `trigger_registry` | **Reuse** | 可能扩展 `trigger_type` 枚举 |
| `decision_records` | **Reuse** | Decision 可观测（`kind=proactive_autonomy`） |
| `loop_runs` / `worlds` / `world_events` / `insights` / `reflection_runs` | **Reuse** | 事实来源 / 记账 |
| **New Table** | **不需要** | 现有表 + `external_message_id` 一列即可支撑 |

**结论**：**默认不新增表**。唯一结构改动是 `proactive_actions` 增一列 `external_message_id`，以及可选地扩展 `trigger_registry.trigger_type` CheckConstraint（若引入 `world_change` 等新 Trigger）。

---

## 30. Background Jobs（后台任务模型）

**优先复用 `background_jobs`，不新建 `autonomy_jobs`/`autonomy_queue`/`autonomy_scheduler`。**

现有 `background_jobs`：`job_type / payload / status / attempts / run_at / idempotency_key(unique) / last_error`。

**结论**：

- `background_jobs` 适合一次性、可延迟、需幂等的后台任务。
- 但当前 delayed action 已由 `trigger_registry`（`due_at` + claim）承担，语义更贴近"Trigger 到点求值"，且已与 `life_loop`/`autonomy_engine` 打通。
- 因此 **Autonomy 不需新建任何队列/调度基础设施**。`trigger_registry`（Trigger 持久化）+ `proactive_actions`（Action Outbox）+ `life_loop`/`autonomy_worker`（tick）已构成完整执行模型。`background_jobs` 仅在"需与 Trigger 无关的通用延迟任务"时用。

**执行模型**：异步 tick + Outbox：

```text
同步部分（tick 内）：Trigger 求值（纯规则）→ Policy 裁决（纯函数）→ 入队（落库）
异步部分（executor）：文本生成（LLM）→ 落库 → Feishu 发送（网络，可重试）
```

LLM/网络延迟在 `proactive_executor` 内消化，不阻塞聊天请求。多用户并发由 `get_user_write_lock` 串行化（单用户深度 1）。失败重试由 `attempt`/`next_retry_at` 驱动。服务重启恢复由 `proactive_actions`（Outbox 持久化）+ `trigger_registry`（claim）保证。重复执行由 `dedupe_key` + `idempotency_key` 抑制。

---

## 31. Observability（可观测性）

Autonomy Trace 回答：

```text
为什么产生这个 Trigger？→ trigger 类型 + dedupe_key + context
为什么是 Opportunity？→ opportunity 摘要（context 内）
角色为什么想做？→ intention + reason
为什么执行/不执行？→ decision + reason + outcome
发送到哪个 Channel？→ channel
发送是否成功？→ SendResult + external_message_id
```

**关联字段**：`trace_id / user_id / trigger_id / action_id / channel`。

现有：`DecisionRecord(kind=proactive_autonomy, input_snapshot, decision, reason, outcome)` + `TurnTraceSession`（`TraceKind.AUTONOMY_TICK` / `TraceKind.PROACTIVE`）。**已满足**。需补充 `external_message_id` 与 `channel` 字段在 trace 中的记录（随 §28 链路闭合一并补齐）。

**不记录**：敏感信息、token、Feishu token、open_id（记录脱敏形式即可）。

---

## 32. Security / Isolation（安全与隔离）

**User A 的 Autonomy 永不访问 User B 的数据。**

所有读写按 `internal_user_id` 隔离：

| 数据 | 隔离方式 | 结论 |
|---|---|---|
| proactive_actions | `user_id` 过滤 | ✅ |
| trigger_registry | `user_id` 过滤 | ✅ |
| memories / world / relationship | 各 repository 按 `user_id`/`internal_user_id` 过滤 | ✅ |
| channel_identities | `(channel, external_id)` → `internal_user_id` | ✅ |
| goal / scene / state | `user_id` / `session_id` 过滤 | ✅ |

`autonomy_engine.tick` 遍历 `list_user_ids()`，对每 user 单独处理，全程用该 `user_id` 取数——**无跨用户泄露**。未来若引入"全局候选评分/调度"，必须保证候选 context 组装绑定单一 `internal_user_id`。

---

## 33. Dependency Direction（依赖方向）

```text
Character Layer（最低，不依赖 Autonomy）
    ▲
Autonomy Engine（依赖 Character 的读取，不反向）
    ▲
Action Execution（World / Character / Message）
    ▲
Channel Adapter（依赖 base，不依赖任何上层）
```

- `app.channels.base`：零 `app.*` 依赖（已满足）。
- Autonomy 依赖 `app.channels.base` 的 `OutboundMessage`/`ChannelAdapter`，**不 import 具体渠道**。
- Autonomy 不 import `app.channels.feishu`（当前 `autonomy_engine`/`proactive_executor` 均未 import feishu，✅；feishu 模块也明确不 import Autonomy，R3）。
- 所有能力经现有 Application/Service 边界完成，不直接操作 DB（✅）。

---

## 34. Failure Handling（失败处理）

```text
Decision 失败    → 无副作用，下轮自然重评
Action 入队失败  → 本次不投递，下轮可重评（dedupe 保证不重复）
生成失败         → _fail_for_retry，重试生成（不重跑 Decision）
落库失败         → 回 candidate，下 tick 重试
Feishu 429/超时  → 仅重发，不重新生成、不重新裁决（幂等键兜底）
重试耗尽         → failed 终态，outcome=failed
用户已回来       → _recheck 后 discarded（竞态，见 §35 场景 6）
```

**核心不变量**：**Channel 失败绝不回退到 Character Decision**。Decision 一次，生成可重试，发送可重试，三者状态解耦。

---

## 35. Typical Scenarios（典型场景）

### 场景 1：主动早安
```
新的一天 → Life Loop → morning state → Trigger(time_reached)
→ Opportunity("说早安") → Desire(关心) → Decision(act, P2)
→ proactive_chain 生成 → 落库 → send_proactive → Feishu
```
（`time_reached` 是目标 Trigger 类型，属后续版本。）

### 场景 2：用户要求提醒
```
用户："一个小时后叫我" → Commitment → register_followup（trigger_registry，due_at=+1h）
→ 一小时后 poll_due_followup claim → scheduled_followup Trigger
→ Decision(act, P0) → send → Feishu
```
（**已闭环**，LIFE-001 表通道。）

### 场景 3：用户长时间未联系 → **不行动**
```
user_inactive 8h → Opportunity("是否主动联系")
→ Decision：关系浅 + 可能在工作 + 冷却 → ignore → 不发送
```
**证明 Autonomy 必须具备"不行动"能力**——`decision ∈ {act, wait, ignore}` 已实现。

### 场景 4：角色刚完成一件事
```
World Action → World Update → Opportunity("饭做好了") → Decision → 主动消息
```
（需 `world_change` Trigger，属后续版本 G7。）

### 场景 5：重复消息抑制
```
昨天："你今天怎么样？" 今天又准备发同样内容
→ Recent Action Penalty / dedupe_key / attempt 上限 → Reject(ignore)
```
（`dedupe_key` + `attempt_count` + `max_attempts_per_episode` 已部分覆盖，同主题语义重复需 LLM 软判断或主题指纹，属后续增强。）

### 场景 6：用户主动回来（竞态）
```
Autonomy 原本准备主动联系 → 用户突然发消息
→ reset_proactive_on_user_message：delivered→acked，candidate→discarded
→ 进入正常 Chat Pipeline
```
（**已实现**。需在 Feishu 发送阶段补充：若发送前用户已回来，`_recheck_failed_reason` 的 `user_active` 分支丢弃。）

---

## 36. Future Extension（未来扩展）

- 多 Channel：Web/Telegram/Discord，实现 `ChannelAdapter` 接入，Autonomy 零改动。
- 新 Trigger 类型：`world_change` / `life_loop_event` / `relationship_change` / `memory_recall`，扩展 `TriggerType` + `trigger_registry` CheckConstraint。
- 多候选 LLM 软排序（G5）。
- Preference/Commitment → 重复 Scheduled Action（G6）。
- 生成/发送两阶段彻底拆分 + `external_message_id` 回填（本补丁 P1~P3）。

---

## 37. Implementation Boundaries（实现边界）

本阶段**只做架构**，明确禁止：

- Coding / Migration / 新增表 / 修改 Python / 修改现有 Service / 修改 Chat Pipeline / 修改 Feishu / 实现 Scheduler / 实现 Worker / 实现主动消息 / 实现新 API。

若发现现有实现不足，仅在本文档标记为**补丁任务**，不直接改。

**API 判断**：Autonomy **不需要** `/api/autonomy/*`。优先采用**内部 Application Service + Background Worker**。仅当 Debug / Admin / 手动触发 / Observability 确实需要时，才建议最小化 admin 端点，留给后续阶段决策。

---

## 38. Gap Analysis（差距分析）

### 38.1 已实现（当前架构已满足目标）

| 目标能力 | 现状 | 结论 |
|---|---|---|
| Trigger（3 类） | `trigger_evaluator` + `trigger_registry` | ✅ |
| Decision 三值 + 闸门 | `autonomy_policy`（八步 + R/W/A） | ✅ |
| 主动消息生成（角色化） | `proactive_chain` | ✅ |
| 状态机 + 幂等 + 重试 | `proactive_repository` | ✅ |
| Life Loop 编排 | `life_loop`（phase-5） | ✅ |
| Reflection 与 Autonomy 解耦 | `_step_reflection_check` 独立频控 | ✅ |
| World/Action/Relationship 域集成 | W/R/A 增量规则 | ✅ |
| Channel 抽象 + Feishu Adapter | `channels/base` + `feishu/*` | ✅ |
| 竞态（用户回来） | `reset_proactive_on_user_message` | ✅ |
| 可观测 | `decision_records` + trace | ✅ |
| 多用户隔离 | 全程 `internal_user_id` 过滤 | ✅ |

### 38.2 关键 Gap（需补丁闭合）

| # | Gap | 影响 | 归属 |
|---|---|---|---|
| **G1** | `proactive_executor` 未调用 `delivery.send_proactive`，主动消息**未真正发到 Feishu** | 主动行为"空转"，核心链路未闭合 | 补丁 P1（最高） |
| **G2** | `proactive_actions.message_id` 存内部 id，缺 `external_message_id` | 无法关联 Feishu 投递，幂等/审计不完整 | 补丁 P2（随 P1） |
| **G3** | 生成与发送未拆两阶段，`delivered` 语义含糊 | Channel 失败误判为已完成 | 补丁 P3（随 P1） |
| **G4** | 双 tick 源（`autonomy_worker` + `life_loop`）潜在重复求值 | 性能与重复风险 | 补丁 P4（次要） |
| **G5** | 无多候选 LLM 软排序 | 多机会并存时无"选哪个更好" | 未来版本 |
| **G6** | Preference/Commitment → 重复 scheduled action 缺失 | 用户"每天提醒"无法持续 | 未来版本 |
| **G7** | 缺 `world_change` / `life_loop_event` 等新 Trigger | 世界/生活事件只能进 reason | 未来版本 |
| **G8** | 无显式 P0/P1 High Priority Override 通道 | 高优提醒与普通 check_in 共用冷却 | 补丁 P5（次要） |

### 38.3 需修改的现有模块（补丁落地时）

| 模块 | 改动 | 对应 Gap |
|---|---|---|
| `services/proactive_executor.py` | 生成后调用 `delivery.send_proactive`，回填 `external_message_id` | G1/G2/G3 |
| `core/db.py` `ProactiveActionRow` | 加 `external_message_id` 列 | G2 |
| `services/autonomy_policy.py` | （可选）显式 P0/P1 优先级覆盖通道 | G8 |
| `core/settings/*` | （可选）优先级/预算相关配置 | G5/G8 |

### 38.4 需新增的模块（未来版本，非本补丁）

| 模块 | 职责 | 对应 Gap |
|---|---|---|
| （候选）`services/candidate_scorer.py` | 多候选 Rule+LLM 软排序 | G5 |
| （候选）`services/preference_commitment.py` | 偏好/承诺 → 重复 scheduled action | G6 |

---

## 39. Patch Task 划分（非 Task Detail）

> 仅阶段划分方向，不产出 Task Detail。详细见 [patch-tasks.md](patch-tasks.md)。

| Patch | 主题 | 内容概要 |
|---|---|---|
| **PATCH-AUT-01** | 主动消息投递链路闭合 | G1：接 `send_proactive`、拆生成/发送、加 `external_message_id`、明确 `delivered` 语义 |
| **PATCH-AUT-02** | 调度收敛 | G4：统一 tick 源（`life_loop` 为主，`autonomy_worker` 兜底） |
| **PATCH-AUT-03** | 优先级覆盖 | G8：引入 P0/P1 High Priority Override 语义 |
| **PATCH-AUT-04** | 幂等与审计收口 | G2/G3：`external_message_id` 回填 + trace 关联 + 生成/发送两阶段 |
| **PATCH-AUT-05** | 回归与评估 | 补丁回归清单 + 主动消息投递评估（投递成功率/幂等/竞态） |

---

## 40. 总结

Autonomy 2.0 的**心智模型与大部分执行能力已在当前代码中落地**（Trigger/Decision/Action 三层分离、Rule 闸门、状态机、幂等、Life Loop 编排、Channel 抽象、多用户隔离都已存在）。本架构文档的核心贡献是：

1. **厘清五层语义边界**（Trigger → Opportunity → Desire → Decision → Action），明确 Opportunity/Desire 不需独立成表、`proactive_actions` 定位为"Action + Execution/Delivery 的 Outbox"。
2. **定位首要 Gap**：主动消息"决策→生成→落库"已闭环，但"→ Feishu 真实投递"尚未接通（`send_proactive` 无生产调用方）。
3. **澄清 `internal_message_id` vs `external_message_id`**，避免混用。
4. **明确数据库结论**：只 `Modify`（`external_message_id` 一列），不新增表。
5. **明确 Background Job 结论**：复用 `trigger_registry` + `proactive_actions` + 现有 worker，不建新队列/调度。
6. **给出补丁划分**：优先闭合投递链路（PATCH-AUT-01），再收敛调度与优先级，收口幂等审计，最后补回归评估。

本阶段到此为止，等待下一步指令。
