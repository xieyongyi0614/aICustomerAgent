# PLAN-003 Task Detail — Planning Engine Core

> 上游：[../architecture.md](../architecture.md) §3.3（PlanContextAssembler）、§3.4（PlanningEngine）、§6.3（输入装配流程）、§7.8（Life Loop 挂载）、§8.1 / §8.2（接口）、§9.7 Q6；[../tasks.md](../tasks.md) PLAN-003
> 状态：DONE（已实现，commit e14bac8，2026-09-16）
> 范围红线：**包装既有 `goal_planning`，不新建规划器**；`plan` / `revise` 不直接落库；拒绝路径不抛异常；除 `assemble` 外组件零 IO；不新增 `life_loop` stage；不新增 `llm_gateway` capability 位。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-003 |
| **Task Name** | Planning Engine Core |
| **Priority** | P0 |
| **Dependencies** | PLAN-002 |
| **Phase** | Phase 1 规划地基 |
| **建议提交** | `feat: V2.5.0 规划上下文装配与七道闸引擎` |

## 1.1 Goal

交付规划引擎核心两件套，并挂进既有 `life_loop` 维护步：

1. **`PlanContextAssembler`**（`app/services/planning/context.py`）：六源输入装配（Goal / Context / World State / Memory / Reflection / ToolSurface），**逐源可降级**，两源硬依赖。
2. **`PlanningEngine`**（`app/services/planning/engine.py`）：计划生成与修订，**七道闸短路**（既有五道 + 新增工具可解析 / 工具在面上两道）。

## 1.2 Scope

**包含**

- 新建 `app/services/planning/context.py`：`PlanContextAssembler.assemble(goal, *, run, now)` + `PlanContextProbe` 只读探测。
- 新建 `app/services/planning/engine.py`：`plan` / `revise` / `enqueue` / `run_jobs` / `register_runtime`，包装既有 `goal_planning`。
- 新增两个闸门与两个拒绝理由码：`plan_tool_unresolvable` / `plan_tool_off_surface`。
- `revise` 的版本语义（`version+1` + 旧版置 `superseded` + 保留已完成步骤）。
- `life_loop._step_goal_supply` 与 `agent_runtime` 的 `goal_supply` 阶段内部改走 `PlanningEngine.enqueue` / `run_jobs`（**不改签名、不新增 stage**）。
- 单元 / 集成 / 场景测试。

**不包含（Non-Scope）**

- 工具绑定的**实现**（属 PLAN-004 的 `TaskDecomposer`；本任务只做闸门 5/6 的**校验**）。
- `PlanScheduler` / `PlanExecutorBridge` / `PlanObserver` / `PlanRevisionPolicy`（属 PLAN-005）。
- 判据第四事实源的求值实现（属 PLAN-005）。
- 工具面投影八维裁剪的实现（V2.4.0 既有 `ToolSurfaceResolver`，零改动）。
- `PlanContext` 装配的 LLM 预算裁决（Q6，本任务内只记录）。
- 调试端点（属 PLAN-011）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 断层中的 **B4（规划器看不见可用工具面）** 与 **B3（计划校验只因 `ACTION_TYPES` 对齐）** 的核心：

| 断层 | 本任务的关闭方式 |
|---|---|
| B4 | `PlanContext.tool_surface` 为**硬依赖**——装配不到面，这一轮不规划（宁缺毋滥），LLM 规划输入里就有可用面 |
| B3 | 闸门 5（`ToolRegistry.resolve` 可解析）+ 闸门 6（`tool_id ∈ tool_surface.tool_ids`）短路拒绝 |
| B4 衍生 | 工具面必须按 `RUN_KIND_AUTONOMOUS_TICK` 解析，使「趁用户不在时发消息」类步骤在**规划层结构性不可能** |

同时把「计划引擎挂在哪」定死：挂既有 `life_loop` 维护步，**零新增调度循环**（architecture §7.8）。

---

# 2. Background

## 2.1 当前系统现状

| 版本 | 能力 | 与规划引擎的关系 |
|---|---|---|
| V2.0.0 | Memory 2.0 / Reflection / Life Loop | 提供 `memory2.retriever.retrieve`、`reflection/lifecycle.list_user_active_insights`、`life_loop` 九步 |
| V2.1.0 | Agent Runtime / Goal Stack / Decision Pipeline / Action Engine | 提供 `agent_runtime/profiles.autonomous_tick` 阶段序列（含 `goal_supply` / `goal_advance`） |
| V2.3.0 | World Simulation | 提供 `world_engine.collect_facts` / `build_context` / `build_time_context`、`world_brief.build_world_brief`、`world_simulation_repository.get_active_situation` |
| V2.4.0 | Tool System | 提供 `ToolRegistry` / `ToolSurfaceResolver` / `ToolSelector`、`build_tool_context`、`RUN_KIND_AUTONOMOUS_TICK` 语义 |

**关键事实（已核对真实源码）**

- `app/services/goal_planning.py` 已有 `collect_candidates` / `materialize` / `enqueue_planning(user_id, goal_id, trigger)` / `run_planning_jobs()` / `register_runtime()` / `plan_goal(goal_id, trigger, world_facts=None)`，以及 `JOB_TYPE_PLANNING = "goal_planning"`、`STEP_NAME = "goal_planning"`、`_LLM_RETRY_ATTEMPTS = 2`、`_LLM_RETRY_BACKOFF_SECONDS = 1.0`、五个 `REASON_*` 常量。
- `goal_planning._build_messages(goal, overlay, world_facts, settings)` 的供给**不含 `ToolSurface`**——这正是 B4。
- `app/services/tool/context.py` 与 `app/services/tool/world_context.py`：`build_tool_context(base, settings=..., now=...)` 存在，`WorldContextBuilder` 提供八段装配（`world` / `part_of_day` / `current_block` / `active_events` / `inventory` / `situations` / `scene` / `relationship`）与 `_degrade` 逐段降级；`DEFAULT_RUN_KIND = "foreground_chat"`、`RUN_SOURCES = ("conversation", "autonomy", "event_driven")`。
- `app/services/tool/surface.py`：`ToolSurfaceResolver` / `ToolSelector` / `surface_hash` / `DEFAULT_SURFACE_MAX_TOOLS = 12`；裁剪理由前缀 `tool_status` / `run_profile` / `part_of_day` / `scene` / `relationship_stage` / `world_unavailable` / `world_disabled` / `surface_limit`。
- `app/application/life_loop.py`：`_run_user_cycle` 九步为 `perception` → `state_update` → `goal_check` → `goal_supply` → `goal_advance` → `memory_retrieval` → `reflection_check` → `decision` → `world_experience`；`_step_goal_supply(user_id, now)` 与 `_step_goal_advance(user_id, now)`（async）已存在。
- `app/application/agent_runtime/profiles.py`：`autonomous_tick` 的 `stages` 元组已含 `goal_supply` / `goal_advance`。
- `app/services/life_loop_budget.py`：`BudgetState` / `check_daily_budget` / `is_degraded` / `reset_cache`。
- 迁移链头 0046（零迁移前提）。

## 2.2 为什么需要本任务

架构 §1.1 的一句话诊断是「角色有了目标、有了决策、有了手，但『这件事分几步、每步用哪只手、做不成怎么办』无人负责」。

本任务负责其中**第一半**：**看清有什么**（六源装配）与**把目标拆成合法计划**（七道闸）。没有这一步：

