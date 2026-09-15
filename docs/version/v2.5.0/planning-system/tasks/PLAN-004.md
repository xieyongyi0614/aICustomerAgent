# PLAN-004 Task Detail — Task Decomposition System

> 上游：[../architecture.md](../architecture.md) §3.5（TaskDecomposer）、§3.1（层图，含 `PlanValidator`）、§7.7（工具绑定与不新增选择逻辑）、§8.6（校验接口）、§9.7 Q4；[../tasks.md](../tasks.md) PLAN-004
> 状态：设计稿（未实现）
> 范围红线：**纯拆解与纯校验**——`TaskDecomposer` 做四阶段转换，`PlanValidator` 三闸为纯函数；不新增工具选择逻辑；不执行、不落库、零 LLM（校验段）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-004 |
| **Task Name** | Task Decomposition System |
| **Priority** | P0 |
| **Dependencies** | PLAN-002, PLAN-003 |
| **Phase** | Phase 1 规划地基 |
| **建议提交** | `feat: V2.5.0 Goal→Task 拆解与工具绑定校验` |

## 1.1 Goal

交付 **Goal → Task → Action** 的拆解与校验，把 LLM 的原始 `PlanningProposal.sub_goals` 转成合法的 `PlanStepSpec[]`，并完成**工具绑定**：

1. **`TaskDecomposer`**（`app/services/planning/decompose.py`）：结构解析 → 工具绑定 → 判据补全 → 预算校验四阶段。
2. **`PlanValidator`**（同模块）：`validate_shape` / `validate_binding` / `validate_budget` 三闸，**全部纯函数、零 IO、零 LLM**。
3. **粒度裁决落地**：L1 Goal / L2 Task / L3 Action / L4 Tool 四级映射可逐条举证，L2 粒度三条判据（独立判据 + 独立工具绑定 + 一次 Action 内可完成）。

## 1.2 Scope

**包含**

- 新建 `app/services/planning/decompose.py`：`TaskDecomposer` 四阶段 + `PlanValidator` 三闸 + `PlanStepBinding` 产出。
- **B2 关闭点**：`SubGoalSpec.capability`（裸能力名）+ LLM 建议的 `tool_id` 提示 → 经 `ACTION_TOOL_MAP` 与 `ACTIONS` 反查 → `ToolBinding`；一能力多工具时由 `ToolSelector.select_with_reason` 的确定性规则（priority + `tool_id` 字典序）裁决；`binding_reason` 记账。
- **B7 关闭点（拆解侧）**：`criteria.fact_source="tool"` 的判据补全与 `observation_keys` 白名单落地。
- 预算校验四项：步数 / 深度 / 每步尝试上限 / 计划 TTL。
- Q4 冻结：`fact_source="tool"` 下 **拒绝** `threshold_reached`。
- 单元 / 集成 / 场景测试。

**不包含（Non-Scope）**

- 六源装配与七道闸（属 PLAN-003）。
- 判据**求值**的 `tool` 源实现（属 PLAN-005 `PlanObserver.evaluate`）。
- 工具面的解析与裁剪（V2.4.0 既有 `ToolSurfaceResolver`，零改动）。
- 工具解析 / 授权 / 校验 / 执行的运行时（属 PLAN-006）。
- 步骤调度与执行（属 PLAN-005）。
- `PlanValidator` 的对外契约冻结（属 PLAN-011）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 中的 **B2（计划与工具互不相识）**，并补齐 **B7 的拆解侧**：

| 断层 | 现状 | 本任务的关闭方式 |
|---|---|---|
| B2 | `SubGoalSpec.capability` 是裸能力名（如 `"world_action"`），`goal_execution.attempt_current_step` 直构 `ActionIntent`，**不经 `ToolSelector` / `ToolSurface`** | 四阶段之②把能力名 + LLM 提示转成确定性的 `tool_id` 绑定，写入 `SubGoalSpec.tool_id` 与 `binding_reason` |
| B7 | `criteria` 的 `fact_source` 只有 `world` / `state` / `memory` | 四阶段之③允许 `fact_source="tool"`，并把可见键收敛到 `observation_keys` 白名单 |
| 粒度模糊 | 「一步」到底多细无判据 | 四阶段交付 L1~L4 映射表与 L2 三条粒度判据 |

**本任务最容易写错的一处**：把「绑定」写成「选择」。绑定必须是**确定性**的（同输入同输出、可复现），否则重复运行会产生不一致的 `tool_id`，进而使幂等键与审计失去意义。§10.1 的 tiebreak 复现性用例即为该风险的守卫。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Memory 2.0** | **不涉及**（拆解不读记忆；记忆由 PLAN-003 装配进 `PlanContext`） |
| **Reflection System** | **不涉及**（拆解不读 Insight；`evidence_refs` 由 PLAN-003 透传、PLAN-010 注入） |
| **Autonomy 2.0** | **不涉及**（拆解不决定「该不该做」） |
| **World Simulation** | 只读 `ctx.world` 的既有投影用于 prompt 素材（不新读） |
| **Tool System V2.4.0** | **核心交互面**：`ToolRegistry.resolve` / `ToolSurface` / `ToolSelector.select_with_reason` / `ToolBinding` / `ToolDefinition.effects` |

**关键事实（已核对真实源码）**

- `app/character/asuna/action.py::ACTION_TOOL_MAP` 现为 **9 键 → 10 工具**：
  `create_reminder → (builtin.reminder.create,)`、`cancel_reminder → (builtin.reminder.cancel,)`、`remember_fact → (builtin.memory.save,)`、`create_object → (world.object.create,)`、`move_object → (world.object.move,)`、`use_object → (world.object.use,)`、`query_environment → (world.env.query,)`、`query_search → (builtin.search.query,)`、`send_notification → (builtin.notification.send, channel.feishu.send)`。
  **唯一的多对一映射是 `send_notification`**——即 architecture 举的 tiebreak 例。
