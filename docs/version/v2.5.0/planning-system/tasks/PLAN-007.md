# PLAN-007 Task Detail — Autonomy Integration

> 上游：[../architecture.md](../architecture.md) §7.3（与 Autonomy 2.0 集成）、§7.8（Life Loop 集成）、§7.9（Autonomy 契约行）、§3.2.3（Goal Priority 复用）；[../tasks.md](../tasks.md) PLAN-007
> 状态：DONE（已实现）
> 契约演进留痕（实现期裁决，2026-09-16）：`plan_facts` 由原定**六字段**扩为**七字段**
> —— 新增标量 `current_action_type`（计划当前步的动作身份）。理由：§4.3.2 / §6.3 / §8 Step 3.2
> 要求「本 intent 与计划当前步的 `action_type` 相同」才抑制，而六字段不含动作身份，该判定不可实现
> （策略层是纯函数，不得为取动作身份而反读计划）。裁决取「新增一个标量键」而非「放宽为同目标级
> 抑制」：字段数 6 → 7（仍有界、仍为标量、仍不含 `tool_id` / 参数 / 优先级），§4.3.2 的动作级语义
> 原样保留。同步改动：§1.1 / §4.1.2 / §4.2.1 / §4.3.1 / §6.1 / §6.2 / §8 Step 1~2 / §9.1 U2~U3 /
> §10.1 / §10.3 与 PLAN-012 §11 的任务行。唯一契约入口：`autonomy_policy.PLAN_FACTS_KEYS`。
> 范围红线：**Autonomy 决定「此刻做什么」/ Planning 决定「怎么做」/ Tool 负责执行**，三者串联且职责不重叠；不新建自治执行器、不新增候选源、不改六维权重、不新建 LLM 决策循环、**不让计划成为绕过额度的后门**。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-007 |
| **Task Name** | Autonomy Integration |
| **Priority** | P1 |
| **Dependencies** | PLAN-005, PLAN-006 |
| **Phase** | Phase 3 系统集成 |
| **建议提交** | `feat: V2.5.0 自治侧计划事实感知` |

## 1.1 Goal

让自治策略**感知计划事实**，并让计划推进意图经**既有候选面**进入决策：

1. **计划事实进策略快照（B9 关闭点）**：`PolicySnapshot` 新增**有界第五段** `plan_facts`（`active_goal_id` / `plan_version` / `current_step` / `current_action_type` / `steps_total` / `blocked_steps` / `last_advanced_at`），由既有行动事实收集**同源扩展、一处装配**；装配失败降级为空包，**不阻塞 tick**。
2. **计划态参与决策候选**：计划推进产生的意图经**既有 `goal_compile` 候选面**进入 `decision_pipeline.collect_candidates`；**不新增候选源、不改 `_SOURCE_PRIORITY` 数学、不改六维权重**。
3. **额度不绕过（评审红线）**：计划触发的执行仍走 `action_engine.run_action_planning(source="autonomy")`，因此 `action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` 与冷却窗口原样生效。

## 1.2 Scope

**包含**

- `app/services/autonomy_policy.py::PolicySnapshot` 新增 `plan_facts`（有界第五段）+ 一处装配点扩展。
- `_apply_action_adjustments` 同源扩展：计划正在推进时抑制抢同一动作的判定（**复用既有调制机制，不新增裁决步**）。
- `autonomy_engine.tick` 的 `plan_facts` 装配（**二十步序列零改动**）。
- 计划推进意图经既有 `goal_compile` 候选面的接线（**不新增候选源**）。
- 额度与冷却未放宽的负例用例。
- 三者分工对照表的可举证清单（G-BOUNDARY）。
- `v25_plan_autonomy_enabled` 门控。

**不包含（Non-Scope）**

- 计划生成 / 拆解 / 调度 / 执行 / 观测 / 修订本体（PLAN-003 ~ PLAN-005）。
- 工具治理（PLAN-006）。
- 世界集成（PLAN-008）、记忆集成（PLAN-009）、反思集成（PLAN-010）。
- `decision_pipeline` 的六维权重数学、`_SOURCE_PRIORITY` 表、四闸门的**任何改动**。
- `autonomy_policy.evaluate` 八步裁决顺序的**任何改动**。
- 调试端点（PLAN-011）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 断层 **B9（Autonomy 侧对计划无感知）**：

| 断层 | 现状 | 本任务的关闭方式 |
|---|---|---|
| B9 | `PolicySnapshot` 有 `world_facts` / `action_facts` / `tool_facts` / `tool_insights`，**无 `plan_facts`** | 新增有界第五段，使自治策略知道「用户身上还有一个进行中的两步计划」，避免与计划抢同一动作（额度被重复消耗） |
| 反向断链 | 计划「该做下一步了」与自治「要不要主动」不在同一张评分表上竞争 | 计划推进意图经**既有 `goal_compile` 候选面**（优先级 P2 原样保留）进入 `decision_pipeline` |