- PLAN-004 的 `TaskDecomposer` 无输入契约（无 `PlanContext`）；
- 闸门 5/6 无处落地（B3 / B4 无法关闭）；
- 规划仍走 `_build_messages(goal, overlay, world_facts, settings)`，LLM 会规划出 `builtin.search.query`（恒 `unavailable`、已从工具面剔除）这类**死步骤**。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 六源装配与逐源降级（两源硬依赖） | `PlanContextAssembler.assemble` |
| R2 | 装配过程零写库、除 `assemble` 外零 IO | 契约纪律 + 静态断言 |
| R3 | 七道闸短路判定与拒绝理由码 | `PlanningEngine.plan` |
| R4 | 闸门 5/6 的判定（工具可解析 / 工具在面上） | `PlanningEngine.plan` |
| R5 | `revise` 的版本语义与修订预算 | `PlanningEngine.revise` |
| R6 | `enqueue` 幂等与 `run_jobs` 委托 | `PlanningEngine.enqueue` / `run_jobs` |
| R7 | 挂进 `life_loop._step_goal_supply` 与 `agent_runtime.goal_supply`（**不改签名、不新增 stage**） | 挂载接线 |
| R8 | 只读探测面（供 debug 与自治事实收集） | `PlanContextProbe` |
| R9 | Q6（装配 LLM 成本）的记录 | 文档 + 压测记录 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 工具绑定的确定性裁决（一能力多工具 tiebreak） | PLAN-004 `TaskDecomposer` |
| N2 | 结构解析（序号连续 / 前向依赖 / 深度封顶）的实现 | 既有 `validate_sub_goals`（PLAN-004 调用） |
| N3 | 判据补全与 `observation_keys` 白名单裁剪 | PLAN-004 / PLAN-005 |
| N4 | 三闸 `PlanValidator`（形状 / 绑定 / 预算）的纯函数实现 | PLAN-004 |
| N5 | 步骤调度 / 执行 / 观测 / 修订 | PLAN-005 |
| N6 | 工具治理链（六闸门 / 五段短路） | PLAN-006（执行期） |
| N7 | 世界事实的写入路径与终态广播 | PLAN-008 |
| N8 | 计划终态记忆与反思证据窗 | PLAN-009 / PLAN-010 |
| N9 | `PlanContext` 装配的预算位新增 | **本任务只记录 Q6，不新增 capability 位** |

## 3.3 职责边界一句话

> **`PlanContextAssembler` 回答「规划这一刻 Agent 能看见什么」；`PlanningEngine` 回答「这个目标能不能变成一份合法计划」。二者都不执行、都不写库（除既有的计划落库经 `goal_repository`）。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/context.py` | **新增** | 六源装配 + 降级登记 + 只读探测 | → `goal_repository` / `world_engine` / `world_brief` / `world_simulation_repository` / `scene_profiles` / `memory2.retriever` / `reflection/lifecycle` / `ToolSurfaceResolver`（全部只读） |
| `app/services/planning/engine.py` | **新增** | **包装** `goal_planning`；七道闸；`revise` 版本语义 | → `goal_planning`（既有）/ `goal_repository`（既有写面）/ `ToolRegistry`（只读） |
| `app/application/life_loop.py` | **最小接线** | `_step_goal_supply` 内部改走 `PlanningEngine.enqueue` / `run_jobs` | 签名与九步序列不变 |
| `app/application/agent_runtime/profiles.py` | 零改动 | `goal_supply` / `goal_advance` 阶段名不变 | — |

**分层纪律**：`app/services/planning/` 不得 import `world_repository`（PLAN-008 红线 G-WORLD），不得直写 Character 域（`character_state` / `personality_state` / `relationship_*`）。

### 4.1.2 Component 划分

```text
app/services/planning/context.py
├── PlanContextAssembler
│     assemble(goal, *, run, now) -> PlanContext | PlanUnavailable
│     ├── _assemble_goal()     硬依赖（缺失 → PlanUnavailable("goal_missing")）
│     ├── _assemble_world()    可降级（world_enabled=False → 空包 + degraded）
│     ├── _assemble_context()  可降级（场景画像 + 用户处境 + 关系）
│     ├── _assemble_memory()   可降级（有界，受两参数约束）
│     ├── _assemble_reflection() 可降级（有界）
│     └── _assemble_tool_surface() 硬依赖（不可得 → PlanUnavailable）
└── PlanContextProbe
      world_available(user_id) / surface_size(user_id, *, run_kind) / degraded_sources(user_id)

app/services/planning/engine.py
├── PlanningEngine
│     plan(goal, ctx, *, trigger) -> PlanOutcome
│     revise(plan, ctx, *, reason) -> PlanOutcome
│     enqueue(user_id, goal_id, trigger, *, ctx) -> bool
│     run_jobs() -> int
│     register_runtime() -> None
└── 七道闸（短路，顺序固定）
      1 attempt_cap  2 subgoal_count_exceeded  3 invalid_sub_goal_shape
      4 capability_unaligned  5 plan_tool_unresolvable  6 plan_tool_off_surface
      7 llm_failed
```

### 4.1.3 数据流一：`PlanContext` 装配

```text
assemble(goal, run, now)
    ├─ 1) Goal（硬依赖）
    │      get_goal → None ⇒ return PlanUnavailable("goal_missing")，不进入 LLM
    ├─ 2) World（可降级）
    │      world_enabled ?
    │        ├ True  → collect_facts + build_context（asyncio.to_thread，与 chat_pipeline 同款）
    │        │          build_world_brief(budget=world_brief_char_budget)
    │        └ False → world = {}，degraded += ["world_disabled"]
    ├─ 3) Context（可降级）
    │      scene_profile_for(world.location_id) → SceneProfile
    │      get_active_situation(user_id)        → UserSituation | None
    ├─ 4) Memory（可降级，有界）
    │      retriever.retrieve(user_id, query=goal.description, top_k=memory_top_k)
    │        · 复用既有打分与拒绝冷却过滤器
    │        · 再受 v25_plan_context_memory_limit 二次裁剪
    ├─ 5) Reflection（可降级，有界）
    │      list_user_active_insights(user_id) → 受 v25_plan_context_insight_limit 截断
    │      reflection.tool_feed.interest_signal(user_id) → 工具效能倾向
    └─ 6) ToolSurface（硬依赖）
           × v24_tool_system_enabled off ⇒ PlanUnavailable("tool_system_disabled")
           × registry 为 None            ⇒ PlanUnavailable("registry_unavailable")
           ✓ ToolSurfaceResolver(registry, settings).resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx)
                · RUN_KIND_AUTONOMOUS_TICK 来自既有 app/application/agent_runtime/models.py
                  （RunKind = Literal["foreground_chat", "autonomous_tick", "event_driven"]）
                · tool_ctx 由 build_tool_context(base, settings, now) 装配（既有）
                · 复用 WorldContextBuilder 的八段装配与逐段降级
    逐段失败 → degraded 清单登记，不抛错、不阻塞
```

### 4.1.4 数据流二：计划生成（七道闸短路）

```text
plan(goal, ctx, *, trigger)
  ① attempt_cap              : 规划尝试次数达 v2_autonomy_planning_max_attempts → reject
  ② subgoal_count_exceeded   : 步骤数 > min(v25_plan_max_steps, v2_autonomy_subgoal_max_count) → reject
  ③ invalid_sub_goal_shape   : validate_sub_goals 抛错（序号 / 前向依赖 / 深度）→ reject
  ④ capability_unaligned     : 能力不在 ACTION_TYPES → reject
  ⑤ plan_tool_unresolvable   : ToolRegistry.resolve(step.tool_id) 失败 → reject   【新增】
  ⑥ plan_tool_off_surface    : step.tool_id ∉ ctx.tool_surface.tool_ids → reject  【新增】
  ⑦ llm_failed               : LLM 调用失败（_LLM_RETRY_ATTEMPTS 后）→ reject
  ── 全过 → GoalPlanRecord(status="validated") + PlanStepSpec[]
  ── 任一不过 → GoalPlanRecord(status="rejected", rejection_reason=<理由码>)（不抛异常）