- `app/services/tool/surface.py::ToolSelector.select_with_reason(intent, surface)` 已有确定性规则，导出理由：`SELECTION_REASON_PRIORITY_ORDER = "priority_order"` / `SELECTION_REASON_CHANNEL_RECIPIENT = "channel_recipient_preferred"` / `SELECTION_REASON_NO_CANDIDATE = "no_candidate"`；并有 `delivery_recipient(intent)` 与 `_legacy_binding`（`ACTION_TOOL_MAP` 未覆盖时按 `(capability, action)` 兜底）。
- `app/services/tool/registry.py::ToolRegistry.resolve(tool_id)` 与 `ToolDescriptor`；`TOOL_ID_PATTERN` 为点分 1~3 段小写标识。
- `app/models/tool.py::TOOL_EFFECT_KINDS = ("world", "memory", "relationship", "note", "external")`（5 值）、`TOOL_FAILURE_KINDS`（6 值）。
- `app/services/tool/builtin.py` 九个内置 + `app/services/tool/channel_tools.py::channel.feishu.send` = 10 个内置工具；`TOOL_UNAVAILABLE_TOOL_IDS`（含 `builtin.search.query`）在 `surface.py` 被剔除。
- `app/models/goal.py::validate_sub_goals(sub_goals, max_depth=2)` 已实现「序号连续 / 无前向依赖 / 深度封顶」；`SubGoalSpec.validate_criteria(criteria, depth=0)` 已实现判据白名单与组合判据嵌套一层。
- `app/services/goal_planning.py::_template(settings, domain)` 提供领域模板（拆解可复用其占位语义，但不复制其逻辑）。

## 2.2 为什么需要本任务

architecture §3.5 的粒度裁决指出：**L2 就是 Task，不再细分**——细于 L2 无判据可观测，粗于 L1 无法执行。既有 `SubGoalSpec` 的 `criteria` + `capability` + `params` 三件套恰好构成这个粒度，因此**不新建 Task 模型**。

而要让 L2 真正「可执行」，还缺两件事：**工具绑定**（否则 `capability` 无法落到 `tool_id`）与**判据补全**（否则步骤达不达成无从判定）。本任务就是补这两件事，并把「不接受什么」用纯函数写成三闸。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 结构解析（复用 `validate_sub_goals`）并把 `PlanningProposal` 转为 `PlanStepSpec[]` | `TaskDecomposer` 阶段① |
| R2 | 工具绑定（能力名 + LLM 提示 → `tool_id`），确定性且可复现 | `TaskDecomposer` 阶段② |
| R3 | `binding_reason` 记账（`tool_selector` / `capability_map` / `fallback`） | `TaskDecomposer` 阶段② |
| R4 | 判据补全（`fact_source="tool"` 的语义与 `observation_keys` 白名单） | `TaskDecomposer` 阶段③ |
| R5 | 预算校验（步数 / 深度 / 每步尝试上限 / 计划 TTL） | `TaskDecomposer` 阶段④ |
| R6 | 三闸纯函数与可读理由列表 | `PlanValidator` |
| R7 | 四级映射与 L2 三条粒度判据的可举证清单 | 文档 + 用例 |
| R8 | Q4 冻结（`fact_source="tool"` 下拒绝 `threshold_reached`） | 校验规则 + 用例 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 六源装配 | PLAN-003 |
| N2 | 七道闸的调度（何时调用三闸、拒绝后如何落 `rejected`） | PLAN-003（**本任务只提供三闸纯函数**） |
| N3 | 工具面的解析（`ToolSurface` 从哪来） | PLAN-003 装配 |
| N4 | 工具解析 / 授权 / 校验 / 执行运行时 | PLAN-006 |
| N5 | `criteria_result` 的实际求值（`fact_source="tool"` 的运行时判定） | PLAN-005 `PlanObserver.evaluate` |
| N6 | 步骤调度与执行 | PLAN-005 |
| N7 | 计划终态记忆与反思证据 | PLAN-009 / PLAN-010 |
| N8 | 新增工具选择规则 | **永不**（architecture §7.7 关键裁决） |

## 3.3 职责边界一句话

> **本任务把「一步该用什么工具、怎么算做成」写进步骤；它不执行这一步，也不决定这一步该不该做。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/decompose.py` | **新增** | `TaskDecomposer` 四阶段 + `PlanValidator` 三闸 | → `models/goal.py`（`validate_sub_goals`）/ `models/tool.py`（`ToolBinding` / `TOOL_EFFECT_KINDS`）/ `character/asuna/action.py`（`ACTION_TOOL_MAP`）/ `ToolRegistry`（`resolve`，只读）/ `ToolSelector.select_with_reason`（只读、确定性） |

**分层纪律**：
- `decompose.py` **不 import** `world_repository`（PLAN-008 红线 G-WORLD）。
- `decompose.py` **不 import** `ToolExecutor` / `Capability.execute`（PLAN-006 红线 G-EXEC）。
- `PlanValidator` 三闸**不 import** 任何仓储或网络模块（纯函数纪律）。

### 4.1.2 Component 划分

```text
app/services/planning/decompose.py
├── TaskDecomposer
│     decompose(proposal, goal, ctx, *, settings) -> DecompositionResult
│       ├── ① 结构解析   parse_structure(proposal)      → SubGoalSpec[]（复用 validate_sub_goals）
│       ├── ② 工具绑定   bind_tools(specs, ctx)          → list[PlanStepBinding]
│       ├── ③ 判据补全   complete_criteria(specs, bindings) → SubGoalSpec[]（tool 源 + 白名单）
│       └── ④ 预算校验   check_budget(specs, plan_versions, budget)
└── PlanValidator（纯函数、零 IO、零 LLM）
      validate_shape(steps, *, max_depth) -> list[str]
      validate_binding(steps, surface) -> list[str]
      validate_budget(steps, plan_versions, budget) -> list[str]
```

### 4.1.3 数据流：四阶段

```text
LLM 产出 PlanningProposal.sub_goals（原始 dict 列表）
        │
        ▼
