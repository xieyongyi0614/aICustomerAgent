# PLAN-010 Task Detail — Reflection Integration

> 上游：[../architecture.md](../architecture.md) §7.6（执行结果 → Reflection → Planning 闭环）、§7.5.4（判据 D）、§6.1 ⑦、§8.6（`PlanningRevisionListener`）、§9.6 G-REFLECT、§9.7 Q8；[../tasks.md](../tasks.md) PLAN-010
> 状态：DONE（已实现，commit 777c8ee，2026-09-16）
> 范围红线：**反思分析计划效能，但不改写计划**；只投一个幂等的重规划触发；三道闸零豁免；不在 `foreground` 关键路径做计划反思；不产出「性格类」Insight。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-010 |
| **Task Name** | Reflection Integration |
| **Priority** | P1 |
| **Dependencies** | PLAN-005 |
| **Phase** | Phase 3 系统集成 |
| **建议提交** | `feat: V2.5.0 计划证据窗与反思重规划回环` |

## 1.1 Goal

建立「**执行结果 → 反思 → 计划优化**」闭环：

1. **扩一路证据通道**：新增 `EVIDENCE_CHANNEL_PLAN = "plan"`（与既有 `EVIDENCE_CHANNEL_MEMORY` / `EVIDENCE_CHANNEL_TOOL` 并列）。
2. **三个计划证据窗（B6 关闭点）**：计划成功率 / 步骤失败模式 / 判据可判定性。
3. **三道闸零豁免**：证据门槛（`passes_gate`）+ 当日额度（`_quota_used`）+ 幂等入队（`has_job(idempotency_key)`），完全复用既有 `trigger_for_user`。
4. **交付 `PlanningRevisionListener`**：`on_insight_created` 注册进既有 `notify_insight_created_listeners`——这是本版本**唯一**的 Planning 侧反思接线。
5. **新规划轮次携带证据**：`PlanContext.evidence_refs` → 进 prompt 与 `GoalPlanRecord.evidence_refs`。

## 1.2 Scope

**包含**

- `app/models/reflection.py`：`EVIDENCE_CHANNELS` 扩一路（`EVIDENCE_CHANNEL_PLAN = "plan"`）。
- `app/services/reflection/evidence.py`：新增三个计划窗口的聚合器（复用既有 `passes_tool_gate` / `ToolEvidenceWindow` 同构机制）。
- 窗口分组键沿用既有 `GROUP_KIND_*` 范式（`plan_kind` / `step_kind` / `failure_kind`）。
- 证据 id 命名沿用既有形态 `plan:<goal_id>:<version>:<step_index>`。
- 新建 `app/services/planning/revision_listener.py`：`on_insight_created` / `enqueue_replan`，注册进既有 `notify_insight_created_listeners`。
- 三道门槛（类型 / 置信度 / 可映射 active 目标）+ 幂等键 `plan_replan:{goal_id}:{insight_id}`。
- Q8 裁决：`insight_driven` 与其他三条重规划判据同时命中时**只产生一个**重规划触发。
- `v25_plan_reflection_enabled` / `v25_plan_replan_min_confidence` / `v25_plan_reflection_min_samples` 门控。

**不包含（Non-Scope）**

- 三道闸的**任何改动**（V2.0 冻结）。
- `reflector` / `triggers` / `lifecycle` 的**任何改动**（除必要的通道常量与窗口聚合新增）。
- Reflection 直接改写计划 / 直接改 `GoalStatus` / 直接写 `goal_plans`（**永不**）。
- `PlanRevisionPolicy.should_replan` 的判定实现（属 PLAN-005；本任务只提供 `insight_driven` 的触发源）。
- 计划终态记忆（PLAN-009）。
- 世界写入与广播（PLAN-008）。
- 自治 `plan_facts`（PLAN-007）。
- 调试端点（PLAN-011）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 断层 **B6（计划终点无反思闭环）**：

| 断层 | 证据（已核对） | 本任务的关闭方式 |
|---|---|---|
| B6 | `services/reflection/` 全包 grep `plan` / `strateg` 零命中；`notify_insight_created_listeners` 的既有消费者只有 `development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py` 三处 | 新增计划证据通道与第四个消费者 `PlanningRevisionListener` |

**闭环的价值**：同一类计划反复失败时，Agent 能学到「这个做法不行」并在**下一次规划轮次**里换做法——而不是在同一个失败方案上无限重规划。这也是 Q8 必须裁决的原因：四条重规划判据若同时命中却各投一次触发，会退化为重规划风暴。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Reflection System** | **核心交互面**：`evidence.py`（证据聚合）/ `lifecycle.py`（监听器机制）/ `triggers.py`（三道闸）/ `reflector.py`（Insight 产出）/ `tool_feed.py` |
| **Planning System** | 计划执行数据（`goal_plans` / `action_records`）为证据窗数据源；`enqueue_planning(TRIGGER_REPLAN)` 为唯一动作 |
| **Memory 2.0** | 记忆证据窗既有；**本任务不涉及记忆写入**（属 PLAN-009） |
| **Tool System V2.4.0** | 工具证据窗（`ToolEvidenceWindow`）为本任务的**同构样板** |
| **World Simulation** | `world/event_bridge.py::on_insight_created` 为既有消费者之一；**零改动** |
| **Autonomy 2.0** | **不涉及**（属 PLAN-007） |

**关键事实（已核对真实源码）**

- 证据通道常量位于 **`app/models/reflection.py`**：`EVIDENCE_CHANNEL_MEMORY = "memory"`、`EVIDENCE_CHANNEL_TOOL = "tool"`、`EVIDENCE_CHANNELS: tuple[str, ...] = (EVIDENCE_CHANNEL_MEMORY, EVIDENCE_CHANNEL_TOOL)`。
  > **源码核对说明**：architecture §7.6 ① 将该常量对表述为「在 `app/services/reflection/evidence.py` 的既有 `EVIDENCE_CHANNEL_MEMORY` / `EVIDENCE_CHANNEL_TOOL` 之外」。**实际值集定义在 `app/models/reflection.py::EVIDENCE_CHANNELS`**，`services/reflection/evidence.py` 与 `reflector.py` / `triggers.py` 通过 import 使用。本任务因此**扩值集在 `models/reflection.py`，扩聚合在 `services/reflection/evidence.py`**——与 architecture 意图一致，落点更精确。