```

### 4.1.5 数据流三：`revise` 修订语义

```text
revise(plan, ctx, reason)
   ├─ plan.status == "rejected" → 等价于 plan(goal, ctx, trigger=TRIGGER_REPLAN)
   ├─ plan.status == "active"   → 新版本（version+1），旧版本置 "superseded"
   ├─ 已终态步骤：保留 done 的 index 与 depends_on 语义，不重做（幂等复用）
   └─ 修订预算：版本数 ≤ v25_plan_revision_budget（默认 3）
        └─ 达上限 → 计划置 "rejected"（rejection_reason 记原因）
                    → 目标转 failed（failure_reason="plan_exhausted"）
```

## 4.2 Core Model

本任务**不新增模型**（值对象由 PLAN-002 定义）。下为本任务定义 / 消费的关键契约类型。

### 4.2.1 `PlanContext`（消费，PLAN-002 定义）

字段见 PLAN-002 §4.2.1。本任务的关键约束：

| 字段 | 本任务的装配约束 |
|---|---|
| `goal` | 硬依赖；缺失即 `PlanUnavailable("goal_missing")` |
| `tool_surface` | 硬依赖；按 `RUN_KIND_AUTONOMOUS_TICK` 解析 |
| `degraded` | 逐条登记失败源，进 `loop_runs.steps` |
| `budget` | settings 投影：步数 / 深度 / 修订 / 尝试四项上限 |
| `run` | `RunContext` 投影：`run_id` / `run_kind` / `trigger_type` |
| `evidence_refs` | 本任务透传（内容由 PLAN-010 注入） |

### 4.2.2 `PlanOutcome`（本任务定义的返回契约）

| 字段 | 类型 | 说明 |
|---|---|---|
| `plan` | `GoalPlanRecord \| None` | 成功时返回（`status="validated"`）；被拒时为 `None` 或 `rejected` 记录 |
| `status` | str | `"validated"` / `"rejected"` |
| `rejection_reason` | str \| None | 取值即七道闸理由码 |
| `steps` | `list[PlanStepSpec]` | 步骤列表（被拒时为空或部分） |
| `degraded` | `list[str]` | 本次装配的降级源清单 |

### 4.2.3 `PlanUnavailable`（硬依赖失败契约）

| 字段 | 取值 | 触发条件 |
|---|---|---|
| `reason` | `goal_missing` | `get_goal` 返回 `None` |
| `reason` | `tool_system_disabled` | `v24_tool_system_enabled` off |
| `reason` | `registry_unavailable` | `ToolRegistry` 未就绪（`get_tool_registry()` 返回 `None`） |

**语义**：`PlanUnavailable` 是**正常业务结果**（这一轮不规划），不是异常。

### 4.2.4 七道闸与理由码（本任务契约）

| # | 闸门 | 理由码常量 | 值 | 既有 / 新增 |
|---|---|---|---|---|
| 1 | 总闸与尝试次数 | `REASON_ATTEMPT_CAP` | `attempt_cap` | 既有（`goal_planning`） |
| 2 | 步骤数上限 | `REASON_COUNT_EXCEEDED` | `subgoal_count_exceeded` | 既有 |
| 3 | 形状合法 | `REASON_INVALID_SHAPE` | `invalid_sub_goal_shape` | 既有 |
| 4 | 能力对齐 | `REASON_CAPABILITY_UNALIGNED` | `capability_unaligned` | 既有 |
| 5 | **工具可解析** | `REASON_TOOL_UNRESOLVABLE` | `plan_tool_unresolvable` | **新增** |
| 6 | **工具在面上** | `REASON_TOOL_OFF_SURFACE` | `plan_tool_off_surface` | **新增** |
| 7 | LLM 失败 | `REASON_LLM_FAILED` | `llm_failed` | 既有 |

**闸门 5 与闸门 6 的区别（评审要点）**

| 维度 | 闸门 5 | 闸门 6 |
|---|---|---|
| 问题 | 「这个工具存在吗」（声明面） | 「这一刻它能用吗」（运行时面） |
| 依据 | `ToolRegistry.resolve(tool_id)` | `tool_id ∈ ctx.tool_surface.tool_ids` |
| 例 | `world.object.move` 存在 | `builtin.search.query` 恒 `unavailable` 已被面剔除 → 拒 |
| 例 | `channel.feishu.send` 已注册 | `late_night` 时段该工具被面剔除 → 拒 |
| 拒绝后果 | 该步不可装配 | **计划的步数与内容不变**，只是暂不装配该步，等面恢复 |

### 4.2.5 装配参数（消费 PLAN-002 配置）

| 参数 | 用途 |
|---|---|
| `v25_plan_context_enabled` | 六源装配总开关（off → 无装配，`degraded` 字段不存在） |
| `v25_plan_step_binding_enabled` | 闸门 5/6 开关（off → 无闸门 5/6，`SubGoalSpec.tool_id` 不写） |
| `v25_plan_tool_required` | on 时工具面为硬依赖；off 时允许无面规划（退化为 V2.4.0 行为） |
| `v25_plan_max_steps` / `v25_plan_max_depth` | 闸门 2 / 3 |
| `v25_plan_context_memory_limit` / `v25_plan_context_insight_limit` | 装配有界 |
| `v25_plan_llm_profile` | 规划 LLM profile（空 = 沿用 `v2_autonomy_planning_llm_profile`） |
| `v25_plan_context_digest_enabled` | 是否计算 `context_digest` |
| `v25_plan_revision_budget` | `revise` 版本数上限 |

## 4.3 State Machine

### 4.3.1 计划状态迁移（本任务产生的转移，值集由 PLAN-002 / PLAN-001 冻结）

```text
（无计划）
    │ plan(goal, ctx, trigger)  七道闸全过
    ▼
┌────────────┐   plan 被任一闸门拒        ┌────────────┐
│ validated  │ ◄──────────────────────    │  rejected  │
└─────┬──────┘                            └─────┬──────┘
      │ 目标 active（PLAN-005 激活）              │ revise（等价于按 TRIGGER_REPLAN 重生成）
      ▼                                          │
┌────────────┐   revise（version+1）              │
│   active   │───────────────► superseded （旧版）│
└────────────┘                                    │
      │ 达 v25_plan_revision_budget                │
      └────────────────────────────────────────────┘
                  → 计划 rejected + 目标 failed("plan_exhausted")
```

| 状态 | 本任务可否产生 | 触发 |
|---|---|---|
| `draft` | ✅（生成中间态） | `plan` 拆解中 |
| `validated` | ✅ | 七道闸全过 |
| `rejected` | ✅ | 任一闸门拒绝 / 达修订预算 |
| `active` | ❌（属 PLAN-005 激活） | 目标 `active` |
| `superseded` | ✅ | `revise` 产生新版 |

### 4.3.2 `PlanUnavailable` 判定状态机（装配硬依赖）

```text
assemble(goal, ...)
    │
    ├─ get_goal 返回 None ─────────────────────► PlanUnavailable("goal_missing")     → 零 LLM
    │
    ├─ v25_plan_tool_required == on ?
    │     ├─ 否 → 允许无面规划（surface = 空面；退化为 V2.4.0 行为）
    │     └─ 是 → 继续
    │
    ├─ v24_tool_system_enabled == off ─────────► PlanUnavailable("tool_system_disabled") → 零 LLM
    ├─ get_tool_registry() is None ────────────► PlanUnavailable("registry_unavailable") → 零 LLM
    └─ 否则 → 继续，返回 PlanContext