① 结构解析（复用既有）
   PlanningProposal.sub_goals → SubGoalSpec.model_validate（经 validate_sub_goals）
     · 判据白名单：CRITERION_TYPES / CRITERION_FACT_SOURCES / CRITERION_METRIC_PATHS / CRITERION_OPS
     · 序号连续 / 无前向依赖 / 深度封顶 v2_autonomy_subgoal_max_depth = 2
        │ 失败 → 理由 invalid_sub_goal_shape（闸门 3 已拒，本阶段不重复判定）
        ▼
② 工具绑定（B2 关闭点）
   SubGoalSpec.capability（裸能力名）+ LLM 建议的 tool_id 提示
        │  经 ACTION_TOOL_MAP（9 键 → 10 工具）与 ACTIONS 反查
        ▼
   ToolBinding(tool_id, capability, action, definition)   ← 既有 models/tool.py 值对象
     · 一能力多工具（唯一例：send_notification → builtin.notification.send / channel.feishu.send）
         由 ToolSelector.select_with_reason 的确定性规则（priority + tool_id 字典序）裁决
     · 绑定失败 → 该步标记 capability_binding_missing，进入闸门 5/6 的拒绝路径
     · binding_reason ∈ {tool_selector, capability_map, fallback}
        ▼
③ 判据补全（B7 关闭点）
   criteria.fact_source 允许新增 "tool"：
     · action_succeeded → 以 action_records.steps[].status 判定
     · field_equals    → 以 ToolResult.observations 的键判定（受 step.observation_keys 白名单约束）
     · threshold_reached → 【拒绝】（Q4 冻结）
     · 未声明判据的步骤 → 视为不可判定，不参与自动推进（沿用 evaluate_criteria 返回 None 的语义）
        ▼
④ 预算校验（复用既有）
   步数（v25_plan_max_steps / v2_autonomy_subgoal_max_count）
   深度（v25_plan_max_depth）
   每步尝试上限（v25_plan_step_max_attempts）
   计划 TTL（v25_plan_ttl_hours）
        │
        ▼
PlanStepSpec[]（含 tool_id / kind / retry_policy / on_failure / expected_effects
               / observation_keys / binding_reason）
```

## 4.2 Core Model

本任务**不新增模型**（值对象由 PLAN-002 定义）。下表为本任务产出 / 消费的字段契约。

### 4.2.1 拆解产物：`PlanStepSpec`（= 扩展后的 `SubGoalSpec`）字段归因

| 字段 | 本阶段的来源 | 阶段 |
|---|---|---|
| `index` / `description` / `params` / `depends_on` / `parent_index` | LLM 产出经结构解析 | ① |
| `capability` | LLM 产出（裸能力名，保留可追溯） | ① |
| `tool_id` | **工具绑定产出** | ② |
| `binding_reason` | **绑定理由**（`tool_selector` / `capability_map` / `fallback`） | ② |
| `kind` | 由绑定结果推导：有 `tool_id` → `tool`；无且仅观测 → `observe`；有子步 → `composite` | ② |
| `expected_effects` | 由 `ToolDefinition.effects`（既有）投影，取值 ⊆ `TOOL_EFFECT_KINDS` | ② |
| `retry_policy` | 由步骤类型与 `ToolDefinition.idempotency` 推导，默认 `once` | ② |
| `on_failure` | LLM 建议 + 依赖结构推导，默认 `skip`；有后继依赖且不可跳过时升为 `abort` | ② |
| `criteria` | LLM 产出经结构解析 + **判据补全**（`fact_source="tool"` 与白名单） | ①③ |
| `observation_keys` | **判据补全产出**（从 `criteria` 中引用的键反推收敛） | ③ |
| `status` / `attempt_count` / `last_observed_at` / `last_attempt_at` / `failure_note` | 运行期字段，初值由模型默认给出 | — |

### 4.2.2 `binding_reason` 值集（三值）

| 值 | 触发路径 | 说明 |
|---|---|---|
| `tool_selector` | 经 `ToolSelector.select_with_reason` 裁决（一能力多工具） | 理由码与 `SELECTION_REASON_*` 一并记录 |
| `capability_map` | 经 `ACTION_TOOL_MAP` / `ACTIONS` 反查直接命中单工具 | 最常见路径 |
| `fallback` | 上述两者均未命中，按 `(capability, action)` 既有兜底（`ToolSelector._legacy_binding` 语义）寻回 | 记录以便审计 |

### 4.2.3 四级映射（Goal → Task → Action → Tool）

| 层级 | 单位 | 模型 | 谁产生 | 谁消费 | 粒度判据 |
|---|---|---|---|---|---|
| L1 | Goal（想要什么） | `GoalRecord` | `goal_planning.materialize` / `goal_service.review` | Planning / Autonomy | 一句话可陈述，短期不可直接执行 |
| L2 | **Task**（怎么做的一步） | `PlanStepSpec`（扩展 `SubGoalSpec`） | **`TaskDecomposer`** | `PlanScheduler` / `PlanExecutorBridge` | **有独立达成判据 + 独立工具绑定 + 可在一次 Action 内完成** |
| L3 | Action（这一次执行） | `ActionIntent` / `ActionRecord` | `PlanExecutorBridge`（PLAN-005） | `action_engine` | 一次六闸门 + 单步 `ActionStep` 装配 |
| L4 | Tool（动手） | `ToolBinding` / `ToolExecution` | `ToolSelector` | `ToolExecutor` | 一次原子外部调用 |

### 4.2.4 L2 粒度三条判据（可判定）

| # | 判据 | 判定方式 | 反例 |
|---|---|---|---|
| G1 | 有独立达成判据 | `step.criteria` 非空且经白名单校验通过 | 判据为空 → 不构成 Task |
| G2 | 有独立工具绑定 | `step.tool_id` 可经 `ToolRegistry.resolve` 解析（`v25_plan_step_binding_enabled` on 时） | 绑定失败且无降级路径 → 不构成可执行 Task |
| G3 | 可在一次 Action 内完成 | 步骤不跨越多个 `ActionRecord`（由 `retry_policy` 与 `on_failure` 界定单次业务判定） | 需要分支/循环控制流的步骤 → 拆成多个 Task |

### 4.2.5 判据第四事实源的拆解侧语义

| `type` | `fact_source="tool"` 的判定依据 | `observation_keys` 约束 |
|---|---|---|
| `action_succeeded` | `action_records.steps[0].status ∈ ("succeeded",)` | 不适用（不读 observations） |
| `field_equals` | `ToolResult.observations[key] == value` | **`key` 必须 ∈ `step.observation_keys`**，否则不可判定 |
| `threshold_reached` | **拒绝**（Q4 冻结） | — |
| `all_of` / `any_of` | 子判据各自按上表；任一子判据不可判定时 `all_of` 返回 `None`、`any_of` 在无 True 时返回 `None` | 子判据合并 |

### 4.2.6 预算四项（消费 PLAN-002 配置）

| 项 | 参数 | 校验对象 |
|---|---|---|
| 步数 | `v25_plan_max_steps`（5）/ `v2_autonomy_subgoal_max_count`（5） | 顶层步骤数（与 PLAN-003 闸门 2 同源，本任务在拆解后复核） |
| 深度 | `v25_plan_max_depth`（2）/ `v2_autonomy_subgoal_max_depth`（2） | `parent_index` 嵌套深度 |
| 每步尝试上限 | `v25_plan_step_max_attempts`（2） | `retry_policy="until_budget"` 的步骤 |
| 计划 TTL | `v25_plan_ttl_hours`（168） | 计划有效期（相对 `v2_autonomy_goal_max_active_hours`） |

## 4.3 State Machine

本任务**不引入新状态机**——拆解是**一次性转换**（proposal → specs），无跨 tick 状态。

### 4.3.1 拆解状态（运行期瞬时，非持久态）

```text
proposal（LLM 原始输出）
    │
    ├─ ① 结构解析失败 ────────────────► 拒（invalid_sub_goal_shape）；不再进入 ②③④
    ├─ ① 成功 → ② 工具绑定
    │        ├─ 全部绑定成功 ──────────► ③
    │        └─ 存在绑定失败步 ────────► 标记 capability_binding_missing，仍进入 ③④，
    │                                   由 PLAN-003 闸门 5/6 拒绝（不在此处短路）
    ├─ ③ 判据补全
    │        ├─ 全部判据合法 ──────────► ④
    │        └─ 存在 tool 源 + threshold_reached ─► 拒
    └─ ④ 预算校验
             ├─ 四项全过 ──────────────► DecompositionResult(passed=True, steps=[...])
             └─ 任一越界 ──────────────► DecompositionResult(passed=False, *errors)