**本任务最关键的一条纪律**：接线必须是**增量**的。`autonomy_engine.tick` 的二十步序列、`autonomy_policy.evaluate` 的八步裁决、`decision_pipeline` 的六维权重与 `_SOURCE_PRIORITY` 表——**四项全部零改动**。任何「顺手重构」都会使 PLAN-012 的快照对照失败。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Autonomy 2.0 / Decision Pipeline** | **本任务的核心交互面**：`PolicySnapshot` / `autonomy_policy.evaluate` / `decision_pipeline` / `autonomy_engine.tick` |
| **Goal System** | `GoalStack` / `SelectedGoal` 是既有输入；`compute_priority` 是唯一优先级算法（PLAN-001 冻结） |
| **Planning System** | 提供 `plan_facts` 的数据源与推进意图 |
| **Tool System V2.4.0** | `tool_facts` / `tool_insights` 为本任务 `plan_facts` 的**同源样板**（同款有界与降级纪律） |
| **Memory 2.0 / Reflection** | **不涉及**（属 PLAN-009 / PLAN-010） |
| **World Simulation** | `world_facts` 既有；本任务不新增世界事实 |

**关键事实（已核对真实源码）**

- `app/services/autonomy_policy.py::PolicySnapshot` 已为 dataclass，既有字段含 `generating` / `has_active_action` / `last_proactive_at` / `attempt_count` / `intimacy` / `tension` / `mood` / `current_activity` / `selected_goal_type` / `goal_degraded` / `extra_flags` / `world_facts` / `action_facts` / `tool_facts` / `tool_insights` / `respect` / `comfort` / `conflict_status` / `neglect_active` / `unlocks` / `trust` / `stage` / `relationship_patterns`——**四段事实（`world_facts` / `action_facts` / `tool_facts` / `tool_insights`）均已存在且默认空 dict**，`plan_facts` 将是**第五段**。
- `autonomy_policy` 已有调制函数族：`_apply_world_adjustments` / `_apply_action_adjustments` / `_apply_tool_adjustments` / `_apply_tool_insight_adjustments` / `_apply_relationship_rules` / `_cooldown_passed` / `_activity_busy` / `_reconciliation_already_used` / `_parse_hhmm` / `in_quiet_hours` / `effective_interval_minutes` / `trigger_priority`，以及 `TRIGGER_PRIORITY` / `HIGH_PRIORITY_OVERRIDE` / `SLEEPY_MOODS` / `BUSY_ACTIVITY_KEYWORDS` / `WORLD_PROACTIVE_EVENT_TYPES` / `STAGE_RANK` / `_PROACTIVE_GOAL_TYPES`。
- `app/services/decision_pipeline.py`：`_SOURCE_PRIORITY` 表（`"goal_compile": P2`）、`Candidate` / `DecisionResult` / `collect_candidates` / `assign_priorities` / `score_candidates` / `run_risk_gates` / `select` / `_intention_for` / `run_pipeline`；六维打分函数 `_state_fit` / `_relationship_fit` / `_timing` / `_interest` / `_cost`（+ 相关性）；`_ACTION_SOURCES = ("autonomy_trigger", "goal_compile", "turn_intention")`；`collect_candidates` 已在 `goal_compile` 面产出候选。
- `app/application/agent_runtime/profiles.py`：`autonomous_tick` 的 `stages` 含 `goal_supply` / `goal_advance`。
- `app/services/reflection/tool_feed.py::autonomy_signal(user_id, *, limit)` 是 `tool_insights` 段的既有来源——`plan_facts` 应照此形态实现（有界、失败降级）。
- 迁移链头 0046。

## 2.2 为什么需要本任务

architecture §7.3 的核心裁决是：**Autonomy 决定做什么 / Planning 决定怎么做 / Tool 负责执行。三者是串联关系，任一层不得越位。**

但串联关系有一个必须处理的**竞争问题**：计划正在推进第 3 步（比如「提醒用户准备面试」），而自治策略同时判定「此刻应该主动关心用户」——两件事可能落到**同一个动作**上。若无 `plan_facts`：

- 自治策略不知道计划在推进，会重复发起同类动作；
- `action_max_active_per_user` 与 `autonomy_action_daily_limit` 被**重复消耗**；
- 用户侧表现为「同一种关心连发两次」。

`plan_facts` 就是让自治策略**看得见计划**，从而在同一张评分表上做出取舍。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | `PolicySnapshot.plan_facts`（有界第五段）字段契约与装配 | 字段 + 装配点 |
| R2 | `plan_facts` 装配失败降级为空包且**不阻塞 tick** | 契约 + 用例 |
| R3 | 计划推进意图经**既有 `goal_compile` 候选面**进入决策 | 接线（不新增源） |
| R4 | 额度与冷却未放宽的可判定负例 | 用例集 |
| R5 | 三者分工对照表（G-BOUNDARY 举证清单） | 对照表 + 输出契约断言 |
| R6 | `v25_plan_autonomy_enabled` 门控与串行链 | 配置 + 用例 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 计划生成 / 拆解 / 调度 / 执行 / 观测 / 修订 | PLAN-003 ~ PLAN-005 |
| N2 | 工具治理链路 | PLAN-006 |
| N3 | `decision_pipeline` 的六维权重与 `_SOURCE_PRIORITY` 数学 | **永不**（零改动） |
| N4 | `autonomy_policy.evaluate` 八步裁决顺序 | **永不**（零改动） |
| N5 | `autonomy_engine.tick` 二十步序列 | **永不**（零改动） |
| N6 | 新建自治执行器 | **永不**（复用 `_produce_autonomy_action`） |
| N7 | 世界 / 记忆 / 反思集成 | PLAN-008 / PLAN-009 / PLAN-010 |
| N8 | 调试端点 | PLAN-011 |