```

### 4.3.3 装配降级状态（逐源，可观测）

| 源 | 可用 | 不可用（降级形态） | `degraded` 标记 |
|---|---|---|---|
| Goal | ✅ | —（硬依赖，缺失即中止） | — |
| World | ✅ | 空包 `{}` | `world_disabled` |
| Context | ✅ | 空包 | `scene_unavailable` / `situation_unavailable` |
| Memory | ✅ | 空列表 | `memory_unavailable` |
| Reflection | ✅ | 空列表 | `reflection_unavailable` |
| ToolSurface | ✅ | —（硬依赖；`v25_plan_tool_required` off 时为空面 + `surface_unavailable`） | `surface_unavailable` |

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 谁决定「此刻做什么」 | `autonomy_policy.evaluate` + `decision_pipeline`（既有） | **不涉及** |
| `plan_facts` 进 `PolicySnapshot` | PLAN-007 | **不涉及** |
| 计划推进意图经 `goal_compile` 候选面 | PLAN-007 | **不涉及** |
| `RUN_KIND_AUTONOMOUS_TICK` 的选择 | 本任务 | **决策点**：计划执行发生在后台节拍，因此工具面按自治面解析 |

**为什么不涉及自治接线**：本任务只做「装配 + 生成」；计划推进「怎么被自治看到」属 PLAN-007 的增量接线（`PolicySnapshot` 第五段 + 既有 `goal_compile` 候选面）。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `ToolRegistry.resolve(tool_id)` | 闸门 5 依据 | **只读消费** |
| `ToolSurfaceResolver.resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx)` | 闸门 6 依据 + `PlanContext.tool_surface` | **只读消费** |
| `build_tool_context(base, settings, now)` | 装配 `ToolContext`（既有八段与逐段降级） | **复用** |
| `ToolSelector` / `ToolExecutor` / 六闸门 / 五段短路 | 执行期 | **本任务不涉及**（PLAN-006） |
| 工具面裁剪八维 | V2.4.0 既有 | **零改动**；本任务只消费投影结果 |

**为什么按自治面**：用 `RUN_KIND_AUTONOMOUS_TICK` 解析意味着 `channel.*` 类「必须用户在线」的工具被自然剔除——**规划层不可能规划出「趁用户不在时发消息」的步骤**，这是权限边界的结构化解法，而非运行时补丁（architecture §6.3 裁决理由）。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 世界事实进 `PlanContext`（`world` / `world_brief` / `world_context` / `situations` / `scene`） | **只读预读** | **实现装配**（读取入口见 §4.1.3） |
| 计划写世界 | PLAN-008 | **不涉及**：本任务禁止 import `world_repository` |
| 计划终态广播 | PLAN-008 | **不涉及** |

**为什么不涉及写入**：计划对世界的写入必须经 `deferred_world_op` → outbox → `world_engine`（architecture §7.4）。本任务是**只读装配**，`assemble` 不得调用 `world_engine.build_context` 内部的 `run_turn_update` 等写路径（§10.1 零写库断言）。

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `memory2.retriever.retrieve` | `PlanContext.memories` 来源 | **只读消费**（有界：`memory_top_k` + `v25_plan_context_memory_limit`） |
| `memory_policy` R1~R8 | 记忆写入政策 | **不涉及**（本任务零写入 `memories`） |
| 计划终态记忆候选 | PLAN-009 | **不涉及** |

**为什么不涉及**：本任务只**读**记忆进规划上下文；计划结果进记忆属 PLAN-009，且必须经 `memory_policy.apply_policy`（零豁免）。

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `reflection/lifecycle.list_user_active_insights` | `PlanContext.insights` 来源 | **只读消费**（有界：`v25_plan_context_insight_limit`） |
| `reflection/tool_feed.interest_signal` | 工具效能倾向进 prompt | **只读消费** |
| `EVIDENCE_CHANNEL_PLAN` / 计划证据窗 | PLAN-010 | **不涉及** |
| `PlanningRevisionListener` | PLAN-010 | **不涉及**（本任务只保证 `enqueue(trigger=TRIGGER_REPLAN)` 可用） |

**为什么不涉及**：本任务只**读** Insight；证据聚合与回环监听属 PLAN-010。

## 5.6 与 Life Loop / Agent Runtime

| 关注点 | 既有形态 | 本任务接线 |
|---|---|---|
| `life_loop._step_goal_supply(user_id, now)` | 调 `goal_planning.collect_candidates` / `materialize` / `enqueue_planning` | **不改签名**；内部改走 `PlanningEngine.enqueue` / `run_jobs` |
| `life_loop._run_user_cycle` 九步序列 | `perception → state_update → goal_check → goal_supply → goal_advance → memory_retrieval → reflection_check → decision → world_experience` | **序列不变**（本任务是 `goal_supply` 步的内部增强） |
| `agent_runtime/profiles.py` 的 `autonomous_tick` stages | 含 `goal_supply` / `goal_advance` | **阶段序列不变** |
| `background_jobs` | `JOB_TYPE_PLANNING = "goal_planning"` | **复用**；重规划走同一 `job_type`，用 `idempotency_key` 区分 |
| `loop_runs.steps` | `mark_step` | 计划阶段以**子步骤**记入（`plan_assemble` 等），受既有 `budget_state` 约束 |
| `llm_gateway` | 能力位（`reflection` / `judge` / `proactive` 等） | **不新增 capability 位**；规划沿用 `v2_autonomy_planning_llm_profile` / `v25_plan_llm_profile` |
| `life_loop_budget` | `check_daily_budget` / `is_degraded` | **复用**（`plan` 是 LLM 调用，受双重约束） |

**预算纪律**：计划生成是 LLM 调用，必须受既有 `llm_gateway` 与 `life_loop_budget` 双重约束。`v25_plan_revision_budget` 只管「计划版本数」，**不绕过**日额度与周期预算。

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| Action Engine 六闸门 / 五段短路 | 不涉及 | 执行桥属 PLAN-005 / 治理链属 PLAN-006 |
| outbox / `event_bridge` | 不涉及 | 属 PLAN-008 |
| `decision_records` 推进审计 | 不涉及（本任务不产生 `PlanAdvance`） | 属 PLAN-005 / PLAN-011 |
| `memories` 写入 | 不涉及 | 属 PLAN-009 |
| `reflection/evidence.py` | 不涉及 | 属 PLAN-010 |
| `PolicySnapshot` | 不涉及 | 属 PLAN-007 |

---

# 6. API / Interface Design

## 6.1 `PlanningEngine` 接口

```text
interface PlanningEngine:
    plan(goal: GoalRecord, ctx: PlanContext, *, trigger: str) -> PlanOutcome
    revise(plan: GoalPlanRecord, ctx: PlanContext, *, reason: str) -> PlanOutcome
    enqueue(user_id: str, goal_id: str, trigger: str, *, ctx: PlanContext | None) -> bool
    run_jobs() -> int
    register_runtime() -> None

interface PlanOutcome:
    plan: GoalPlanRecord | None
    status: str                      # "validated" / "rejected"
    rejection_reason: str | None     # 取值即 §4.2.4 七道闸理由码
    steps: list[PlanStepSpec]
    degraded: list[str]