- `app/services/reflection/evidence.py` 既有：`EVIDENCE_CHANNEL_*` import、`STEP_NAME="reflection_evidence"`、`TOOL_EVIDENCE_STEP_NAME="reflection_tool_evidence"`、`TOOL_EVIDENCE_WINDOW_DAYS=7`、`TOOL_EVIDENCE_MAX_MEMBERS=12`、`TOOL_EVIDENCE_RECORD_SCAN_LIMIT=200`、`GROUP_KIND_TOOL="tool_id"` / `GROUP_KIND_ACTION="action_type"` / `GROUP_KIND_FAILURE="failure_kind"`、`TOOL_GATE_SAMPLES="samples"` / `TOOL_GATE_FAILURES="failures"` / `TOOL_GATE_SPAN="span"`、`_GATE_EVIDENCE_COUNT` / `_GATE_SPAN` / `_GATE_COHERENCE`、`passes_gate(window, settings)` / `passes_tool_gate(window, thresholds)` / `tool_gate_reasons(window, thresholds)`、`aggregate_evidence_windows(...)` / `_aggregate` / `_pool` / `_build_window` / `_window_digest` / `_trace`、`ToolExecutionFact` / `ToolEvidencePackage` / `aggregate_tool_usage` / `aggregate_success_rate` / `aggregate_user_feedback` / `aggregate_tool_windows`、`VISIBILITY_HYPOTHETICAL`、`_TOOL_FACT_SALIENCE=0.8` / `_DEFAULT_SALIENCE=0.5` / `_COHERENCE_PAIR_SAMPLE=20` / `_TOPIC_DIGEST_CHARS=40`。
- `app/services/reflection/lifecycle.py`：`register_insight_created_listener(fn)` / `notify_insight_created_listeners(user_id, created)` / `list_active_insights(...)` / `list_user_active_insights(user_id) -> list[Insight]`。**四个注册点现状**：`development/policy.py:180`、`relationship_narrative.py:128`、`world/event_bridge.py:108` 三处（即 architecture 所述三个既有消费者）；`reflector.py:432` 调用 `notify_insight_created_listeners`。**本任务新增第四个注册点**（`planning/revision_listener.py`）。
- `app/services/reflection/triggers.py`：`trigger_for_user(...)`（含 `_quota_used(user_id, now)` 当日额度闸与 `background_job_repository.has_job(idempotency_key)` 幂等入队）、`tool_channel_enabled(settings)`、`observe_tool_evidence(...)` / `observe_tool_evidence_from_records(...)`、`observe_reinforce(...)`、`run_reflection_trigger_tick(now)`、`_channel_field(channel)` / `_channel_bucket_key(user_id, now, channel)` / `_match_bucket` / `_rotate` / `_order_tool_windows` / `_existing_windows_summary` / `_trim_seen` / `_day_bucket_key` / `_record_run` / `_drop_run`；`register_with_job_worker()`。
- `app/services/reflection/tool_feed.py`：`is_enabled(settings)` / `interest_signal(user_id, *, limit=TOOL_FEED_MAX_ITEMS)` / `autonomy_signal(user_id, *, limit)` / `tool_ids_of_insights(insight_ids)`。
- `app/core/settings/reflection_development.py`：`v2_reflection_min_evidence`（3）/ `v2_reflection_min_span_hours`（24.0）/ `v2_reflection_min_coherence`（0.5）/ `v2_reflection_context_max_items`。
- `app/prompts/reflection.py`：反思 prompt。
- 迁移链头 0046。

## 2.2 为什么需要本任务

架构 §1.1 的诊断之一是：**「有反思，但反思碰不到计划」**——`services/reflection/` 全包 grep `plan` / `strateg` 零命中，执行结果 → 反思 → 计划优化这条闭环是断的。

断链的后果是**同类失败无法规避**：计划「4 步做面试准备」连续两次失败，第三次仍会规划出 4 步（因为没有任何机制把「4 步做不完」这件事告诉规划器）。本任务补上这条链路，并严格限制其行为为「**投一个幂等触发**」——反思管认知，Planning 管编排（architecture §7.6 明确边界）。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 新增 `EVIDENCE_CHANNEL_PLAN = "plan"` 并扩 `EVIDENCE_CHANNELS` | 值集扩展 |
| R2 | 三个计划证据窗的聚合（成功率 / 失败模式 / 判据可判定性） | 聚合器 + 用例 |
| R3 | 窗口分组键与证据 id 命名沿用既有范式 | 契约 |
| R4 | 三道闸零豁免（门槛 / 额度 / 幂等入队） | 复用 `trigger_for_user` |
| R5 | `PlanningRevisionListener` 与三门槛 + 幂等键 | 监听器 |
| R6 | 注册进既有 `notify_insight_created_listeners`（**唯一** Planning 侧接线） | 注册点 |
| R7 | 新规划轮次携带 `evidence_refs`（进 prompt 与 `GoalPlanRecord.evidence_refs`） | 接线 |
| R8 | **G-REFLECT**：隔离断言（不改 `GoalPlanRecord` / `GoalStatus` / 工具注册表） | 断言 |
| R9 | Q8 裁决：四判据同时命中只产生一个重规划触发 | 裁决 + 用例 |
| R10 | 门控（`v25_plan_reflection_enabled` / 置信度 / 样本门槛） | 用例 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 直接改写 `sub_goals` / `GoalPlanStatus` | **永不**（改写只发生在 `goal_planning` 的新轮次里） |
| N2 | 直接改 `GoalStatus` | **永不**（唯一写面在 `goal_repository`，经 PLAN-005 `settle`） |
| N3 | 直接写 `goal_plans` | **永不** |
| N4 | 三道闸的规则改动 | **永不**（V2.0 冻结） |
| N5 | 产出「性格类」Insight | **永不**（计划失败不改变人格） |
| N6 | 在 `foreground` 关键路径做计划反思 | **永不**（仍在 `memory_extract` 步与后台节拍里） |
| N7 | 自动终止计划 / 自动熔断工具 | **永不**（健康度与运维另有通道） |
| N8 | `should_replan` 的四判据判定实现 | PLAN-005（本任务提供 `insight_driven` 触发源） |
| N9 | 三闸门槛阈值的新增 | 复用既有 settings（`v25_plan_reflection_min_samples` 对齐 `v2_reflection_min_evidence`） |