## 3.3 职责边界一句话

> **Autonomy 只出 `AutonomyVerdict` + intention（要不要主动）；Planning 只出 `GoalPlanRecord` + `PlanStepSpec[]`（分几步、每步用什么）；Tool 只出 `ToolResult`（真的动手了没）。三者无交叉写面。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/services/autonomy_policy.py` | 既有 | **增量扩展**：`PolicySnapshot` +1 段；新增一个 `_apply_plan_adjustments`（与既有四个调制函数同款形态） | 只读 `plan_facts`（纯数据） |
| `app/application/autonomy_engine.py` | 既有 | **最小接线**：`plan_facts` 在既有行动事实收集处**同源扩展、一处装配**；`tick` 二十步序列零改动 | → `goal_repository`（只读 `list_active_plans`）/ `PlanScheduler`（只读） |
| `app/services/decision_pipeline.py` | 既有 | **零改动**（计划意图经既有 `goal_compile` 候选面进入） | — |
| `app/services/reflection/tool_feed.py::autonomy_signal` | 既有 | 形态样板（有界 + 降级） | — |

**分层纪律（静态断言强制）**
- `autonomy_policy.py` 保持**纯函数 + 纯数据**：不 import 仓储，`plan_facts` 由调用方注入。
- `plan_facts` 装配点**唯一**（一处），不在多个 tick 阶段重复装配。
- `decision_pipeline.py` 零改动（diff 为空）。

### 4.1.2 Component 划分

```text
app/services/autonomy_policy.py（既有，增量扩展）
├── PolicySnapshot
│     ...既有 24 字段...
│     + plan_facts: dict = field(default_factory=dict)      ← 新增第五段
└── _apply_plan_adjustments(verdict, snapshot) -> AutonomyVerdict   ← 新增调制函数
      # 与 _apply_action_adjustments / _apply_tool_adjustments 同款形态
      # 语义：计划正在推进时，抑制抢同一动作的主动性（不改变八步裁决顺序）

app/application/autonomy_engine.py（既有，最小接线）
├── _collect_plan_facts(user_id) -> dict     ← 新增，与既有 _collect_action_facts 同源
│     active_goal_id / plan_version / current_step / current_action_type
│     / steps_total / blocked_steps / last_advanced_at
│     失败 → {}（不阻塞 tick）
└── tick（二十步序列零改动，plan_facts 在既有收集点装配一次）

app/services/decision_pipeline.py（零改动）
└── collect_candidates → goal_compile 候选面（P2 原样保留）
      计划推进产生的意图经此面进入，不新增候选源
```

### 4.1.3 数据流：双向接线

```text
 ┌──────────────────────────────────────────────────────────────────┐
 │ ① Autonomy：决定「此刻做什么」                                     │
 │    autonomy_engine.tick（二十步，零改动）                          │
 │      trigger_evaluator（三类触发源）                               │
 │      autonomy_policy.evaluate（八步裁决，零改动）→ AutonomyVerdict  │
 │      decision_pipeline.run_pipeline（五段 + 六维 + 四闸，零改动）    │
 │    ⇒ 输出：act/wait/ignore + intention                             │
 └───────────────────────────┬──────────────────────────────────────┘
                             │ intention（做什么）
                             ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ ② Planning：决定「怎么做」                                         │
 │    PlanContextAssembler → PlanningEngine.plan → TaskDecomposer     │
 │    → PlanScheduler → ⇒ 输出 GoalPlanRecord + PlanStepSpec[]        │
 └───────────────────────────┬──────────────────────────────────────┘
                             │ PlanStep（怎么做）
                             ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ ③ Tool：真正动手（六闸门 + 五段短路）                              │
 │    ⇒ 输出 ToolResult{status, effects, observations, usage}         │
 └──────────────────────────────────────────────────────────────────┘

 —— 本任务新增的两条反向接线 ——
 ④ plan_facts 上行：Planning 运行态 → PolicySnapshot.plan_facts（有界第五段）
 ⑤ 意图下行：计划推进意图 → 既有 goal_compile 候选面 → decision_pipeline