```

**参数说明**

| 参数 | 说明 |
|---|---|
| `trigger` | ∈ 既有 `PLANNING_TRIGGERS`（`goal_created` / `goal_blocked` / `goal_replan`），无新值 |
| `reason` | ∈ 四个重规划理由码（`step_attempt_exhausted` / `tool_persistently_unavailable` / `criteria_undecidable` / `insight_driven`） |
| `ctx` | `enqueue` 的 `ctx` 可为 `None`（入队时未装配；实际装配在 job 执行期） |

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | `plan` / `revise` **不直接落库**——落库经 `goal_repository.create_plan` / `set_plan_status`，保证单一写面 | 静态断言：`engine.py` 零 `session` / 零 `update()` |
| D2 | `plan` 必须 **async**（含 LLM 调用），受 `llm_gateway` 与 `life_loop_budget` 双重约束 | 签名断言 + 预算用例 |
| D3 | `enqueue` 必须**幂等**（同 `idempotency_key` 重复调用不得产生第二个 job） | 幂等用例（§9.2 I3） |
| D4 | **拒绝路径不得抛异常**——拒绝是正常业务结果（`status="rejected"`），异常仅用于实现缺陷 | 负例用例：七道闸各一例，断言无异常抛出 |
| D5 | 本任务**不新增工具选择逻辑** | 静态断言：`engine.py` 零 `ToolSelector` 选择调用（只用 `ToolRegistry.resolve` 做可解析判定） |

## 6.2 `PlanContextAssembler` 接口

```text
interface PlanContextAssembler:
    assemble(goal: GoalRecord, *, run: RunContext | None, now: datetime | None)
        -> PlanContext | PlanUnavailable

interface PlanContextProbe:                 # 只读探测，供 debug 与自治事实收集
    world_available(user_id: str) -> bool
    surface_size(user_id: str, *, run_kind: str) -> int
    degraded_sources(user_id: str) -> list[str]
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D6 | 除 `assemble` 外，组件内**零 IO** | 静态断言（与 `planner.GateSnapshot` / `ToolContext` 同一工程标准） |
| D7 | `assemble` **只读、不写任何表**（`world_engine.build_context` 内部的 `run_turn_update` 等写路径**不得**被调用） | 打桩断言（§9.2 I4） |
| D8 | 任一源失败降级为空包并登记 `degraded`，**不抛错、不阻塞** | 逐源两态用例 |
| D9 | `goal` 与 `tool_surface` 是硬依赖：缺任一 → 返回 `PlanUnavailable`，调用方跳过本轮规划 | 零 LLM 断言（§9.1 U7） |
| D10 | 工具面一律按 `RUN_KIND_AUTONOMOUS_TICK` 解析 | 静态 + 运行时断言 |

## 6.3 内部辅助接口（仅本任务内可调用）

```text
# context.py
_assemble_goal(goal) -> GoalRecord                      # 硬依赖
_assemble_world(user_id, now) -> tuple[dict, WorldBrief | None, WorldContext | None, list[str]]
_assemble_context(user_id, world) -> tuple[SceneProfile | None, UserSituation | None, dict, list[str]]
_assemble_memory(user_id, goal, settings) -> tuple[list[MemoryRef], list[str]]
_assemble_reflection(user_id, settings) -> tuple[list[InsightSummary], list[str]]
_assemble_tool_surface(user_id, settings, now) -> ToolSurface | PlanUnavailable

# engine.py
_evaluate_gates(proposal, ctx, settings) -> str | None   # 返回理由码或 None
_build_plan(goal, proposal, ctx, trigger) -> GoalPlanRecord
```

> 私有函数命名以 `_` 前缀；对外只暴露 §6.1 / §6.2 的公开面（PLAN-011 做契约冻结与对照）。

## 6.4 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| `ValueError`（`validate_sub_goals` / `validate_criteria`） | 形状闸 / 判据白名单 | **转 `rejected` + `invalid_sub_goal_shape`**，不抛给调用方（D4） |
| LLM 调用异常 | `llm_gateway` | `_LLM_RETRY_ATTEMPTS`(2) 后转 `rejected` + `llm_failed` |
| 装配源异常 | 任一可降级源 | 捕获 → 空包 + `degraded`，不抛 |
| 装配硬依赖缺失 | Goal / ToolSurface | 返回 `PlanUnavailable`（**不是异常**） |
| `IllegalGoalTransition` | `goal_repository`（达修订预算转 `failed` 时） | 不吞；向上暴露（PLAN-005 记审计） |

## 6.5 挂载接口（既有签名零改动）

```text
life_loop._step_goal_supply(user_id: str, now: datetime) -> dict    # 签名不变
    # 内部：goal_planning.collect_candidates / materialize（既有，不变）
    #       → PlanningEngine.enqueue(user_id, goal_id, trigger, ctx=None)
    #       → PlanningEngine.run_jobs()
    # 返回 dict 的字段集与既有实现一致

agent_runtime/profiles.py::autonomous_tick.stages                    # 阶段元组不变
    # 已含 "goal_supply" / "goal_advance"；本任务不新增 stage
```

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 计划本体落既有 `goal_plans`（`sub_goals` JSON 已承载步骤） |
| 新列 | 无 | `PlanContext` 是内存值对象，落 `loop_runs.steps`（既有 JSON）与 `decision_records.input_snapshot`（既有 JSON）；`degraded` 随 `PlanContext` 进 JSON |
| 新索引 | 无 | 既有 `uq_goal_plans_goal_version` / `idx_goal_plans_goal_status` 覆盖计划查询 |
| 改 CHECK | 无 | `ck_goal_plans_status` 五值不变（`validated` / `rejected` / `superseded` 均既有） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面（全部为既有）**

| 数据 | 落点 | 写入入口 |
|---|---|---|
| 计划本体 + 步骤 | `goal_plans` | `goal_repository.create_plan` / `update_plan_progress` |
| 计划状态 | `goal_plans` | `goal_repository.set_plan_status` |
| 计划拒绝理由 | `goal_plans` | `goal_repository.set_plan_rejection` |
| 目标终态（达修订预算） | `character_goals` | `goal_repository.fail_goal`（`failure_reason="plan_exhausted"`） |
| 规划 job | `background_jobs` | `background_job_repository.enqueue_job`（`job_type='goal_planning'`，既有常量） |
| 运行态子步骤 | `loop_runs` | `loop_run_repository.mark_step` |

> **`assemble` 的零写库是本任务的硬断言**：装配只读六源，不得触发任何表写入（含 `world_engine.build_context` 内部写路径）。若实现期发现必须加列来存 `PlanContext`，说明 architecture §3.1 裁决被违背，须回退重审。

---

# 8. Implementation Plan

## Step 1 — 装配器骨架与硬依赖（`app/services/planning/` 包 + `context.py`）

1. 建立 `app/services/planning/__init__.py`（只导出公开面）。
2. 实现 `_assemble_goal`：`goal_repository.get_goal` → `None` 即返回 `PlanUnavailable("goal_missing")`（**在调用任何 LLM 之前短路**）。
3. 实现 `_assemble_tool_surface`：总闸 off → `tool_system_disabled`；`get_tool_registry()` 为 `None` → `registry_unavailable`；否则 `build_tool_context` + `ToolSurfaceResolver.resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx)`。
4. `v25_plan_tool_required` off 时退化：返回空面 + `degraded += ["surface_unavailable"]`（不再硬依赖）。
5. 单测：三个 `PlanUnavailable` 分支 + 零 LLM 调用打桩断言。