## 3.3 职责边界一句话

> **反思分析计划效能，但不改写计划。`on_insight_created` 的全部行为就是一个幂等入队——它不碰计划、不碰目标、不碰工具。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/models/reflection.py` | 既有 | **扩展**：`EVIDENCE_CHANNELS` 加第三值 | 纯值集 |
| `app/services/reflection/evidence.py` | 既有 | **扩展**：新增三个计划窗口聚合器 | → `goal_repository`（只读）/ `action_repository`（只读） |
| `app/services/reflection/triggers.py` | 既有 | **最小接线**：计划通道接入既有 `trigger_for_user` 的三道闸 | **改写逻辑零改动** |
| `app/services/planning/revision_listener.py` | **新增** | `on_insight_created` / `enqueue_replan` | → `reflection/lifecycle.register_insight_created_listener` / `goal_planning.enqueue_planning` / `background_job_repository.has_job` |
| `app/services/planning/context.py`（PLAN-003） | 已有 | 补齐 `evidence_refs` 注入 | 透传 |

**分层纪律（静态断言强制）**
- `revision_listener.py` **零** `goal_repository.set_status` / `finish_goal` 调用；**零** `goal_plans` 写入。
- `revision_listener.py` 的**唯一动作**是 `goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)`。
- 既有三个消费者（`development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py`）行为不变。

### 4.1.2 Component 划分

```text
app/models/reflection.py（扩展）
└── EVIDENCE_CHANNELS: ("memory", "tool") → ("memory", "tool", "plan")
      EVIDENCE_CHANNEL_PLAN = "plan"

app/services/reflection/evidence.py（扩展）
├── 三个计划窗口聚合器
│     aggregate_plan_success_rate(...)   ← goal_plans 按 status × goal.type 聚合
│     aggregate_step_failure_modes(...)  ← action_records.steps 按 tool_id × failure_kind 聚合
│     aggregate_criteria_decidability(...) ← goal_plans.sub_goals 中 criteria_result=None 占比
│     · 分组键沿用 GROUP_KIND_* 范式（plan_kind / step_kind / failure_kind）
│     · 证据 id 沿用形态 plan:<goal_id>:<version>:<step_index>
│     · 门槛复用 passes_gate 或 passes_tool_gate（+ v25_plan_reflection_min_samples）

app/services/reflection/triggers.py（最小接线）
└── trigger_for_user （三道闸零改动，计划通道与用户证据走完全相同闸门）

app/services/planning/revision_listener.py（新增）
└── PlanningRevisionListener
      on_insight_created(user_id, created) -> None     # 注册进既有 notify_insight_created_listeners
      enqueue_replan(goal_id, insight_id) -> bool       # 幂等
        · 门槛一：insight.type ∈ PLAN_INFLUENCE_INSIGHT_TYPES
        · 门槛二：insight.confidence ≥ v25_plan_replan_min_confidence
        · 门槛三：存在可映射的 active 目标
        · 幂等键：plan_replan:{goal_id}:{insight_id}
        · 唯一动作：goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)
        · ✗ 不直接改 plan.sub_goals / GoalStatus / goal_plans
```

### 4.1.3 数据流：闭环链路

```text
Plan 执行与终态
    │  （数据已在 action_records.steps 与 goal_plans.sub_goals，零新表）
    ▼
① 证据聚合（扩源）
   aggregate_evidence_windows 扩一通道：
     · EVIDENCE_CHANNEL_PLAN = "plan"（与既有 memory / tool 并列）
     · 窗口分组键沿用既有 GROUP_KIND_* 范式
     · 证据 id 形态：plan:<goal_id>:<version>:<step_index>
        │  门槛：passes_gate（evidence_count / span / coherence）
        │        或 passes_tool_gate（samples / failures / span）
        ▼
② 三道闸（零豁免，完全复用 trigger_for_user）
   ├─ 闸一：证据门槛（passes_gate / passes_tool_gate）
   ├─ 闸二：当日额度（_quota_used）
   └─ 闸三：幂等入队（background_job_repository.has_job(idempotency_key)）
        ▼
③ Reflection 产出 Insight（既有 reflector：证据窗 → LLM → 置信度校准 → review 闸）
   Insight{type ∈ {capability_note, pattern, usage_preference}, scope ∈ {user, world}, confidence}
        ▼
④ 事件通知（复用既有监听器机制）
   reflection/lifecycle.notify_insight_created_listeners(user_id, created)
     · 既有消费者：development/policy.py:on_insight_created
     ·              relationship_narrative.py:on_insight_created
     ·              world/event_bridge.py:on_insight_created
     · ★ 新增消费者：planning/revision_listener.py:on_insight_created     ← 本版本唯一的 Planning 侧接线
        ▼
⑤ 重规划触发（唯一动作，且极窄）
   PlanningRevisionListener（三门槛 + 幂等键）
        ▼
⑥ 新规划轮次（回 PLAN-003 的装配）
   PlanContext.evidence_refs = [insight_id, ...] → 进 prompt 与 GoalPlanRecord.evidence_refs
   ⇒ "我上一次这么做没成，这次换个做法" —— 闭环成立