```

## 4.2 Core Model

### 4.2.1 `PolicySnapshot.plan_facts`（本任务新增的第五段）

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `active_goal_id` | str \| None | `goal_repository.list_active_plans(user_id)` | 有进行中计划的目标 id |
| `plan_version` | int \| None | `GoalPlanRecord.version` | 当前生效版本 |
| `current_step` | int \| None | `PlanScheduler.current_step(plan).index` | 下一个待执行步（无则 `None`） |
| **`current_action_type`** | str \| None | `PlanScheduler.current_step(plan).capability` | 当前步的动作身份（**契约演进新增键**，见文首留痕；非工具细节，不含 `tool_id` / 参数） |
| `steps_total` | int | `len(plan.sub_goals)` | 步骤总数 |
| `blocked_steps` | int | `PlanScheduler.blocked_reason` 计数 | 被阻塞步数（`off_surface` / `cooldown` / `predecessor_failed`） |
| `last_advanced_at` | str \| None | `PlanAdvance.at`（最近一次 `advanced`，经既有 `decision_records`（`kind='goal_lifecycle'`）只读投影） | ISO 时刻字符串 |

**示例形态（architecture §7.3 接线 1）**

```text
plan_facts = {
  "active_goal_id": "g_xxx",             # 有进行中计划的目标
  "plan_version": 2,
  "current_step": 3,
  "current_action_type": "create_reminder",
  "steps_total": 4,
  "blocked_steps": 0,
  "last_advanced_at": "2026-09-15T20:10:00"
}
```

**有界与降级纪律（与既有四段同款）**

| 纪律 | 要求 |
|---|---|
| 有界 | 字段数固定为 **7**（六字段 + `current_action_type`，见文首契约演进留痕）；不做无界列表展开（不把全部步骤塞进 `plan_facts`） |
| 单目标 | 只反映**一个** active 计划（取值规则：最近 `updated_at` 的 active 计划；多计划时取最新） |
| 降级 | 装配失败 → `{}`（与既有四段默认空 dict 一致）；**不阻塞 tick** |
| 只读 | 装配只经 `goal_repository` 只读接口 + `PlanScheduler` 纯函数 |
| 门控 | `v25_plan_autonomy_enabled` off → `plan_facts` **不存在**（保持 `{}` 原状） |

### 4.2.2 三者分工逐项对照（G-BOUNDARY 举证清单）

| 关注点 | Autonomy（决定做什么） | Planning（决定怎么做） | Tool（负责执行） |
|---|---|---|---|
| 问题 | 此刻该不该主动？做哪件事？ | 这件事分几步？每步用什么？ | 这一步真的动手 |
| 权威函数 | `autonomy_policy.evaluate` + `decision_pipeline.run_pipeline` | `goal_planning.plan_goal`（强化版，经 `PlanningEngine`） | `ToolRegistry` + `ToolExecutor` |
| 输入契约 | `PolicySnapshot` + `GoalStack` + `TriggerSignal` | `PlanContext` + `GoalRecord` | `ToolInvocation` + `ToolContext` |
| 输出契约 | `AutonomyVerdict`（`act`/`wait`/`ignore`）+ intention | `GoalPlanRecord` + `PlanStepSpec[]` | `ToolResult` |
| 决策粒度 | 一轮一次（单意图） | 一目标一份（多步） | 一步一次（单调用） |
| 触发频度 | tick / 触发源驱动（分钟级） | 事件驱动（创建 / 阻塞 / 重规划） | 步骤驱动（秒级） |
| 额度与预算 | `autonomy_max_attempts_per_episode=2`、`autonomy_action_daily_limit=1`、`autonomy_min_interval_minutes=240` | `v2_autonomy_planning_max_attempts=3`、`v2_autonomy_subgoal_max_count=5`、`v25_plan_revision_budget` | `action_max_active_per_user=5`、`action_retry_max_attempts=2`、工具 `rate_limit` |
| **不做什么** | 不拆步骤、不选工具、不管参数细节 | 不判断「该不该主动」、不直接执行、不做退避 | 不做重试决策、不写世界、不管计划 |
| 既有断层闭合 | B9（`plan_facts` 进 `PolicySnapshot`） | B1 ~ B8 | — |

### 4.2.3 计划推进意图进入候选面的契约（不新增候选源）

| 项 | 契约 |
|---|---|
| 候选源 | **既有 `goal_compile`**（`decision_pipeline._SOURCE_PRIORITY["goal_compile"] = P2` **原样保留**） |
| 候选构造 | 由既有 `collect_candidates` 在 `goal_compile` 面产出（PLAN-003/005 的计划态使该面已有候选） |
| 优先级 | P2（不变） |
| 权重 | 六维（`_state_fit` / `_relationship_fit` / `_timing` / `_interest` / `_cost` / 相关性）**零改动** |
| 四闸 | `run_risk_gates` 的 `_persona_gate` / `_relationship_gate` / `_gate_capability` 等**零改动** |
| 禁止 | 不新增 `Candidate.source` 值、不新增 `_SOURCE_PRIORITY` 条目、不改 `_ACTION_SOURCES` 元组 |

### 4.2.4 额度与冷却（未放宽，本任务断言）

| 关注 | 设置 | 生效位置 |
|---|---|---|
| 活跃行动上限 | `action_max_active_per_user` | `action_engine` 六闸门 `quota_exceeded` |
| 主动日额度 | `autonomy_action_daily_limit` | `autonomy_policy` / `autonomy_engine` 既有 |
| 最小间隔 | `autonomy_min_interval_minutes` | `autonomy_policy.effective_interval_minutes` / `_cooldown_passed` |
| 每轮尝试 | `autonomy_max_attempts_per_episode` | `autonomy_policy` 既有 |
| 计划触发时 | 仍走 `action_engine.run_action_planning(source="autonomy")` | **全部原样生效** |

## 4.3 State Machine

本任务**不新增状态机**。下表为自治裁决状态与计划状态的交互。

### 4.3.1 `AutonomyVerdict`（既有三态）× 计划状态

| 计划状态 | `plan_facts` 形态 | 对自治裁决的影响 |
|---|---|---|
| 无 active 计划 | `{}`（空包） | 无影响（既有行为逐字节一致） |
| 有 active 计划，推进正常 | 七字段齐全，`blocked_steps=0` | `_apply_plan_adjustments` 抑制「抢同一动作」的主动性 |
| 有 active 计划，步骤阻塞 | `blocked_steps > 0`（`PlanScheduler.blocked_reason` 的 0/1 计数） | 同上；不额外放宽（`blocked_steps` 不参与调制） |
| 有 active 计划，全部步骤终态 | `current_step=None` | 视为无推进中的计划 |
| `v25_plan_autonomy_enabled` off | `{}` | 无影响（原状） |

### 4.3.2 `_apply_plan_adjustments` 的调制语义

```text
输入：AutonomyVerdict（前序调制后）+ PolicySnapshot（含 plan_facts）
    │
    ├─ plan_facts 为空 ─────────────────► 原样返回（零影响）
    ├─ current_step is None ────────────► 原样返回（无推进中的步）
    └─ 有推进中的步
           ├─ 本 intent 与计划当前步的 action_type 相同（同一动作）
           │     → 抑制：降级 verdict（避免与计划抢同一动作）
           └─ 不同动作
                 → 原样返回（可正常主动）