## Step 2 — 四个可降级源

1. `_assemble_world`：`world_enabled` 判定 → `collect_facts` + `build_context`（`asyncio.to_thread`）+ `build_world_brief(budget=world_brief_char_budget)`；`world_disabled` 时返回空包并登记。
2. `_assemble_context`：`scene_profile_for` + `get_active_situation`；失败分别登记 `scene_unavailable` / `situation_unavailable`。
3. `_assemble_memory`：`retriever.retrieve(user_id, query=goal.description, top_k=...)` → 再受 `v25_plan_context_memory_limit` 二次裁剪。
4. `_assemble_reflection`：`list_user_active_insights` → 受 `v25_plan_context_insight_limit` 截断；`tool_feed.interest_signal` 并入。
5. `assemble` 汇总：组装 `PlanContext`（含 `budget` / `run` / `degraded` / `evidence_refs`）；`v25_plan_context_digest_enabled` on 时计算 `context_digest`。
6. 单测：六源各自的「可用 / 不可用」两态；`degraded` 清单可读。

## Step 3 — 引擎骨架与既有三闸复用

1. `app/services/planning/engine.py`：包装 `goal_planning.plan_goal`，保持其 `PlanningProposal` 契约与 `_LLM_RETRY_ATTEMPTS` 重试语义（**不重复实现 LLM 调用**）。
2. 接入既有四闸（`attempt_cap` / `subgoal_count_exceeded` / `invalid_sub_goal_shape` / `capability_unaligned`）与 `llm_failed`。
3. 契约纪律落地：`plan` / `revise` async、不落库、拒绝不抛异常。
4. 单测：既有五闸负例逐条命中。

## Step 4 — 新增闸门 5 / 6

1. 定义两个理由码常量（`plan_tool_unresolvable` / `plan_tool_off_surface`），追加在既有 `REASON_*` 范式之后。
2. 闸门 5：对每个步骤的 `tool_id`（非 `None` 时）调 `ToolRegistry.resolve`；任一不可解析即拒。
3. 闸门 6：对每个步骤的 `tool_id` 校验 ∈ `ctx.tool_surface.tool_ids`；任一不在面上即拒。
4. **闸门 5/6 分别可独立关闭**（受 `v25_plan_step_binding_enabled` 门控）并单独验证。
5. 单测：闸门 5 负例（不存在的 `tool_id`）、闸门 6 负例（`builtin.search.query` / `late_night` 下的 `channel.feishu.send`）；**「闸门 5 过、闸门 6 拒」单列用例**。

## Step 5 — `revise` 版本语义

1. `rejected` → 等价于按 `TRIGGER_REPLAN` 重新生成。
2. `active` → 新版本 `version+1`，旧版 `set_plan_status("superseded")`。
3. 已终态（`done`）步骤保留 `index` 与 `depends_on` 语义**不重做**。
4. 修订预算：`count_plans(goal_id) ≥ v25_plan_revision_budget` → 计划 `rejected` + `fail_goal(failure_reason="plan_exhausted")`。
5. 单测：`version+1` / `superseded` / 保留步 / 达上限终止四条用例。

## Step 6 — 挂载 `life_loop` 与 `agent_runtime`

1. `life_loop._step_goal_supply` 内部改走 `PlanningEngine.enqueue` / `run_jobs`；**签名与返回 dict 字段集不变**。
2. `agent_runtime/profiles.py` 零改动（阶段序列已含 `goal_supply`）。
3. 计划阶段以子步骤记入 `loop_runs.steps`（`plan_assemble` 等），受既有 `budget_state` 约束。
4. `enqueue` 幂等：`job_type` 仍为 `goal_planning`，用 `idempotency_key` 区分（含 trigger）。
5. 回归：九步序列与 `autonomous_tick` 阶段序列的形状快照对照零差异。

## Step 7 — Q6 记录与预算回归

1. 记录 Q6：六源装配中 Memory 检索可能触发嵌入调用（`memory2.embeddings`），与规划 LLM 叠加对 `v2_life_loop_cycle_llm_budget` 的压力；**本任务不新增 capability 位**，压测后决定。
2. `v2_life_loop_cycle_llm_budget` 数学回归（无新增 capability 位 ⇒ 数学不变）。
3. Flag off 全量既有测试零修改通过 + prompt 逐字节对照。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 六源各有「可用 / 不可用」两态 | 六源 × 2 = 12 例；降级态返回空包且 `degraded` 逐条登记 |
| U2 | `world_enabled=False` | `world` 为空包且 `degraded` 含 `world_disabled` |
| U3 | `degraded` 清单可读 | 清单元素为稳定字符串；进 `loop_runs.steps` 子步骤 |
| U4 | Memory 有界 | 检索条数 ≤ min(`memory_top_k`, `v25_plan_context_memory_limit`) |
| U5 | Reflection 有界 | Insight 条数 ≤ `v25_plan_context_insight_limit` |
| U6 | 工具面按 `RUN_KIND_AUTONOMOUS_TICK` 解析 | 断言 resolve 的 `run_kind` 参数为该值；`channel.*` 在 `late_night` 下被剔除 |
| U7 | **零 LLM 断言** | `goal` 缺失 → `PlanUnavailable("goal_missing")` 且 LLM 调用次数 = 0（打桩）；`tool_surface` 不可得同理两分支 |
| U8 | 七道闸各有负例 | 理由码与 §4.2.4 表逐条一致；**拒绝路径零异常抛出**（D4） |
| U9 | 闸门 5 独立关闭 / 闸门 6 独立关闭 | 两个开关各自生效；「闸门 5 过、闸门 6 拒」单列用例通过，且**计划步数与内容不变** |
| U10 | `revise` 四条语义 | `version+1` / 旧版 `superseded` / 保留 `done` 步 / 达预算终止 |
| U11 | `context_digest` 可复现 | 同 `PlanContext` 输入同输出（`v25_plan_context_digest_enabled` on 时） |
| U12 | `v25_plan_tool_required` off | 允许无面规划，退化为 V2.4.0 行为 |
| U13 | 参数边界 | `v25_plan_max_steps` / `v25_plan_max_depth` / `v25_plan_revision_budget` 边界各一例 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | `PlanContext` 字段来源可追溯 | 每个非空字段可指向其读取入口（打桩记录调用） |
| I2 | 装配**零写库** | 对全部写入口打桩（含 `world_engine.build_context` 内部 `run_turn_update` 等写路径），断言调用次数 = 0 |
| I3 | `enqueue` 幂等 | 同 `idempotency_key` 重复调用不产生第二个 job；`job_type` 仍为既有 `goal_planning` |
| I4 | `plan` 不落库 | 静态断言 `engine.py` 零 `session` / 零 `update()`；落库只经 `goal_repository` 四个计划函数 |
| I5 | 预算双重约束 | `plan` 走 `llm_gateway` + `life_loop_budget`；`life_loop_budget` 降级时规划被跳过（不报错） |
| I6 | 目标终态请求合法 | 达修订预算时 `fail_goal` 成功且 `failure_reason="plan_exhausted"`；非法迁移不出现 |
| I7 | `life_loop` 九步序列不变 | 形状快照对照零差异 |
| I8 | `autonomous_tick` stage 序列不变 | 形状快照对照零差异；无新增 stage |
| I9 | `v2_life_loop_cycle_llm_budget` 数学未变 | 无新增 capability 位（快照对照） |
| I10 | 计划面九函数零改动 | 签名快照差异为空 |
| I11 | **Flag off 时走原路径** | `world_facts` 直入、无 `PlanContext`；prompt 与 V2.4.0 逐字节一致；行为快照零差异 |
| I12 | 零迁移断言 | 迁移链头 `0046`；`ck_goal_plans_status` 五值未变 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | 单目标规划（Flag on） | 目标 `active` → `life_loop._step_goal_supply` → `PlanningEngine.enqueue` → `run_jobs` | 产出 `GoalPlanRecord(status=validated)`，每步有 `tool_id`；落 `goal_plans` |
| S2 | **「帮我规划一次旅行」**（多步） | 目标成熟 → 六源装配（world 含天气时段、situations 含出行压力、memories 含偏好、insights 含「提前一晚提醒」）→ 七道闸 → 拆解 → 落 `goal_plans` | 六源非空可追溯；计划步骤数与工具绑定合理；`degraded` 为空或仅含预期项 |
| S3 | 工具面剔除场景 | `late_night` 时段 + 计划含 `channel.feishu.send` | 闸门 5 过、闸门 6 拒 → 计划 `rejected`（或该步不装配）；**不产生死步骤** |
| S4 | 恒 `unavailable` 工具 | 计划含 `builtin.search.query` | 闸门 6 拒（该工具已在 `TOOL_UNAVAILABLE_TOOL_IDS` 被面剔除） |
| S5 | 修订链 | 计划失败 → `PlanRevisionPolicy` 请求 `revise` | `version+1`；旧版 `superseded`；`done` 步保留；版本链可读 |
| S6 | 修订预算耗尽 | 连续修订达 `v25_plan_revision_budget` | 计划 `rejected`；目标 `failed` 且 `failure_reason="plan_exhausted"` |
| S7 | 世界关闭 | `world_enabled=False` → 规划 | world 空包 + `degraded` 含 `world_disabled`；规划仍能产出计划（若 `v25_plan_tool_required` 满足） |
| S8 | Flag 全 off | 触发规划 | 走 `goal_planning` 原路径；prompt 与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 六源各有「可用 / 不可用」两态用例；`degraded` 清单可读并以子步骤记入 `loop_runs.steps`。
- `world_enabled=False` 时 world 为空包且 `degraded` 含 `world_disabled`。
- **零 LLM 断言**：`goal` 缺失或 `tool_surface` 不可得时返回 `PlanUnavailable` 且零 LLM 调用（打桩断言）。
- 装配过程**零写库**（含「不得调用 `world_engine.build_context` 内部写路径」的断言）；除 `assemble` 外组件零 IO（静态断言）。
- 七道闸各有负例，拒绝理由码与 §4.2.4 表逐条一致；闸门 5 与闸门 6 可分别独立关闭并单独验证；「闸门 5 过、闸门 6 拒」单列用例通过。
- `enqueue` 幂等：同 `idempotency_key` 重复调用不产生第二个 job；`job_type` 仍为既有 `goal_planning`。
- `revise` 产生 `version+1` 且旧版置 `superseded`；达修订预算上限后计划置 `rejected` 且目标转 `failed("plan_exhausted")`；拒绝路径零异常抛出。
- `life_loop` 九步序列与 `autonomous_tick` stage 序列不变（形状快照对照）；`v2_life_loop_cycle_llm_budget` 数学未变（无新增 capability 位）。
- Flag off 时走 `goal_planning` 原路径（`world_facts` 直入、无 `PlanContext`），prompt 与 V2.4.0 逐字节一致，行为快照对照零差异。