```

**为什么绑定失败不在此处短路**：闸门 5/6 的判定主体是 `PlanningEngine`（PLAN-003），本任务只负责**标出问题**。这样「闸门 5 过、闸门 6 拒」的单列用例才能成立（architecture §3.4 明确要求该用例）。

### 4.3.2 `kind` 推导规则（无迁移语义）

```text
有 tool_id（绑定成功）                         → kind = "tool"
无 tool_id 且 criteria 可判定（纯观测）         → kind = "observe"
有子步（作为 parent_index 的承载者）            → kind = "composite"
```

| `kind` | 进就绪集 | 产出 `ActionRecord` | 参与判据求值 |
|---|---|---|---|
| `tool` | ✅ | ✅ | ✅ |
| `observe` | ✅（仅观测） | ❌ | ✅ |
| `composite` | ❌（父步不执行，由子步结算） | ❌ | ❌ |

### 4.3.3 `on_failure` 推导规则（默认不放大失败影响）

| 条件 | 推导结果 |
|---|---|
| 默认（无特殊结构） | `skip` |
| LLM 显式声明 | 采信 LLM 值 |
| 本步失败会使后继**全部**不可达（后继链唯一前置） | 升为 `abort` |
| LLM 声明了替代方案（同 `capability` 有其他工具） | 保持 `replan` |
| 本步为可选增强（无后继依赖） | 保持 `continue` |

> **默认值纪律**：默认取 `skip` 而非 `abort`——默认值不得放大失败影响（与 architecture §2.3 红线 8「默认拒绝与降级放行」同源）。

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 谁决定「此刻做什么」 | `autonomy_policy.evaluate` + `decision_pipeline`（既有） | **不涉及** |
| `plan_facts` / 候选面 | PLAN-007 | **不涉及** |

**为什么不涉及**：拆解是「一个已经决定要做的目标，怎么分步」——它不判断该不该做、不参与评分、不消费 `PolicySnapshot`。

## 5.2 与 Tool System

**本任务的核心交互面。**

| 关注点 | Tool System（V2.4.0，不动） | 本任务 |
|---|---|---|
| 工具身份 | `ToolDefinition.id`（点分命名空间，10 个内置） | `tool_id` 指向它 |
| 解析 | `ToolRegistry.resolve(tool_id)` → `ToolBinding` | **绑定阶段调用**（判定可解析性并取 `definition`） |
| 选择 | `ToolSelector.select_with_reason(intent, surface)` | **仅用于一能力多工具的确定性 tiebreak**（同一函数、同一规则） |
| 可用性 | `ToolSurfaceResolver.resolve(run_kind, ctx)` → `ToolSurface` | **只读** `ctx.tool_surface.tool_ids` 做绑定可行性判定 |
| 效果声明 | `ToolDefinition.effects` | 投影为 `expected_effects`（取值 ⊆ `TOOL_EFFECT_KINDS`） |
| 授权 / 校验 / 执行 / 结果 | `ToolPermissionGate` / `ParamValidator` / `ToolExecutor` / `ToolResult` | **本任务不涉及**（PLAN-005 / PLAN-006） |

**关键裁决（architecture §7.7）：Planning 不新增任何工具选择逻辑。**
规划期的「选哪个工具」是**绑定**（`TaskDecomposer`，确定性，一能力多工具时按 `ToolSelector` 的确定性规则）；执行期的「选哪个工具」是**决策**（`ToolSelector` 在真实 intent 与真实面上）。二者用**同一套规则、同一个函数**，因此不会产生分歧——这是计划绑定与执行选择不会打架的结构性保证。

**校验分层**：步骤参数在规划期只做**弱校验**（必填齐备），强校验（结构 + 语义）留给执行期 `ParamValidator.validate`（唯一权威）；弱校验不过的步骤在规划期即被拒。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `ctx.world` / `world_context` | PLAN-003 装配的只读投影 | **只读消费**（不新读世界） |
| 世界写入 | PLAN-008 | **不涉及**：本任务禁止 import `world_repository` |

**为什么不涉及**：「查天气」这类步骤的**世界读取**发生在执行期（`world.env.query` 工具内部），拆解期不预读。计划的步骤「要不要用世界工具」只由 `tool_id` 绑定表达。

## 5.4 与 Memory

**完全不涉及。**

| 关注点 | 本任务 | 原因 |
|---|---|---|
| `ctx.memories` | 由 PLAN-003 装配，拆解不读（只作为 prompt 素材已进上下文） | 拆解不新增记忆检索 |
| `memories` 写入 | 不涉及 | 属 PLAN-009，且必须经 `memory_policy` R1~R8 |
| 边界表 | 不涉及 | 属 PLAN-009 |

## 5.5 与 Reflection

**完全不涉及。**

| 关注点 | 本任务 | 原因 |
|---|---|---|
| `ctx.insights` / `evidence_refs` | PLAN-003 透传，PLAN-010 注入 | 拆解不读 Insight |
| 证据窗 / 监听器 | 不涉及 | 属 PLAN-010 |

## 5.6 与既有 Goal 域 / Action 域

| 既有设施 | 本任务的关系 | 是否改动 |
|---|---|---|
| `models/goal.py::validate_sub_goals` / `SubGoalSpec.validate_criteria` | **复用**为结构解析与判据白名单 | ❌ 零改动（PLAN-002 只扩了 `CRITERION_FACT_SOURCES` 与一条组合校验） |
| `models/tool.py::ToolBinding` / `TOOL_EFFECT_KINDS` | 复用于绑定产物与效果投影 | ❌ 零改动 |
| `character/asuna/action.py::ACTION_TOOL_MAP` / `ACTION_CAPABILITY_MAP` | 复用于能力 ↔ 工具反查 | ❌ 零改动 |
| `services/tool/surface.py::ToolSelector.select_with_reason` | 复用于 tiebreak | ❌ 零改动 |
| `models/action.py::ActionIntent` | 拆解不构造（属 PLAN-005） | ❌ 零改动 |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 七道闸调度 | 不涉及 | PLAN-003 |
| Action 六闸门 / 五段短路 | 不涉及 | PLAN-006 |
| `deferred_world_op` / outbox / `event_bridge` | 不涉及 | PLAN-008 |
| `memories` / `memory_policy` | 不涉及 | PLAN-009 |
| `reflection/evidence.py` / `reflection/lifecycle.py` | 不涉及 | PLAN-010 |
| `PolicySnapshot` / `decision_pipeline` | 不涉及 | PLAN-007 |
| `life_loop` | 不涉及（拆解在规划 job 内被调用） | PLAN-003 已接线 |

---

# 6. API / Interface Design

## 6.1 `TaskDecomposer` 接口

```text
interface TaskDecomposer:
    decompose(
        proposal: PlanningProposal,
        goal: GoalRecord,
        ctx: PlanContext,
        *,
        settings: Settings,
    ) -> DecompositionResult