```

**纪律**：本函数只在**既有调制链**中追加一环，**不改变八步裁决顺序**、不改变 `TRIGGER_PRIORITY` 数学、不改变 `HIGH_PRIORITY_OVERRIDE` 语义（P0 / P1 触发器仍可越过）。

## 4.4 二十步 tick 序列的零改动（评审要点）

```text
autonomy_engine.tick（既有，二十步）
    ...
    ├─ <既有行动事实收集点>          ← plan_facts 在此处"同源扩展、一处装配"
    │     action_facts  ← 既有
    │     plan_facts    ← 新增（同一处装配，不新增阶段）
    ...
```

| 断言 | 要求 |
|---|---|
| 步数 | 二十步不变 |
| 顺序 | 顺序不变（形状快照对照） |
| `_produce_autonomy_action` | 形态不变 |
| 装配点 | `plan_facts` 只在一处装配（静态断言：装配函数调用点唯一） |

---

# 5. System Interaction

## 5.1 与 Autonomy（本任务核心）

| 关注点 | 存量 | 本任务 |
|---|---|---|
| `PolicySnapshot` 四段事实 | `world_facts` / `action_facts` / `tool_facts` / `tool_insights` | **新增第五段 `plan_facts`** |
| `autonomy_policy.evaluate` 八步 | 既有顺序 | **零改动**；只追加一个调制函数 |
| `decision_pipeline` 五段 + 六维 + 四闸 | 既有 | **零改动**；计划意图经既有 `goal_compile` 面进入 |
| `autonomy_engine.tick` 二十步 | 既有 | **零改动**；`plan_facts` 在既有收集点装配 |
| `_produce_autonomy_action` | 既有 | **零改动**（不新建自治执行器） |
| 额度数学 | 既有 | **未放宽**（断言） |

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `tool_facts` / `tool_insights` | 既有四段之一（本任务的形态样板） | 只参照形态，不改内容 |
| 工具面 / 选择器 / 执行器 | 既有 | **不涉及**（治理属 PLAN-006） |

**为什么不涉及**：本任务不改工具侧任何逻辑；`plan_facts` 只携带**计划**的运行态（版本、步号、阻塞数），不携带工具细节。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `world_facts` | 既有四段之一 | **零改动** |
| 世界事实进 `PlanContext` | PLAN-008 | **不涉及** |

**为什么不涉及**：世界→计划的预读装配属 PLAN-008；本任务只处理「计划运行态→自治策略」这一条反向接线。

## 5.4 与 Memory

**完全不涉及。**

| 关注点 | 本任务 | 原因 |
|---|---|---|
| 记忆写入 | 不涉及 | 属 PLAN-009，且必须经 `memory_policy` R1~R8 |
| 记忆检索 | 不涉及 | `PlanContext.memories` 由 PLAN-003 装配 |

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `tool_insights` | 既有四段之一（由 `reflection/tool_feed.py::autonomy_signal` 提供） | **零改动** |
| 计划证据窗 / 重规划监听器 | PLAN-010 | **不涉及** |

**为什么不涉及**：本任务不读 Insight、不参与证据聚合；`plan_facts` 的数据源是 `goal_plans` + `PlanScheduler`，与反思无关。

## 5.6 与 Goal System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `GoalStack` / `SelectedGoal` | 自治既有输入 | **零改动** |
| `goal_arbitration.compute_priority` | 唯一优先级算法（PLAN-001 冻结） | **不重算**；`plan_facts` 不携带优先级 |
| `goal_repository.list_active_plans` | `plan_facts` 只读来源 | **只读消费** |

**纪律**：`plan_facts` **不引入第二套优先级**——它只陈述「有计划在跑、跑到第几步」，不参与目标排序。

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 计划生成 / 拆解 | 不涉及 | PLAN-003 / PLAN-004 |
| 调度 / 执行 / 观测 / 修订 | 不涉及（本任务只读其运行态） | PLAN-005 |
| 工具治理 | 不涉及 | PLAN-006 |
| outbox / `event_bridge` | 不涉及 | PLAN-008 |
| `memories` / `memory_policy` | 不涉及 | PLAN-009 |
| `reflection/evidence.py` / 监听器 | 不涉及 | PLAN-010 |
| `goal_repository` 只读扩展 / 调试端点 | 不涉及 | PLAN-011 |

---

# 6. API / Interface Design

本任务不新增公开接口；下表为被本任务扩展 / 加固的契约。

## 6.1 `PolicySnapshot` 扩展接口

```text
@dataclass
class PolicySnapshot:
    ...既有 23 字段...
    plan_facts: dict = field(default_factory=dict)      # 本任务新增（有界第五段，默认空包，位于既有字段之后）
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | `plan_facts` 默认 `{}`；Flag off 时**不存在**（保持 `{}` 原状） | 快照对照 |
| D2 | 字段数固定为 7（六字段 + `current_action_type`），不做无界展开 | 结构断言（`autonomy_policy.PLAN_FACTS_KEYS` 为唯一声明处） |
| D3 | `autonomy_policy.py` 保持纯函数 + 纯数据：不 import 仓储 | 静态断言 |
| D4 | `plan_facts` **不携带优先级 / 工具细节**（避免职责外溢） | 字段快照对照 |