## 10.2 Integration Acceptance

- `PlanContext` 六源全部经**既有入口**读取，且每源读取调用可打桩追溯（无自造读取路径）。
- `ToolSurfaceResolver.resolve` 的 `run_kind` 恒为 `RUN_KIND_AUTONOMOUS_TICK`（静态 + 运行时断言）。
- `plan` / `revise` 不直接落库（静态断言）；落库只经 `goal_repository.create_plan` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress`。
- `life_loop._step_goal_supply` 签名与返回 dict 字段集不变；`agent_runtime/profiles.py` 零改动。
- `life_loop_budget` 与 `llm_gateway` 双重约束生效；降级时规划优雅跳过（不抛错、不阻塞 tick）。
- 既有 `goal_planning` / `goal_observation` / `goal_execution` 测试零失败。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`。
- **零新增基础设施**：不新增 `life_loop` stage、不新增 `background_jobs.job_type`、不新增调度循环 / Worker、不新增 `llm_gateway` capability 位。
- **纯只读装配纪律**：`context.py` 只读六源，零写库；`PlanContextProbe` 三个方法零 IO。
- **Q6 记录留痕**：`PlanContext` 装配的嵌入调用与规划 LLM 叠加对 `v2_life_loop_cycle_llm_budget=1` 的压力在本任务内记录，压测结论与「是否新增预算位」的裁决一并留痕；若最终新增 capability 位，须同步 architecture §7.8 预算数学说明（本任务范围内不新增）。
- **文档一致**：本文件与 architecture §3.3 / §3.4 / §6.3 / §7.8 / §8.1 / §8.2 / §9.7 Q6 及 tasks.md PLAN-003 Acceptance Criteria 逐条对应，无自相矛盾。

---

# 11. 实现留痕（PLAN-003 落地记录）

## 11.1 交付清单

| 文件 | 性质 | 作用 |
|---|---|---|
| `apps/backend/app/services/planning/context.py` | 新增 | `PlanContextAssembler`（六源装配、逐源降级、两源硬依赖）、`PlanContextProbe`（只读探测）、`PlanUnavailable`、`context_digest`、`plan_budget` |
| `apps/backend/app/services/planning/engine.py` | 新增 | `PlanningEngine`（`plan` / `revise` / `enqueue` / `run_jobs` / `register_runtime`）、七道闸、`PlanOutcome`、`get_planning_engine` |
| `apps/backend/app/services/goal_planning.py` | 增补 | `propose_plan(goal, world_facts, settings)`：规划 LLM 面的**增量复用入口**（同 prompt、同 `_LLM_RETRY_ATTEMPTS`），使 LLM / prompt 面仍只有一处实现；`plan_goal` 原三步编排未改 |
| `apps/backend/app/application/life_loop.py` | 最小接线 | `_step_goal_supply` 内部新增 `_route_planning_jobs`（Flag 门控）；签名与返回 dict 字段集不变 |
| `apps/backend/app/services/planning/__init__.py` | 文档 | 公开面登记（保持零急切实导入，避免包级导入拉起仓储 / LLM / 世界链路） |
| `apps/backend/tests/v25/test_plan003_context.py` | 新增 | U1 ~ U7、U11、U12、I1、I2（27 例） |
| `apps/backend/tests/v25/test_plan003_engine.py` | 新增 | U8 ~ U10、U13、I3 ~ I6（35 例） |
| `apps/backend/tests/v25/test_plan003_mount.py` | 新增 | I7 ~ I12 与 S1 / S3 / S4 / S7（18 例） |

## 11.2 契约演进留痕（PLAN-001 已预告的越界评审点）