interface DecompositionResult:
    steps: list[PlanStepSpec]
    bindings: list[PlanStepBinding]
    passed: bool
    shape_errors: list[str]
    binding_errors: list[str]
    criteria_errors: list[str]
    budget_errors: list[str]
```

**参数说明**

| 参数 | 说明 |
|---|---|
| `proposal` | 既有 `goal_planning.PlanningProposal`（LLM 原始输出，含 `sub_goals`） |
| `goal` | 目标记录（用于能力域推导与 `ACTION_TOOL_MAP` 反查上下文） |
| `ctx` | 提供 `tool_surface`（绑定可行性判定）与 `budget`（预算四项） |
| `settings` | 提供四项预算参数（不直接读 `get_settings()`，保持可测） |

## 6.2 `PlanValidator` 接口（纯函数、零 IO、零 LLM）

```text
interface PlanValidator:
    validate_shape(steps: list[PlanStepSpec], *, max_depth: int) -> list[str]
    validate_binding(steps: list[PlanStepSpec], surface: ToolSurface) -> list[str]
    validate_budget(steps: list[PlanStepSpec], plan_versions: int, budget: dict) -> list[str]
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 三闸**全部为纯函数**：零 IO、零 LLM、零 `get_settings()` 直调（参数注入） | 静态断言（§9.2 I6） |
| D2 | 返回**可读理由列表**；**空列表 = 通过** | 对齐既有 `ValidationReport` 形态与语义 |
| D3 | 三闸互不重叠：形状闸不管绑定、绑定闸不管预算 | 用例交叉验证 |
| D4 | 理由码对齐 PLAN-003 §4.2.4 七道闸与 architecture §8.6 | 理由码快照对照 |

## 6.3 分阶段内部接口