```

## 4.2 Core Model

本任务**不新增持久模型**。下表为证据窗与监听器的契约。

### 4.2.1 三个计划证据窗（B6 关闭点）

| # | 证据窗 | 数据源（投影） | 窗口分组 | 产出 Insight 类型 | 示例 |
|---|---|---|---|---|---|
| 1 | **计划成功率** | `goal_plans` 按 `status` × `goal.type` 聚合 | 按目标类型（`plan_kind`） | `capability_note` | 「面试类计划 4 步做不完，实际两步就够」 |
| 2 | **步骤失败模式** | `action_records.steps` 按 `tool_id` × `failure_kind` 聚合 | 按工具 × 失败类（`step_kind` / `failure_kind`） | `capability_note` / `usage_preference` | 「查天气这一步总是超时，先别排它」 |
| 3 | **判据可判定性** | `goal_plans.sub_goals` 中 `criteria_result=None` 的步占比 | 按判据类型 | `pattern` | 「我给自己定的判据太虚，常判不出来」 |

**窗口契约**

| 项 | 契约 |
|---|---|
| 通道常量 | `EVIDENCE_CHANNEL_PLAN = "plan"`（值集在 `models/reflection.py`） |
| 分组键 | 沿用既有 `GROUP_KIND_*` 范式（`plan_kind` / `step_kind` / `failure_kind`） |
| 证据 id | `plan:<goal_id>:<version>:<step_index>`（沿用既有命名形态） |
| 时间窗 | 复用既有 `TOOL_EVIDENCE_WINDOW_DAYS`（7）语义 |
| 成员上限 | 复用既有 `TOOL_EVIDENCE_MAX_MEMBERS`（12） |
| 扫描上限 | 复用既有 `TOOL_EVIDENCE_RECORD_SCAN_LIMIT`（200） |
| 门槛 | 复用 `passes_gate`（`evidence_count` / `span` / `coherence`）或 `passes_tool_gate`（`samples` / `failures` / `span`）；`v25_plan_reflection_min_samples`（默认 3）对齐 `v2_reflection_min_evidence` |

### 4.2.2 `PlanningRevisionListener` 契约

| 项 | 契约 |
|---|---|
| 注册点 | `reflection/lifecycle.register_insight_created_listener(on_insight_created)`（**本版本唯一 Planning 侧接线**） |
| 入参 | `(user_id: str, created: list[dict])` |
| 门槛一 | `insight.type ∈ PLAN_INFLUENCE_INSIGHT_TYPES`（默认 `capability_note` / `pattern`） |
| 门槛二 | `insight.confidence ≥ v25_plan_replan_min_confidence`（默认 0.7） |
| 门槛三 | 存在可映射的 active 目标（按 `insight.scope` 与目标 `domain` / `layer` 匹配） |
| 幂等键 | `plan_replan:{goal_id}:{insight_id}` |
| 唯一动作 | `goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)` |
| ✗ 禁止 | 直接改 `plan.sub_goals`、直接改 `GoalStatus`、直接写 `goal_plans` |

### 4.2.3 三门槛值集与参数

| 项 | 取值 / 参数 | 对齐来源 |
|---|---|---|
| 影响类型 | `PLAN_INFLUENCE_INSIGHT_TYPES`（默认 `capability_note` / `pattern`） | architectural §7.6 ⑤ |
| 置信度下限 | `v25_plan_replan_min_confidence`（0.7） | `v23_interest_confidence_threshold` |
| 样本门槛 | `v25_plan_reflection_min_samples`（3） | `v2_reflection_min_evidence` |
| 洞察类型域（既有） | `capability_note` / `pattern` / `usage_preference` | 既有 `Insight` 模型 |

### 4.2.4 证据 id 命名范式（沿用既有）

| 通道 | 证据 id 形态 |
|---|---|
| `memory` | 既有形态（记忆 id 系） |
| `tool` | 既有形态（工具执行系） |
| **`plan`** | **`plan:<goal_id>:<version>:<step_index>`** |

### 4.2.5 `evidence_refs` 的下游契约

| 项 | 契约 |
|---|---|
| 注入 | `PlanContext.evidence_refs = [insight_id, ...]`（由装配器从触发源取，PLAN-003 透传） |
| prompt | 进规划 prompt（「上次这么做没成，这次换个做法」） |
| 落库 | 进 `GoalPlanRecord.evidence_refs`（PLAN-002 字段；落点见 PLAN-002 §4.4.1 → `decision_records.input_snapshot`） |
| 修订链 | 进 `PlanRevision.evidence_refs`（PLAN-002），供 PLAN-011 的修订链投影读取 |

## 4.3 State Machine

本任务**不新增状态机**。下为 Insight 生命周期与重规划触发的交互。

### 4.3.1 Insight 生命周期（既有）× 计划

```text
证据窗（含新增 plan 通道）
    │ 达门槛（passes_gate / passes_tool_gate）
    ▼
三道闸（零豁免）
    ├─ 闸一 证据门槛 ✗ → 不产 Insight（零 LLM）
    ├─ 闸二 当日额度 ✗ → 不产 Insight
    └─ 闸三 幂等入队 ✗ → 复用既有 run
    ▼
Insight 产出（既有 reflector）；Insight 状态 ∈ 活跃 / 非活跃（既有生命周期）
    ▼
notify_insight_created_listeners（既有机制）
    ├─ 三个既有消费者（零改动）
    └─ ★ PlanningRevisionListener（新增）
          ├─ 门槛一 ✗ → 返回（零动作）
          ├─ 门槛二 ✗ → 返回
          ├─ 门槛三 ✗ → 返回
          └─ 全过 → enqueue_replan（幂等键 plan_replan:{goal_id}:{insight_id}）
                ▼
            goal_planning.enqueue_planning(TRIGGER_REPLAN)   ← 唯一动作，到此为止
```

### 4.3.2 Q8 裁决：四判据同时命中的去重

```text
PlanRevisionPolicy.should_replan 有四条理由码：
   step_attempt_exhausted        ← PLAN-005 判定
   tool_persistently_unavailable ← PLAN-005 判定
   criteria_undecidable          ← PLAN-005 判定
   insight_driven                ← PLAN-010（本任务）触发源