## 6.2 `plan_facts` 装配接口（`autonomy_engine` 内部）

```text
_collect_plan_facts(user_id: str) -> dict
    # 单目标取值规则：最近 updated_at 的 active 计划
    # 七字段：active_goal_id / plan_version / current_step / current_action_type
    #         steps_total / blocked_steps / last_advanced_at
    # 装配失败 → {}（不抛错、不阻塞 tick）
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D5 | 装配点**唯一**（一处，与既有行动事实收集同源） | 静态断言（调用点计数 = 1） |
| D6 | 装配全程**只读**（`goal_repository` 只读接口 + `PlanScheduler` 纯函数） | 打桩断言零写库 |
| D7 | 装配失败降级为空包且**不阻塞 tick** | 用例：注入异常 → tick 正常完成，`plan_facts == {}` |
| D8 | `v25_plan_autonomy_enabled` off → 不装配（`{}`） | 门控用例 |

## 6.3 调制接口（`autonomy_policy` 内部）

```text
_apply_plan_adjustments(verdict: AutonomyVerdict, snapshot: PolicySnapshot) -> AutonomyVerdict
    # 空包 / current_step is None → 原样返回
    # 有推进中的步且 intent 与当前步 action_type 相同 → 降级 verdict（抑制抢同一动作）
    # 其余 → 原样返回
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D9 | 纯函数（无 IO、无 LLM） | 静态断言 |
| D10 | **不改变八步裁决顺序**、不改 `TRIGGER_PRIORITY` 数学、不改 `HIGH_PRIORITY_OVERRIDE`（P0 / P1 仍可越过） | 顺序快照 + P0/P1 用例 |
| D11 | `plan_facts` 为空时零影响 | 用例（原状逐字节一致） |

## 6.4 输出契约断言（G-BOUNDARY）

| # | 断言 | 判定方式 |
|---|---|---|
| B1 | Autonomy 只出 `AutonomyVerdict` + intention | 静态 + 运行时断言：Autonomy 路径零 `GoalPlanRecord` 写、零 `PlanStepSpec` 写 |
| B2 | Planning 只出 `GoalPlanRecord` + `PlanStepSpec[]` | 静态 + 运行时断言：Planning 路径零 `AutonomyVerdict` 写、零 intention 写 |
| B3 | Tool 只出 `ToolResult` | 静态 + 运行时断言：Tool 路径零计划写、零裁决写 |
| B4 | 三者无交叉写面 | 写面矩阵：三者的写表集合两两不相交（`decision_records` 为共享只增表，按 `kind` / `decision` 区分） |

## 6.5 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| `plan_facts` 装配异常 | 只读接口失败 / 数据异常 | 捕获 → `{}`；log；**不阻塞 tick** |
| `PlanScheduler` 调用异常 | 纯函数不应抛（若抛为实现缺陷） | 捕获 → `{}`；log；不阻塞 tick |
| `_apply_plan_adjustments` 异常 | 纯函数不应抛 | 捕获 → 原样返回 verdict（保守：不因调制失败改变裁决） |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | `plan_facts` 是**运行期内存段**，进 `loop_runs.steps` / `decision_records.input_snapshot`（既有 JSON 列） |
| 新列 | 无 | `PolicySnapshot` 是 dataclass，不落库 |
| 新索引 | 无 | `plan_facts` 装配复用既有 `list_active_plans`（既有查询） |
| 改 CHECK | 无 | `decision_records.kind` 五值不变（自治路径既有 `proactive_autonomy` 等） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| 自治决策审计 | `decision_records` | 既有自治决策记录写入（`kind='proactive_autonomy'` 等既有值） | ❌ |
| 运行态序列 | `loop_runs.steps` | `loop_run_repository.mark_step` | ❌ |
| 行动计划 | `action_records` | 经既有 `action_engine.run_action_planning` | ❌ |

> **本任务的写入量为零新增**：`plan_facts` 只读装配、只进内存与既有 JSON 快照；不新增任何持久化面。

---

# 8. Implementation Plan

## Step 1 — `PolicySnapshot` 扩展与门控