```text
# ① 结构解析
parse_structure(proposal, *, max_depth: int) -> list[PlanStepSpec]
    # 复用 models/goal.py::validate_sub_goals（序号连续 / 无前向依赖 / 深度封顶）
    # 失败 → 抛 ValueError（由调用方 PLAN-003 转 rejected + invalid_sub_goal_shape）

# ② 工具绑定
bind_tools(specs: list[PlanStepSpec], ctx: PlanContext, *, registry: ToolRegistry | None)
    -> tuple[list[PlanStepBinding], list[str]]
    # 返回 (绑定列表, 绑定错误列表)
    # 单步绑定：capability + hint → ACTION_TOOL_MAP / ACTIONS 反查 → ToolSelector.select_with_reason tiebreak
    #           → ToolRegistry.resolve 校验 → ToolBinding
    # 绑定失败 → 错误列表追加 capability_binding_missing，该步 tool_id 保持 None

# ③ 判据补全
complete_criteria(specs, bindings) -> tuple[list[PlanStepSpec], list[str]]
    # fact_source="tool" 的语义检查 + observation_keys 白名单收敛
    # 未在 observation_keys 声明的键 → 该判据不可判定（不在本阶段报错，运行期返回 None）

# ④ 预算校验
check_budget(specs, plan_versions: int, budget: dict) -> list[str]
    # 步数 / 深度 / 每步尝试上限 / 计划 TTL 四项
```

## 6.4 绑定契约（可核对表）

| 契约项 | 形态 |
|---|---|
| 绑定输入 | `SubGoalSpec.capability`（必填）+ LLM 建议的 `tool_id` 提示（可选） |
| 反查路径 | `ACTION_TOOL_MAP[action_type]` → 候选 `tool_id` 元组 → 与 `surface.tool_ids` 取交集 |
| tiebreak（候选择一） | `ToolSelector.select_with_reason` 的确定性规则：`priority` 优先，同 `priority` 按 `tool_id` 字典序 |
| 兜底路径 | `ACTION_TOOL_MAP` 未覆盖时按 `(capability, action)` 在面上寻回（`fallback`） |
| 可解析性校验 | `ToolRegistry.resolve(tool_id)` 必须成功，否则 `capability_binding_missing` |
| 产出 | `ToolBinding(tool_id, capability, action, definition)`（既有 `models/tool.py` 值对象） |
| 记账 | `binding_reason` ∈ {`tool_selector`, `capability_map`, `fallback`}；tiebreak 时附 `SELECTION_REASON_*` |
| 确定性 | 同输入同输出（同 `specs` + 同 `surface` + 同 `registry`） |

**唯一一能力多工具用例（`send_notification`）**

| 候选 | 声明面 | 运行时面 | tiebreak 依据 |
|---|---|---|---|
| `builtin.notification.send` | 已注册 | 面上（默认） | `priority` 值 + `tool_id` 字典序 |
| `channel.feishu.send` | 已注册 | **仅当通道启用且非 `late_night`** | 同上；`SELECTION_REASON_CHANNEL_RECIPIENT` 在收件人命中时优先后者 |

> **纪律**：tiebreak **不引入新规则**——只用 `ToolSelector` 既有规则。若 `ToolSelector` 因面裁剪只剩一个候选，绑定即唯一，无歧义。

## 6.5 弱校验契约（规划期）

| 校验项 | 规划期（弱） | 执行期（强，`ParamValidator.validate`） |
|---|---|---|
| 必填齐备 | ✅ 本任务 | ✅ |
| 类型/格式/范围 | ❌ | ✅（唯一权威） |
| 语义（如地点存在性） | ❌ | ✅ |

**弱校验失败的处理**：该步骤在**规划期即被拒**（进 `binding_errors` 或 `criteria_errors`，由 PLAN-003 转 `rejected`），不进入执行。

## 6.6 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| `ValueError`（`validate_sub_goals` / `validate_criteria`） | 结构解析 / 判据白名单 | 由 PLAN-003 转 `rejected` + `invalid_sub_goal_shape`；本任务**不吞**（上抛给调用方） |
| `capability_binding_missing`（非异常，错误码） | 工具绑定 | 记入 `binding_errors`；该步 `tool_id = None`；由 PLAN-003 闸门 5/6 处置 |
| `PlanningProposal.sub_goals` 为空 | 结构解析 | 视为形状非法（无 Task 即无计划），抛 `ValueError` |
| `registry` 为 `None` | 工具绑定 | `v25_plan_step_binding_enabled` off 时允许（不绑定）；on 时全部步骤记 `capability_binding_missing` |

## 6.7 对外暴露面（PLAN-011 冻结）

本任务暴露的公开接口**仅**：`TaskDecomposer.decompose` / `PlanValidator.validate_shape` / `validate_binding` / `validate_budget`。四个分阶段函数为**模块私有**（`_` 前缀或不在 `__all__`），供 PLAN-011 契约对照。

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 拆解产物即 `PlanStepSpec[]`，落 `goal_plans.sub_goals`（既有 JSON 列） |
| 新列 | 无 | 7 个扩展字段是 `SubGoalSpec` 的**模型字段**（PLAN-002），JSON 列内扩展不触发 DDL |
| 新索引 | 无 | 拆解不引入新查询维度 |
| 改 CHECK | 无 | `ck_goal_plans_status` 五值不变；本任务不写状态 |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面：零。**

| 项 | 说明 |
|---|---|
| 落库 | **本任务不落库**。`decompose` 返回内存态 `DecompositionResult`；写入 `goal_plans` 由 PLAN-003 经 `goal_repository.create_plan` / `update_plan_progress` 完成（单一写面） |
| 读取 | 只读 `ctx.tool_surface` / `ToolRegistry`（内存态）/ 既有映射常量（代码资产） |
| 审计 | `binding_reason` / `expected_effects` / `observation_keys` 随 `PlanStepSpec` 序列化进 `goal_plans.sub_goals`（既有 JSON），**不新增审计表** |

> **TL 存储说明**：预算四项（含 `v25_plan_ttl_hours`）只在**校验时**参与判定，不落库。计划有效期由既有 `v2_autonomy_goal_max_active_hours` 在 `goal_observation.advance_goal` 的激活期封顶逻辑中生效（PLAN-005 复用），本任务不新增 TTL 列。

---

# 8. Implementation Plan

## Step 1 — 结构解析（阶段①）

1. 实现 `_parse_structure`：`PlanningProposal.sub_goals` → 逐条 `SubGoalSpec.model_validate`。
2. 复用 `models/goal.py::validate_sub_goals(sub_goals, max_depth)` 完成序号连续 / 无前向依赖 / 深度封顶校验（**不重复实现**）。
3. 空 `sub_goals` 视为形状非法。
4. 单测：形状合法 / 序号不连续 / 前向依赖 / 超深嵌套 / 空列表 各一例。