同时命中时：
   ├─ 四个理由码按固定优先序归一为一个（见下表）
   └─ 幂等键在两层同时生效：
         · 本任务层：plan_replan:{goal_id}:{insight_id}
         · 既有 job 层：background_job_repository.has_job(idempotency_key)
   ⇒ 只产生一个重规划触发（只入队一次）

优先序（Q8 裁决结论）：
   1. step_attempt_exhausted         （步骤层事实最直接）
   2. criteria_undecidable           （判据层事实次之）
   3. tool_persistently_unavailable  （工具面事实，可能是暂时性的）
   4. insight_driven                 （认知层建议，最弱）
```

**裁决理由**：`insight_driven` 是**建议性**触发（来自反思的统计倾向），其余三条是**事实性**触发（来自本计划的实际执行状态）。事实优先于建议，避免反思统计噪声覆盖计划自身的失败证据。

**幂等的双重保障**：
1. 本任务层：`plan_replan:{goal_id}:{insight_id}`（同一 Insight 对同一目标只触发一次）。
2. 既有 job 层：`background_job_repository.has_job(idempotency_key)`（同一目标的重规划 job 不重复入队）。

## 4.4 明确边界（Reflection 不做的事）

| # | 不做 | 原因 |
|---|---|---|
| 1 | 不直接改写 `sub_goals` / `GoalPlanStatus` | 规划改写只发生在 `goal_planning` 的新轮次里 |
| 2 | 不因计划失败产出「性格类」Insight | 计划失败不改变人格（性格类属 V2.2 通道） |
| 3 | 不绕过三道闸 | 计划证据与用户证据走**完全相同**的闸门（与 V2.4.0 §7.5 同一纪律） |
| 4 | 不直接终止计划、不自动把工具下线 | 健康度与运维另有通道 |
| 5 | 不在 `foreground` 关键路径里做计划反思 | reflection 仍在 `memory_extract` 步与后台节拍里 |

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `tool_insights` 进 `PolicySnapshot` | 既有（`tool_feed.autonomy_signal`） | **零改动** |
| `plan_facts` | PLAN-007 | **不涉及** |
| 重规划触发的额度 | `trigger_for_user` 的当日额度闸 | **复用**（不绕过） |

**为什么不涉及**：本任务的触发动作是「入一个规划 job」，不是「做一次主动行为」——它不经过自治裁决，因此不涉及自治侧数学。但它**受反思侧当日额度约束**（闸二）。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 工具证据窗（`ToolEvidenceWindow` 机制） | 本任务的**同构样板** | 参照形态，不修改工具窗口 |
| `GROUP_KIND_TOOL` / `GROUP_KIND_FAILURE` | 复用其分组范式 | **复用命名，零改动** |
| 工具注册表 / 健康度 | 既有 | **断言零改动**（G-REFLECT） |
| 自动熔断工具 | **永不** | 明确边界 4 |

**为什么断言零改动**：`on_insight_created` 若不慎调用工具注册表的禁用/熔断方法，会形成「反思 → 熔断工具」的隐式耦合，违反 architecture §7.6「不自动把工具下线」的边界。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `world/event_bridge.py::on_insight_created` | 既有第三个消费者 | **零改动**；本任务新增监听器**不改变它的行为** |
| 计划终态广播 → 世界事件 | PLAN-008 | **不涉及** |

**回归要求**：新增第四个消费者后，须验证既有三个消费者的行为不变（注册顺序、调用参数、副作用均不变）——这是 §10.2 的回归对照项。

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 记忆证据窗（`EVIDENCE_CHANNEL_MEMORY`） | 既有通道 | **零改动** |
| 计划终态记忆 | PLAN-009 | **不涉及** |
| 记忆写入 | 本任务零写入 | — |

**为什么不涉及**：本任务只**扩一路证据通道**，不触碰记忆写入政策；计划终态记忆候选属 PLAN-009。

## 5.5 与 Reflection（本任务核心）

| 关注点 | 既有（V2.0 / V2.4.0，基本零改动） | 本任务 |
|---|---|---|
| 证据通道值集 | `models/reflection.py::EVIDENCE_CHANNELS`（2 值） | **扩为 3 值** |
| 证据聚合 | `aggregate_evidence_windows` / `aggregate_tool_windows` / `passes_gate` / `passes_tool_gate` | **扩一路计划通道**（同构） |
| 三道闸 | `trigger_for_user`（门槛 / 额度 / 幂等入队） | **零改动**（计划证据走同一套） |
| 监听器机制 | `register_insight_created_listener` / `notify_insight_created_listeners` | **新增第四个注册点** |
| Insight 产出 | `reflector`（证据窗 → LLM → 置信度校准 → review 闸） | **零改动** |
| 防幻觉纪律 | 既有 | **零改动** |

## 5.6 与 Planning（本任务核心）

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `enqueue_planning(user_id, goal_id, trigger)` | 既有（`goal_planning`） | **唯一动作**（幂等） |
| `PLANNING_TRIGGERS` | 既有三常量 | **复用 `TRIGGER_REPLAN`**（无新值） |
| `PlanContext.evidence_refs` | PLAN-002 字段 | **注入**（供新轮次 prompt） |
| `GoalPlanRecord.evidence_refs` | PLAN-002 字段 | **写入**（经 PLAN-003 的计划落库路径） |
| `should_replan` 的 `insight_driven` 理由码 | PLAN-005 定义 | **提供触发源**（不实现判定） |
| `PlanScheduler` / `PlanObserver` / 执行桥 | PLAN-005 | **不涉及** |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 计划生成 / 拆解 | 不涉及（本任务只注入 `evidence_refs`） | PLAN-003 / PLAN-004 |
| 调度 / 执行 / 观测 / 修订判定 | 不涉及（只提供触发源与理由码消费方） | PLAN-005 |
| 工具治理 | 不涉及 | PLAN-006 |
| 世界写入与广播 | 不涉及 | PLAN-008 |
| 计划终态记忆 | 不涉及 | PLAN-009 |
| 自治 `plan_facts` | 不涉及 | PLAN-007 |
| 调试端点 | 不涉及 | PLAN-011 |

---

# 6. API / Interface Design

## 6.1 证据通道接口（值集扩展）

```text
# app/models/reflection.py
EVIDENCE_CHANNEL_MEMORY = "memory"      # 既有
EVIDENCE_CHANNEL_TOOL = "tool"          # 既有
EVIDENCE_CHANNEL_PLAN = "plan"          # 本任务新增
EVIDENCE_CHANNELS: tuple[str, ...] = (  # 由 2 值扩为 3 值
    EVIDENCE_CHANNEL_MEMORY,
    EVIDENCE_CHANNEL_TOOL,
    EVIDENCE_CHANNEL_PLAN,
)
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 追加在末尾，**既有两值相对顺序不变** | 值集快照对照 |
| D2 | 值集扩展不改变既有两通道的行为 | 通道用例回归 |