| # | 演进 | 精确范围 | 依据 |
|---|---|---|---|
| 1 | `goal_repository` 调用白名单 **12 → 16** | 只加计划面四函数（`create_plan` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress`） | Task Detail §7 写入面表：计划引擎必须经既有计划面落库；`PLANNING_WRITE_INTERFACES`（Goal 状态写面 5 个）不变 |
| 2 | 角色资产导入禁令的**唯一窄例外** | 只放行 `app.character.asuna.scene_profiles`（逐模块枚举，不得扩成前缀） | Task Detail §4.1.3 要求 `PlanContext.scene` 取 `scene_profile_for`；PLAN-001 禁令的语义是「优先级资产」 |
| 3 | `test_plan001_scope_markers.py` 标记翻转 | `context.py` / `engine.py` 由「仍不得预埋」→「已落地」；`decompose.py` 与 PLAN-005 五模块维持「不得预埋」 | 范围标记的既定纪律（标记翻转本身即越界评审证据） |
| 4 | `test_plan001_deferred.py` 清单更新 | `context` / `engine` 移出「今日不存在」清单，白名单断言去 `skip` | 同上 |

以上改动**仅限相应测试文件 + `goal_contract` 模块文档 §9**；PLAN-001 的其余冻结快照（Goal 状态机 / 迁移表 / 失败理由词表 / 五写面签名 / 禁止事项清单）零变更。

## 11.3 与 Task Detail 的偏差（均已在代码与测试留痕）

| # | Task Detail 表述 | 实现 | 理由 |
|---|---|---|---|
| 1 | §4.1.4 闸门顺序「2 步数 → 3 形状」 | 实现序为「形状 → 步数 → 能力」 | 步数必须在 `validate_sub_goals` 解析出 specs 之后才可数；与既有 AUT-002 实现同序，闸门集合与理由码不变 |
| 2 | §8.2 / §10.1「`degraded` 以子步骤记入 `loop_runs.steps`」与 §7「`assemble` 零写库」冲突 | 子步骤（`plan_assemble` / `plan_generate` / `plan_revise`）由**引擎**在 `ctx.run["run_id"]` 存在时写；`assemble` 保持严格只读 | 零写库是本任务的硬断言，冲突时以零写库为准 |
| 3 | §6.2 D6「除 `assemble` 外组件零 IO」 | Probe 三方法读 `assemble` 写下的**内存快照**（零 IO），并以静态 + 运行期断言固定 | `world_available(user_id)` 等签名（architecture §8.2）要求按 user 查询；内存投影是唯一同时满足「签名不变」与「零 IO」的形态 |
| 4 | §4.2.1「`degraded` 进 `PlanContext`」 | 已进（`PlanContext.degraded` + `PlanContextProbe.degraded_sources` + `loop_runs.steps` 子步骤） | 无偏差，此处登记读面 |
| 5 | §6.3 `_assemble_world(user_id, now)` | 去掉未使用的 `now` 形参（`_gather_sources(goal, settings)` 同） | 世界源的既有入口不接时刻参数（时刻由 `TimeProvider` 从世界时钟取）；`now` 仅在工具面装配使用 |
| 6 | §6.3 `_assemble_context(user_id, world)` 第 2 返回值 `UserSituation \| None` | 返回 `list[UserSituation]`；第 2 参数为**世界事实包** | `PlanContext.situations` 是列表，且 `get_active_situation` 真实签名要求 dimension（故逐维装配）；场景画像按 `world["location"]` 取地点 id |
| 7 | §3.4 注释「`plan_goal` 包装」+ §9.3 S1 期望 `status=validated` | `plan` / `revise` 复用 `goal_planning.propose_plan`（LLM 面）+ 七道闸 + `create_plan(validated)`；`run_jobs` 按 §3.4 **委托** `run_planning_jobs`（保持「处理 running 载荷并置 `active`」的既有语义） | 若让挂载的 `run_jobs` 走引擎路径，计划将停在 `validated` 而**永不被激活**（激活属 PLAN-005），既有 `goal_advance` 链路立即回退——不可接受。故 S1 的 `validated` 由 `PlanningEngine.plan` 交付（引擎用例），挂载点交付「步内把规划处理完」 |
| 8 | §4.1.3「`world_engine.build_context`」与 §7「装配零写库」 | 用 `world_engine.get_world` 前置判定，**不建档**；`build_context` 内部 `ensure_world` 的建档 / 家庭默认物播种是其既有前置，测试以「世界预播种 + 全表行数前后一致 + 世界写面零调用」三重断言覆盖 | 见 `context.py::_assemble_world` 文档；`assemble` 自身不触发任何写路径 |

实现形态说明：`propose_plan` 是 `goal_planning` 的**增量**入口（`plan_goal` 原编排未改，prompt 逐字节不变），因为 `app/services/planning/` 零 prompt / LLM 面由 PLAN-001 静态扫描强制——引擎取提案只能在 `goal_planning` 内开口。

## 11.4 Q6 记录（Step 7 交付项）

**问题**：六源装配中 Memory 检索可能触发嵌入调用（`memory2.embeddings.embed_query`），与规划 LLM 叠加对 `v2_life_loop_cycle_llm_budget=1` 的压力。

**本任务的核对事实**：

| 观测点 | 事实 |
|---|---|
| 嵌入调用条件 | `memory2.retriever.retrieve` 仅在 `v2_memory_vector_enabled` on **且**查询文本非空时调 `embed_query`；否则走结构化打分（零网络） |
| 装配侧 LLM 调用 | `assemble` **零 LLM**（`PlanContextAssembler` 不触达 `llm_gateway` / `get_llm` / prompt 面；由 `test_plan003_context.py::TestHardDependencies` 三处打桩断言） |
| 规划 LLM | 规划是本模块唯一的 LLM 面（`plan` / `revise`），受 `life_loop_budget.is_degraded()` 前置闸；日额度熔断时优雅跳过（`status="skipped"`，不落库、不消耗版本号） |
| 计划阶段是否记入 `llm_capable` | 否：`planning` 不进 `autonomous_tick` 的阶段序列，`llm_capable` 仍只有 `decision`（`v2_life_loop_cycle_llm_budget` 数学不变） |

**裁决（本任务内）**：**不新增 `llm_gateway` capability 位，不加 `v2_life_loop_cycle_llm_budget` 预算位**。理由：

1. 装配侧的嵌入调用是**既有** `memory2.retriever` 行为（前台对话同样发生），本任务未新增调用点，也未把它升级为周期步骤（周期步骤数不变 ⇒ 预算数学不变）。
2. 规划 LLM 已受「日额度熔断 + `v25_plan_revision_budget`（版本数）+ 既有 `enqueue` 幂等」三重约束，无新增绕过路径。
3. 若后续压测显示规划 LLM 与嵌入叠加确实挤占周期预算，应在 PLAN-011 / PLAN-012 增加**独立预算位**并同步 architecture §7.8 的预算数学说明（本任务范围内不做）。

**回归覆盖**：`test_plan003_mount.py::TestShapeSnapshots` 断言 `autonomous_tick.stages` / `llm_capable` / `_CAPABILITY_DEFAULTS` 三处快照零差异。

## 11.5 自检结果

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/v25 -q` | 315 passed / 4 skipped（新增 80 例） |
| `python -m pytest tests -q -k "goal or life_loop or autonomy"` | 449 passed（1 例 `test_aut005_goal_evaluation::test_clean_slice_passes_all` 为**改动前既有失败**，已在干净工作区复核） |
| `python -m pytest -m "(unit or api) and not slow" -q` | 1424 passed |
| `python -m pytest tests/unit/test_prompt_golden.py -q` | 9 passed（prompt 逐字节未变） |
| `python -m pylint app/services/planning` | 9.71/10（余项：11× `broad-exception-caught` = D8 要求的逐源降级捕获；1× `too-few-public-methods` = §6.2 冻结的「装配器单一公开入口」结构后果） |
| `python -m compileall <新增/修改的生产文件>` | exit 0 |