## Step 2 — 工具绑定（阶段②，B2 关闭点）

1. 实现能力 → 动作 → 工具的反查：`ACTION_TOOL_MAP`（9 键 → 10 工具）与既有 `ACTIONS` / `ACTION_CAPABILITY_MAP`。
2. 单工具命中 → 直接绑定；多工具命中 → 调 `ToolSelector.select_with_reason` 做确定性 tiebreak（priority + `tool_id` 字典序）。
3. 绑定后经 `ToolRegistry.resolve(tool_id)` 校验可解析；失败记 `capability_binding_missing` 并置 `tool_id = None`。
4. 记录 `binding_reason`（`tool_selector` / `capability_map` / `fallback`）。
5. 推导 `kind` / `expected_effects`（取 `ToolDefinition.effects`）/ `retry_policy` / `on_failure`（§4.3.2 / §4.3.3 规则）。
6. 单测：唯一多工具用例（`send_notification`）的 tiebreak 可复现（重复运行输出完全一致）；绑定失败路径。

## Step 3 — 判据补全（阶段③，B7 关闭点）

1. 检查 `criteria.fact_source == "tool"` 的合法性：`action_succeeded` / `field_equals` 允许，`threshold_reached` **拒绝**（Q4 冻结，理由中文可读）。
2. 从 `field_equals` 判据引用的 `path` 反推 `observation_keys` 白名单（收敛而非放任）。
3. 组合判据（`all_of` / `any_of`）递归处理，子判据合并进同一白名单。
4. 未声明判据的步骤：不在本阶段报错，但**不参与自动推进**（运行期 `evaluate_criteria` 返回 `None`）。
5. 单测：白名单生效（未声明键 → 不可判定）；`threshold_reached` 负例；组合判据递归。

## Step 4 — 三闸（`PlanValidator`）

1. `validate_shape(steps, *, max_depth)`：序号连续 / 无前向依赖 / 深度封顶 / `kind` 与 `parent_index` 一致（`composite` 必有子步、非 `composite` 不可有子步）。
2. `validate_binding(steps, surface)`：`kind="tool"` 的步骤必须有可解析的 `tool_id` 且 ∈ `surface.tool_ids`；`expected_effects` ⊆ `TOOL_EFFECT_KINDS`。
3. `validate_budget(steps, plan_versions, budget)`：步数 / 深度 / 每步尝试上限 / 计划 TTL 四项。
4. 三闸全部纯函数，返回可读理由列表，空列表 = 通过。
5. 单测：三类非法产物各有可读拒绝理由，理由码对齐 PLAN-003 §4.2.4 与 architecture §8.6。

## Step 5 — 四级映射与粒度判据用例

1. 交付 L1~L4 映射的可举证清单（§4.2.3）。
2. L2 粒度三条判据（G1 / G2 / G3）各有通过用例与反例。
3. 单测：无判据的步骤不构成 Task（G1 反例）；绑定失败且无降级路径 → 不可执行（G2 反例）；需要分支控制流的步骤应拆为多 Task（G3 反例）。

## Step 6 — Flag 门控与回归