## 6.2 计划证据窗聚合接口

```text
interface PlanEvidenceAggregator:                # 与既有 ToolEvidenceWindow 同构
    aggregate_plan_success_rate(user_id, *, now) -> PlanEvidencePackage
    aggregate_step_failure_modes(user_id, *, now) -> PlanEvidencePackage
    aggregate_criteria_decidability(user_id, *, now) -> PlanEvidencePackage
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D3 | 数据源全部为**既有表投影**（`goal_plans` / `action_records`），零新表 | 静态断言（零 DDL / 零新表引用） |
| D4 | 复用既有上限常量（`TOOL_EVIDENCE_WINDOW_DAYS` / `TOOL_EVIDENCE_MAX_MEMBERS` / `TOOL_EVIDENCE_RECORD_SCAN_LIMIT`） | 常量对照 |
| D5 | 分组键沿用既有 `GROUP_KIND_*` 范式 | 键名对照 |
| D6 | 证据 id 形态 `plan:<goal_id>:<version>:<step_index>` | 用例断言 |
| D7 | 门槛复用 `passes_gate` / `passes_tool_gate`，不自造门槛数学 | 静态断言 |
| D8 | 证据不足 → **不产 Insight**（零 LLM 调用） | 打桩断言 |

## 6.3 `PlanningRevisionListener` 接口

```text
interface PlanningRevisionListener:
    on_insight_created(user_id: str, created: list[dict]) -> None    # 注册进既有 notify_insight_created_listeners
    enqueue_replan(goal_id: str, insight_id: str) -> bool            # 幂等
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D9 | 全流程**零仓储写入**（`goal_plans` / `character_goals` 零写） | 静态 + 运行时断言（G-REFLECT） |
| D10 | 唯一动作是 `goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)` | 静态断言（调用点唯一） |
| D11 | 幂等键固定 `plan_replan:{goal_id}:{insight_id}` | 用例断言 |
| D12 | 三门槛任一不过 → 零动作返回 | 三个负例用例 |
| D13 | 工具注册表 / 健康度零调用 | 静态断言 |

## 6.4 参数接口（消费 PLAN-002 配置）