1. 在 `app/services/autonomy_policy.py` 的 `PolicySnapshot` 末尾追加 `plan_facts: dict = field(default_factory=dict)`（**位置在 `tool_insights` 之后，保证既有字段顺序不变**）。
2. `v25_plan_autonomy_enabled` off → 装配器不写入（保持 `{}`）。
3. 单测：默认值、字段数固定为 7、Flag off 时为空包（且 off 时零读取）。

## Step 2 — `plan_facts` 装配（一处，同源扩展）

1. 在 `autonomy_engine` 的既有行动事实收集处新增 `_collect_plan_facts(user_id)`，与既有事实收集**同源、同时刻、同一处**调用。
2. 取「最近 `updated_at` 的 active 计划」：`goal_repository.list_active_plans(user_id)` + `get_latest_plan`。
3. 计算七字段：`current_step` / `current_action_type` 由 `PlanScheduler.current_step` 得出，`blocked_steps` 由 `blocked_reason` 得出（均为纯函数）。
4. `last_advanced_at` 取最近一次 `PlanAdvance`（`decision` 为 `advanced`）的时刻（扫描窗内按 `at` 求最大，缺省回退落库时刻）。
5. 装配失败 → `{}`，log，**不阻塞 tick**。
6. 单测：七字段正确；多计划取最新；无计划为空包；装配失败降级且不阻塞 tick；装配点唯一（静态）。

## Step 3 — `_apply_plan_adjustments` 调制

1. 在 `autonomy_policy` 的既有调制链中追加 `_apply_plan_adjustments`（与 `_apply_action_adjustments` / `_apply_tool_adjustments` 同款形态与位置）。
2. 逻辑：空包 / `current_step is None` → 原样返回；有推进中的步且 intent 与当前步 `action_type` 相同 → 降级 verdict；其余原样返回。
3. 断言：`TRIGGER_PRIORITY` 数学未改；`HIGH_PRIORITY_OVERRIDE`（P0 / P1）仍可越过。
4. 单测：空包零影响；同动作被抑制；不同动作不受影响；P0 / P1 仍越过。

## Step 4 — 计划推进意图经既有候选面

1. 确认计划推进产生的意图经**既有 `goal_compile` 候选面**进入 `decision_pipeline.collect_candidates`（P2 原样保留）。
2. **零改动** `decision_pipeline.py`（diff 为空断言）。
3. 断言未新增 `Candidate.source` 值、未新增 `_SOURCE_PRIORITY` 条目、未改 `_ACTION_SOURCES`。
4. 单测：计划推进意图确实经 `goal_compile` 面进入；候选优先级为 P2。

## Step 5 — 额度与冷却未放宽的负例

1. `action_max_active_per_user`：达上限 → 计划步骤不执行、不产生 `ActionRecord`。
2. `autonomy_action_daily_limit`：达上限 → 计划触发的执行被拒。
3. `autonomy_min_interval_minutes`：间隔未到 → 计划触发的执行被拒。
4. 冷却窗口：同理。
5. 单测：四条负例逐条通过。

## Step 6 — G-BOUNDARY 输出契约断言

1. 写面矩阵：Autonomy / Planning / Tool 三者的写表集合两两不相交。
2. 静态断言：Autonomy 路径零 `GoalPlanRecord` / `PlanStepSpec` 写；Planning 路径零 `AutonomyVerdict` / intention 写；Tool 路径零计划写。
3. 运行时断言：对一次完整链路（计划推进触发一次执行）记录各层输出，断言输出类型恰为各自契约类型。
4. 单测：B1~B4 四条断言可判定。

## Step 7 — 序列快照回归