1. `v25_plan_step_binding_enabled` off → 不写 `SubGoalSpec.tool_id`，绑定只在执行期由 `ToolSelector` 发生（V2.4.0 原状）。
2. `v25_plan_tool_required` off → 允许无面规划并退化为 V2.4.0 行为。
3. 回归：`goal_planning` 原拆解路径在 Flag off 下生效，`sub_goals` 落库形状与 V2.4.0 **逐字节一致**。
4. `.env` / `.env.example` 段落补写不在本任务（收口至 PLAN-012）。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 结构解析五例 | 合法 / 序号不连续 / 前向依赖 / 超深嵌套 / 空列表；后四者拒绝 |
| U2 | 判据白名单四元组 | 越出 `CRITERION_TYPES` / `CRITERION_FACT_SOURCES` / `CRITERION_METRIC_PATHS` / `CRITERION_OPS` 各一负例 |
| U3 | **tiebreak 可复现** | `send_notification` 用例重复运行 N 次，输出 `tool_id` **完全一致**（priority + `tool_id` 字典序） |
| U4 | `binding_reason` 与裁决路径一致 | `tool_selector` / `capability_map` / `fallback` 三条路径各一例，`binding_reason` 与实际情况匹配 |
| U5 | 绑定失败 | 不可解析的 `tool_id` → `capability_binding_missing` 专项目例；该步 `tool_id = None` |
| U6 | `kind` 推导三条规则 | 有 `tool_id` → `tool`；纯观测 → `observe`；有子步 → `composite` |
| U7 | `expected_effects` 约束 | 越出 `TOOL_EFFECT_KINDS`（5 值）即拒 |
| U8 | `on_failure` 默认不放大 | 无特殊结构 → `skip`；后继链唯一前置 → `abort` |
| U9 | `fact_source="tool"` 白名单 | 已声明键的 `field_equals` 可判定；**未在 `observation_keys` 声明的键返回 `None`（不可判定，绝不默认 True）** |
| U10 | `threshold_reached` + `fact_source="tool"` | 拒绝，理由可读（Q4 冻结） |
| U11 | 三闸纯函数 | 零 IO / 零 LLM 静态断言；返回值恒为 `list[str]` |
| U12 | 三闸职责不重叠 | 形状闸不管绑定、绑定闸不管预算（交叉用例） |
| U13 | 预算四项越界 | 步数 / 深度 / 尝试上限 / TTL 各一负例 |
| U14 | L2 粒度三判据 | G1 / G2 / G3 各有通过用例与反例 |
| U15 | 组合判据递归 | `all_of` / `any_of` 子判据的 `observation_keys` 合并；嵌套超一层拒绝 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | 与 PLAN-003 的衔接 | `decompose` 产出喂给 `PlanValidator` 三闸，三闸通过则 `PlanningEngine.plan` 落 `validated` |
| I2 | 复用 `validate_sub_goals` | 断言未重复实现（静态：`decompose.py` 调用既有函数） |
| I3 | 复用 `ToolSelector` | 静态断言 `decompose.py` 零自造 tiebreak 规则；tiebreak 调用点唯一 |
| I4 | 复用 `ACTION_TOOL_MAP` | `decompose.py` 不新增映射表（静态断言零新增 `dict[str, tuple[str, ...]]` 常量） |
| I5 | `ToolRegistry.resolve` 调用 | 只读调用；断言零工具状态改动（注册表快照对照） |
| I6 | **纯函数静态断言** | `PlanValidator` 三闸零 IO（零仓储 / 零 LLM / 零 `get_settings()` 直调） |
| I7 | 绑定结果与执行期选择一致 | 对 `send_notification` 用例，规划期绑定结果与执行期 `ToolSelector.select_with_reason` 结果一致（同函数同规则） |
| I8 | `v25_plan_step_binding_enabled` off | 不写 `SubGoalSpec.tool_id`，绑定只在执行期由 `ToolSelector` 发生 |
| I9 | `v25_plan_tool_required` off | 允许无面规划并退化为 V2.4.0 行为 |
| I10 | **Flag off 逐字节一致** | `goal_planning` 原拆解路径生效，`sub_goals` 落库形状与 V2.4.0 逐字节一致 |
| I11 | 零迁移断言 | 迁移链头 `0046`；本任务零写入 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」四步拆解** | LLM 产出 4 个 sub_goals（记录 → 查天气 → 提前提醒 → 当天提醒）→ 拆解 | 4 个 Task 全部绑定成功；`binding_reason` 可读；`observation_keys` 收敛；四项预算通过 |
| S2 | 一能力多工具的 tiebreak 端到端 | `send_notification` + 通道开启 + 非 `late_night` | 绑定结果确定；重复运行一致 |
| S3 | 通道被时段剔除 | `send_notification` + `late_night` | `channel.feishu.send` 不在面 → 绑定落到 `builtin.notification.send`（或按面裁剪后唯一候选）；**不产生死步骤** |
| S4 | 判据第四事实源端到端 | `field_equals` + `fact_source="tool"` + `observation_keys=["condition"]` | 执行后 `observations["condition"]` 可判定；未声明键不可见 |
| S5 | 弱校验拒绝 | 必填参数缺失的步骤 | 规划期即被拒（不进入执行） |
| S6 | Flag off 全链 | 总闸 + 绑定子闸 off → 一次规划 | `sub_goals` 无 `tool_id` 键；形状与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- Goal → Task → Action 三级（含 L4 Tool）映射可逐条举证；L2 粒度三条判据各有通过用例与反例（无判据的步骤不构成 Task）。
- 一能力多工具的绑定 tiebreak 可复现：重复运行输出完全一致（priority + `tool_id` 字典序）；`binding_reason` 与裁决路径一致。
- 绑定失败步进入拒绝路径且理由可读；`capability_binding_missing` 有专项目例。
- `fact_source="tool"` 的 `observation_keys` 白名单生效：未在 `observation_keys` 声明的键的 `field_equals` 判据返回 `None`（不可判定，**绝不默认 True**）。
- 三闸全部为纯函数（零 IO / 零 LLM 静态断言）；三类非法产物（形状 / 工具面 / 预算）各有可读拒绝理由，理由码对齐 PLAN-003 §4.2.4 与 architecture §8.6。
- `v25_plan_tool_required` off 时允许无面规划并退化为 V2.4.0 行为（用例）；`v25_plan_step_binding_enabled` off 时不写 `SubGoalSpec.tool_id`，绑定只在执行期由 `ToolSelector` 发生。
- 深度与步数上限、TTL 三类越界各有负例。
- Q4 冻结落地：`fact_source="tool"` 下 `threshold_reached` 被拒（负例，理由可读）。
- Flag off 时 `goal_planning` 原拆解路径生效，`sub_goals` 落库形状与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- `validate_sub_goals` / `SubGoalSpec.validate_criteria` / `ACTION_TOOL_MAP` / `ACTION_CAPABILITY_MAP` / `ToolSelector.select_with_reason` / `ToolRegistry.resolve` 全部**复用**，调用点可追溯（静态断言：零重复实现）。
- `decompose.py` 零新增工具选择规则、零新增映射表（静态断言）。
- 规划期绑定结果与执行期 `ToolSelector` 选择结果一致（同函数同规则，用例对照）。
- `PlanValidator` 三闸零 IO（静态断言），且只被 `PlanningEngine` / `PlanScheduler` 调用。
- `decompose.py` 零 `world_repository` 导入；零 `ToolExecutor` / `Capability.execute` 调用（G-WORLD / G-EXEC 前置守卫）。
- 既有 `goal_planning` / `goal_observation` 测试零失败；V2.4.0 工具侧既有测试（注册表 / 选择器 / 面投影）零失败。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`；本任务写入量为零。
- **零新建系统**：不新建 Task 模型（复用 `SubGoalSpec`）、不新建工具绑定类型（复用 `ToolBinding`）、不新建映射表（复用 `ACTION_TOOL_MAP`）、不新建选择器（复用 `ToolSelector`）。
- **确定性可复现**：`decompose` 对同输入（`proposal` + `goal` + `ctx` + `settings`）产生同输出（含 `tool_id` / `binding_reason` / `observation_keys`），用例可判定。
- **Q4 冻结留痕**：`fact_source="tool"` 与 `threshold_reached` 的组合语义在本任务内冻结为「拒绝」，理由与后续放开条件（须先定义工具侧指标路径词表）写入本文件与代码注释。
- **文档一致**：本文件与 architecture §3.5 / §3.1 / §7.7 / §8.6 / §9.7 Q4 及 tasks.md PLAN-004 Acceptance Criteria 逐条对应，无自相矛盾。