```text
# 门控与门槛
v25_plan_reflection_enabled      # 计划证据窗 + 监听器总开关（依赖总闸 + v2_reflection_enabled）
v25_plan_replan_min_confidence   # 门槛二（默认 0.7）
v25_plan_reflection_min_samples  # 窗口样本门槛（默认 3）
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D14 | `v25_plan_reflection_enabled` off → 证据聚合只有 `memory` 与 `tool` 两通道；**无 `planning/revision_listener`** | 门控用例 |
| D15 | 三闸门槛阈值复用既有 settings 语义（不新造数学） | 常量对照 |

## 6.5 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| `on_insight_created` 内异常 | 映射 / 匹配逻辑 | 捕获 → log；**不影响其他监听器**（既有 `notify_insight_created_listeners` 的隔离语义） |
| 目标映射失败 | 门槛三（无可映射 active 目标） | 返回（**零动作**，不是异常） |
| `enqueue_planning` 异常 | `goal_planning` | 捕获 → log；不影响 Insight 生命周期 |
| 证据聚合异常 | 只读投影 | 捕获 → 空窗（不产 Insight）；log |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 证据窗是**投影**（不建表）；`insights` 表既有 |
| 新列 | 无 | `EVIDENCE_CHANNELS` 是 Python 值集（非 DB 约束）；`insight` 的类型列既有，新增类型取值 `capability_note` / `pattern` 均已有 |
| 新索引 | 无 | 证据投影复用既有 `goal_plans` / `action_records` 查询（`idx_goal_plans_goal_status` 等） |
| 改 CHECK | 无 | `insights` 的类型 / `scope` 值集未扩；`background_jobs.job_type` 未扩（复用 `goal_planning`） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| Insight | `insights` | 既有 `reflector`（本任务只扩证据源，不改产出路径） | ❌ |
| 规划 job（重规划触发） | `background_jobs` | `goal_planning.enqueue_planning` → `background_job_repository.enqueue_job`（既有 `job_type='goal_planning'`） | ❌ |
| `evidence_refs` | `decision_records.input_snapshot` | PLAN-003 的计划落库路径（PLAN-002 §4.4.1 落点裁决） | ❌ |
| 运行态序列 | `loop_runs.steps` | `loop_run_repository.mark_step` | ❌ |

> **本任务零新表、零新列**：计划证据是 `goal_plans` + `action_records` 的**投影**（architecture §6.7 ⑪ 明确「❌ 不建表，投影」）。这是本任务最容易偏离的地方——若为「计划证据」建表，会同时违反零迁移与「证据即投影」两条裁决。

---

# 8. Implementation Plan

## Step 1 — 证据通道值集扩展

1. 在 `app/models/reflection.py` 追加 `EVIDENCE_CHANNEL_PLAN = "plan"`，并扩 `EVIDENCE_CHANNELS` 为三元组（追加在末尾）。
2. 断言既有两值顺序与行为不变。
3. 单测：值集 3 值；既有两通道回归零差异。

## Step 2 — 三个计划证据窗聚合

1. `aggregate_plan_success_rate`：`goal_plans` 按 `status` × `goal.type` 聚合 → 成功率窗口。
2. `aggregate_step_failure_modes`：`action_records.steps` 按 `tool_id` × `failure_kind` 聚合 → 失败模式窗口。
3. `aggregate_criteria_decidability`：`goal_plans.sub_goals` 中 `criteria_result=None` 的步占比 → 可判定性窗口。
4. 复用既有上限常量、分组键范式、证据 id 形态与门槛函数（不自造数学）。
5. 证据不足 → 不产 Insight（零 LLM）。
6. 单测：三个窗口各有场景用例；证据不足零 LLM 断言。

## Step 3 — 接入既有三道闸

1. 计划通道经既有 `trigger_for_user` 走三道闸（门槛 / 当日额度 / 幂等入队）。
2. **零改动** `trigger_for_user` 的闸门逻辑（diff 为空断言）；只新增计划通道的窗口选取。
3. 单测：三闸与用户证据走**完全相同**的门槛；当日额度与幂等入队行为不变。

## Step 4 — `PlanningRevisionListener`

1. 新建 `app/services/planning/revision_listener.py`：`on_insight_created` / `enqueue_replan`。
2. 三门槛：类型 ∈ `PLAN_INFLUENCE_INSIGHT_TYPES`；置信度 ≥ `v25_plan_replan_min_confidence`；存在可映射 active 目标（按 `scope` 与目标 `domain` / `layer` 匹配）。
3. 幂等键 `plan_replan:{goal_id}:{insight_id}`。
4. **唯一动作**：`goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)`。
5. 注册进既有 `register_insight_created_listener`（第四个注册点）；受 `v25_plan_reflection_enabled` 门控。
6. 单测：三门槛负例各一；幂等重复触发只入队一次；隔离断言（G-REFLECT）。

## Step 5 — `evidence_refs` 闭环

1. 重规划轮次的 `PlanContext.evidence_refs` = 触发它的 Insight / 记忆 id 列表（由装配器从触发源取）。
2. 进 prompt 与 `GoalPlanRecord.evidence_refs`（经 PLAN-003 的落库路径）。
3. 进 `PlanRevision.evidence_refs`（供 PLAN-011 修订链投影）。
4. 单测：`evidence_refs` 正确落盘并注入 prompt（可判定用例）。

## Step 6 — Q8 裁决落地（四判据去重）

1. 固定优先序：`step_attempt_exhausted` > `criteria_undecidable` > `tool_persistently_unavailable` > `insight_driven`。
2. 同时命中时归一为一个理由码 + 一个重规划触发。
3. 双重幂等：本任务层 `plan_replan:{goal_id}:{insight_id}` + 既有 job 层 `has_job(idempotency_key)`。
4. 单测：四判据同时命中 → 只产生一个触发（专项目例）。

## Step 7 — 边界守卫与回归

1. 静态断言：`revision_listener.py` 零 `goal_repository` 写入 / 零工具注册表调用 / 零 `goal_plans` 写入。
2. 断言不在 `foreground` 关键路径：反思仍在 `memory_extract` 步与后台节拍里（阶段位置断言）。
3. 回归：既有三个消费者（`development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py`）行为不变（注册顺序、调用参数、副作用对照）。
4. Flag off 时证据聚合只有 `memory` 与 `tool` 两通道、无 `planning/revision_listener`，行为与 V2.4.0 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | `EVIDENCE_CHANNELS` 三值 | `("memory", "tool", "plan")`；既有两值相对顺序不变 |
| U2 | 计划成功率窗口 | 数据源 / 分组键 / 证据 id 形态与 §4.2.1 一致 |
| U3 | 步骤失败模式窗口 | 同上（按 `tool_id` × `failure_kind`） |
| U4 | 判据可判定性窗口 | 同上（`criteria_result=None` 占比） |
| U5 | 上限常量复用 | 复用 `TOOL_EVIDENCE_WINDOW_DAYS` / `MAX_MEMBERS` / `RECORD_SCAN_LIMIT`（零新造） |
| U6 | 分组键范式 | 沿用 `GROUP_KIND_*` 命名 |
| U7 | 证据 id 形态 | `plan:<goal_id>:<version>:<step_index>` |
| U8 | **证据不足零 LLM** | 样本低于 `v25_plan_reflection_min_samples` → 不产 Insight，零 LLM 调用（打桩） |
| U9 | 门槛一负例 | `insight.type ∉ PLAN_INFLUENCE_INSIGHT_TYPES` → 不触发 |
| U10 | 门槛二负例 | `confidence < v25_plan_replan_min_confidence` → 不触发 |
| U11 | 门槛三负例 | 无可映射 active 目标 → 不触发 |
| U12 | 幂等键 | `plan_replan:{goal_id}:{insight_id}` 重复触发只入队一次 |
| U13 | `enqueue_replan` 返回语义 | 首次触发 → `True`；重复 → `False` |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **三闸零豁免** | 计划证据与用户证据走**完全相同**的三道闸；当日额度（`_quota_used`）与幂等入队（`has_job`）行为不变 |
| I2 | `trigger_for_user` diff 为空 | 闸门逻辑零改动 |
| I3 | **隔离断言（G-REFLECT）** | `on_insight_created` 不改变任何 `GoalPlanRecord` / `GoalStatus` / 工具注册表状态（静态 + 运行时） |
| I4 | 唯一动作断言 | `revision_listener.py` 唯一的写副作用是 `enqueue_planning`；零 `goal_repository` 写入 |
| I5 | 监听器注册 | 第四个注册点存在且受 `v25_plan_reflection_enabled` 门控 |
| I6 | 既有三消费者回归 | `development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py` 行为不变（注册顺序、调用参数、副作用对照） |
| I7 | Q8 去重 | 四判据同时命中 → 只产生**一个**重规划触发（专项目例） |
| I8 | 双重幂等 | 本任务层 + 既有 job 层同时生效；同 `goal_id` 不产生第二个 job |
| I9 | `evidence_refs` 落盘 | 正确落 `GoalPlanRecord.evidence_refs` 并注入 prompt |
| I10 | 阶段位置断言 | 计划反思不在 `foreground` 关键路径（仍在 `memory_extract` 步与后台节拍） |
| I11 | 无性格类 Insight | 计划失败不产出性格类 Insight（类型断言） |
| I12 | 零迁移断言 | 迁移链头 `0046`；`insights` 类型 / `scope` 值集未扩；`background_jobs.job_type` 未扩 |
| I13 | **Flag off 逐字节一致** | 证据聚合只有 `memory` / `tool` 两通道；无 `planning/revision_listener` |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」反思回环** | 4 步计划执行 → 结果进证据窗 → 达门槛 → Insight「这类计划 4 步做不完」→ 监听器触发 → 新轮次规划 | 新轮次 `evidence_refs` 含该 Insight id；prompt 注入历史；新计划步数更合理 |
| S2 | 失败模式窗口 | 「查天气」步骤连续超时 | 产出 `capability_note` / `usage_preference`；下次规划避开该工具或调参 |
| S3 | 判据可判定性窗口 | 多步 `criteria_result=None` | 产出 `pattern` Insight（「判据太虚」） |
| S4 | 证据不足 | 样本 < 3 | 零 Insight、零 LLM 调用 |
| S5 | 三门槛拦截 | 类型不符 / 置信度不足 / 无 active 目标 各一次 | 均不触发（三个负例） |
| S6 | **Q8 四判据同时命中** | 步骤耗尽 + 判据不可判定 + 工具持续不可用 + Insight 达标，同时发生 | **只入队一个**重规划触发；理由码取优先序最高者 |
| S7 | 重复触发幂等 | 同一 Insight 对同一目标触发两次 | 只入队一次 |
| S8 | 隔离 | 触发后检查计划与工具状态 | `GoalPlanRecord` / `GoalStatus` / 工具注册表零变化 |
| S9 | 既有消费者回归 | 一次 Insight 产生 | 既有三个消费者的行为与本任务前逐字节一致 |
| S10 | Flag off | 反思子闸 off → 计划执行后 | 证据聚合只有两通道；无计划监听器；行为与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 三个计划证据窗各有场景用例（成功率 / 失败模式 / 判据可判定性）；证据不足时**不产 Insight**（零 LLM 断言）。
- 计划证据与用户证据走**完全相同**的三道闸（零豁免）；当日额度与幂等入队行为不变。
- **隔离断言（G-REFLECT）**：`on_insight_created` 不改变任何 `GoalPlanRecord` / `GoalStatus` / 工具注册表状态。
- 幂等键 `plan_replan:{goal_id}:{insight_id}` 重复触发只入队一次；`insight_driven` 与其他三条判据同时命中时只产生**一个**重规划触发（Q8 裁决落地用例）。
- 三道门槛各有负例：类型不在 `PLAN_INFLUENCE_INSIGHT_TYPES` / 置信度低于 `v25_plan_replan_min_confidence` / 无可映射 active 目标 → 均不触发。
- 重规划轮次的 `evidence_refs` 正确落 `GoalPlanRecord.evidence_refs` 并注入 prompt（可判定用例）。
- 不产出「性格类」Insight（计划失败不改变人格）；不在 `foreground` 关键路径做计划反思（阶段位置断言）。
- 监听器注册不改变既有三个消费者的行为（回归对照）。
- `EVIDENCE_CHANNELS` 恰三值，既有两值相对顺序不变。
- 计划证据是**投影**：不新建证据表（零新表断言）。
- Flag off 时证据聚合只有 `memory` 与 `tool` 两通道、无 `planning/revision_listener`，行为与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- `trigger_for_user` 的三道闸逻辑 diff 为空（零改动）；计划通道只用其既有门槛。
- `revision_listener.py` 的唯一写副作用是 `goal_planning.enqueue_planning`；零 `goal_repository` 写入、零工具注册表调用（静态断言）。
- 既有三个消费者（`development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py`）行为不变（注册顺序、调用参数、副作用对照）。
- `reflector` 的 Insight 产出路径零改动；防幻觉纪律与置信度校准不变。
- `background_jobs.job_type` 未扩（复用既有 `goal_planning`）；`insights` 的类型与 `scope` 值集未扩。
- 既有 `reflection` / `development` / `relationship_narrative` / `world/event_bridge` 相关测试零失败。
- 零迁移断言：迁移链头 `0046`。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`；计划证据**不建表**（投影）。
- **零新建反思系统**：不新建证据聚合框架（同构扩展既有）、不新建监听器机制（复用 `register_insight_created_listener`）、不新建闸门（复用 `trigger_for_user`）。
- **唯一接线**：本版本 Planning 侧反思接线只有 `PlanningRevisionListener` 一处（可 grep 计数）。
- **Q8 裁决留痕**：四判据优先序（事实优先于建议）与「只入队一次」的双重幂等机制写入本文档与代码注释；有专项目例。
- **源码核对留痕**：`EVIDENCE_CHANNEL_*` 的实际值集落点（`app/models/reflection.py::EVIDENCE_CHANNELS`）与 architecture §7.6 表述的差异已在本文件 §2.1 说明，实现按「值集在 `models/reflection.py`、聚合在 `services/reflection/evidence.py`」执行，与 architecture 意图一致。
- **文档一致**：本文件与 architecture §7.5.4 / §7.6 / §6.1 ⑦ / §8.6 / §9.6 G-REFLECT / §9.7 Q8 及 tasks.md PLAN-010 Acceptance Criteria 逐条对应，无自相矛盾。