1. `autonomy_engine.tick` 二十步序列形状快照对照零差异。
2. `autonomy_policy.evaluate` 八步裁决顺序快照对照零差异。
3. `_produce_autonomy_action` 形态快照对照零差异。
4. `decision_pipeline` 六维权重与 `_SOURCE_PRIORITY` 快照对照零差异。
5. Flag off 时 `PolicySnapshot.plan_facts` 为 `{}`（原状），行为与 V2.4.0 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | `PolicySnapshot.plan_facts` 默认值 | `{}`；既有字段顺序与默认值未变 |
| U2 | `plan_facts` 字段数 | 恰 7 个；全部标量；无无界列表 |
| U3 | 七字段取值正确 | `active_goal_id` / `plan_version` / `current_step` / `current_action_type` / `steps_total` / `blocked_steps` / `last_advanced_at` 各可追溯 |
| U4 | 多计划取最新 | 两个 active 计划 → 取 `updated_at` 最新者 |
| U5 | 无 active 计划 | `{}` |
| U6 | 装配失败降级 | 注入异常 → `{}`；**tick 正常完成** |
| U7 | `_apply_plan_adjustments` 空包零影响 | verdict 原样返回 |
| U8 | 同动作被抑制 | intent 与当前步 `action_type` 相同 → verdict 降级 |
| U9 | 不同动作不受影响 | verdict 原样返回 |
| U10 | P0 / P1 仍可越过 | `HIGH_PRIORITY_OVERRIDE` 语义未变 |
| U11 | `plan_facts` 不含优先级 / 工具细节 | 字段快照对照 |
| U12 | 装配点唯一 | 静态断言：装配函数调用点计数 = 1 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | `autonomy_engine.tick` 二十步序列不变 | 形状快照对照零差异 |
| I2 | `autonomy_policy.evaluate` 八步顺序不变 | 顺序快照对照零差异 |
| I3 | `decision_pipeline` 六维权重与 `_SOURCE_PRIORITY` 未改 | 快照对照零差异 |
| I4 | 未新增候选源 | `Candidate.source` 值集未扩；`_ACTION_SOURCES` 元组未改 |
| I5 | 计划推进意图经 `goal_compile` 面 | 用例：候选源为 `goal_compile`，优先级 P2 |
| I6 | `_produce_autonomy_action` 形态未变 | 快照对照 |
| I7 | 装配全程只读 | 打桩断言：`_collect_plan_facts` 零写库 |
| I8 | 额度未放宽（四条负例） | `action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` / 冷却窗口各一例；额度耗尽时计划步骤不执行、不产生 `ActionRecord` |
| I9 | G-BOUNDARY 写面矩阵 | 三者写表集合两两不相交 |
| I10 | `plan_facts` 门控 | `v25_plan_autonomy_enabled` off → `{}`（原状） |
| I11 | **Flag off 逐字节一致** | `PolicySnapshot.plan_facts` 不存在（`{}` 原状）；行为与 V2.4.0 逐字节一致 |
| I12 | 零迁移断言 | 迁移链头 `0046`；`decision_records.kind` 五值未变 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」+ 自治竞争** | 计划推进到第 3 步 → 自治 tick 同时判定「应主动关心用户」且 intent 与当前步同动作 | `plan_facts` 非空 → 自治抑制该主动性；额度未被重复消耗；只产生一条 `ActionRecord` |
| S2 | 计划推进中但动作不同 | 计划当前步为「查天气」，自治 intent 为「发消息关心」 | 自治正常主动（不同动作不受抑制） |
| S3 | 高优先级触发器 | P0 / P1 触发源进来 | 仍越过计划抑制（`HIGH_PRIORITY_OVERRIDE` 语义不变） |
| S4 | 装配失败 | `list_active_plans` 抛异常 | `plan_facts == {}`；tick 正常完成；下一 tick 继续 |
| S5 | 额度耗尽 | `action_max_active_per_user` 达上限 | 计划步骤不执行、不产生 `ActionRecord`（负例） |
| S6 | 计划已完成 | 全部步骤终态 | `plan_facts` 可能仍存在但 `current_step=None` → 自治不受抑制 |
| S7 | Flag off | 总闸 off → 自治 tick | `plan_facts` 为 `{}`；行为与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 自治 tick 的 `plan_facts` 有界（受既有可观测预算约束）且各字段可追溯；装配失败降级为空包且**不阻塞 tick**（用例）。
- **额度与冷却未放宽**：`action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` / 冷却窗口的生效用例通过；负例：额度耗尽时计划步骤不执行、不产生 `ActionRecord`。
- 六维权重数学与候选优先级表未改（快照对照零差异）；未新增候选源；计划推进意图确实经既有 `goal_compile` 面进入（优先级 P2 原样保留）。
- `autonomy_engine.tick` 步数与顺序不变（形状快照对照）；`_produce_autonomy_action` 形态未变。
- `autonomy_policy.evaluate` 八步裁决顺序不变；`TRIGGER_PRIORITY` 数学未改；`HIGH_PRIORITY_OVERRIDE`（P0 / P1）仍可越过。
- `plan_facts` 字段数固定为 7（六字段 + `current_action_type`），不含优先级与工具细节；装配点唯一（静态断言）。
- **G-BOUNDARY 输出契约断言**：Autonomy 只出 `AutonomyVerdict` + intention、Planning 只出 `GoalPlanRecord` + `PlanStepSpec[]`、Tool 只出 `ToolResult`（各自静态与运行时断言）；三者无交叉写面。
- 行为差异只在 Flag on 时出现；Flag off 时 `PolicySnapshot.plan_facts` 不存在（`{}` 原状），与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- `app/services/autonomy_policy.py` 保持纯函数 + 纯数据：零仓储导入、零 IO（静态断言）。
- `app/services/decision_pipeline.py` diff 为空（零改动）。
- `_collect_plan_facts` 装配全程只读（打桩断言零写库）。
- 计划触发的执行仍经 `action_engine.run_action_planning(source="autonomy")`，额度与冷却原样生效。
- 既有 `autonomy_policy` / `decision_pipeline` / `autonomy_engine` / `trigger_evaluator` 测试零失败。
- `life_loop` 九步序列与 `autonomous_tick` stage 序列不变（形状快照对照）。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`。
- **零新建自治执行器**：`_produce_autonomy_action` 原样复用；不新增 LLM 决策循环；`llm_gateway` 预算数学不变。
- **增量接线可举证**：四项「零改动」断言（tick 二十步 / evaluate 八步 / 六维权重 / `_SOURCE_PRIORITY`）各有快照对照证据。
- **B9 关闭可举证**：`plan_facts` 七字段各可追溯到具体读取入口；「计划推进时自治不抢同一动作」有端到端用例（含 Flag on / off 对照面）。
- **职责不重叠可举证**：§4.2.2 对照表逐行对应 §6.4 的输出契约断言（B1~B4）。
- **文档一致**：本文件与 architecture §7.3 / §7.8 / §7.9 / §3.2.3 及 tasks.md PLAN-007 Acceptance Criteria 逐条对应，无自相矛盾。
