# PLAN-002 Task Detail — Planning Domain Model

> 上游：[../architecture.md](../architecture.md) §4.1 ~ §4.9、§5.6、§7.10、§7.11、§9.7 Q2 / Q3；[../tasks.md](../tasks.md) PLAN-002
> 状态：DONE（已实现，commit ed80000，2026-09-16）
> 范围红线：**纯值对象 + 配置骨架**；零 IO、零执行、零治理逻辑；不新建任何表、不加任何列、不扩任何 CHECK；`SubGoalSpec` 扩展字段必须显式加入模型定义（不能靠 JSON 多塞字段）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-002 |
| **Task Name** | Planning Domain Model |
| **Priority** | P0 |
| **Dependencies** | PLAN-001 |
| **Phase** | Phase 1 规划地基 |
| **建议提交** | `feat: V2.5.0 计划域模型与配置骨架` |

## 1.1 Goal

交付计划域的**完整值对象与配置骨架**，为 PLAN-003 ~ PLAN-012 提供唯一类型契约：

1. **Plan**（`GoalPlanRecord` 扩展 4 字段）；
2. **PlanStep**（`SubGoalSpec` 扩展 7 字段）；
3. **ExecutionContext**（`PlanContext`）与结果 / 审计 / 校验值对象（`PlanStepBinding` / `PlanStepOutcome` / `PlanAdvance` / `PlanRevision` / `PlanValidationReport` / `RetryPolicy`）；
4. **ActionItem 契约**（步级 `dedupe_key` 形态与 `PlanStepOutcome → ActionRecord.status` 映射表）；
5. **判据第四事实源**（`CRITERION_FACT_SOURCES` 由三值扩为四值）；
6. **配置域**（13 个 `v25_*` Flag + 14 个参数 + 串行链校验）。

## 1.2 Scope

**包含**

- 新建 `app/models/plan.py`（纯值对象模块，零 IO）：§4.2 全部运行期值对象。
- 扩展 `app/models/goal.py::GoalPlanRecord` 4 个字段：`trigger` / `context_digest` / `revision_of` / `evidence_refs`。
- 扩展 `app/models/goal.py::SubGoalSpec` 7 个字段：`tool_id` / `kind` / `retry_policy` / `on_failure` / `expected_effects` / `observation_keys` / `binding_reason`。
- 扩展 `app/models/goal.py::CRITERION_FACT_SOURCES`：三值 → 四值（新增 `"tool"`）。
- 新建 `app/core/settings/plan.py`：13 Flag + 14 参数 + 参数自校验。
- 扩展 `app/core/settings/enablement.py::enablement_violations`：追加 v25 段七条串行链校验。
- 全局 `Settings` 组装 `PlanSettings`。
- 单元测试：序列化往返、默认值、负例、串行链、双向兼容、静态分层断言。

**不包含（Non-Scope）**

- 任何装配 / 生成 / 拆解 / 调度 / 执行 / 观测 / 修订逻辑（PLAN-003 ~ PLAN-005）。
- `PlanContextAssembler` / `PlanningEngine` / `TaskDecomposer` / `PlanScheduler` / `PlanExecutorBridge` / `PlanObserver` / `PlanRevisionPolicy` / `PlanValidator` 的实现。
- `goal_repository` 只读扩展与调试端点（PLAN-011）。
- 记忆边界表 / 反思证据窗 / 自治 `plan_facts`（PLAN-009 / PLAN-010 / PLAN-007）。
- `.env.example` 段落补写（收口至 PLAN-012）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 断层中的 **B7（判据事实源缺第四类）** 的**类型面**，并为 B2 / B3 / B4 / B5 / B8 提供字段承载：

| 断层 | 本任务提供的承载 |
|---|---|
| B2 计划与工具互不相识 | `SubGoalSpec.tool_id` + `binding_reason` |
| B3 计划校验只因 `ACTION_TYPES` 对齐 | `expected_effects`（取值即 `TOOL_EFFECT_KINDS`）为闸门 5/6 提供校验输入 |
| B4 规划器看不见可用工具面 | `PlanContext.tool_surface`（硬依赖字段） |
| B5 重试语义双份 | `retry_policy` + `on_failure` 显式声明，配合 `v25_plan_step_max_attempts` |
| B7 判据事实源缺第四类 | `CRITERION_FACT_SOURCES` 四值 + `observation_keys` 白名单 |
| B8 无计划可观测面 | `PlanAdvance` / `PlanRevision` 值对象 + `context_digest` 可复现锚点 |

---

# 2. Background

## 2.1 当前系统现状

| 已有系统 | 与计划域模型的关系 |
|---|---|
| **Memory 2.0**（`memory_policy` R1~R8 + `memory2.retriever` + `ingest_from_goal_completion`） | `PlanContext.memories` 是其只读投影；记忆写入通道不在本任务 |
| **Reflection System**（`reflection/evidence.py` + `reflection/lifecycle.py`） | `PlanContext.insights` 是其只读投影；证据通道扩展属 PLAN-010 |
| **Autonomy 2.0**（`autonomy_policy.PolicySnapshot` + `decision_pipeline`） | `PlanContext.run` 记录 run 元信息；`plan_facts` 属 PLAN-007 |
| **World Simulation**（`world_engine` + `world_brief` + `WorldContext`） | `PlanContext.world` / `world_brief` / `world_context` / `situations` / `scene` 是其只读投影 |
| **Tool System V2.4.0**（`ToolRegistry` / `ToolSurface` / `ToolSelector` / `ToolExecutor`） | `PlanContext.tool_surface` 是**硬依赖**；`SubGoalSpec.tool_id` 指向 `ToolDefinition.id` |
| **V9 Action Engine**（`ActionIntent` / `ActionRecord` / `ActionStatus` / `GATE_REASONS`） | `PlanStepOutcome → ActionRecord.status` 映射表；本任务不扩 `ActionStatus` / `GATE_REASONS` |

**关键事实（已核对真实源码）**

- `app/models/goal.py::SubGoalSpec` 是 Pydantic `BaseModel`，**未声明 `extra="forbid"`**——默认 `ignore` 会静默丢弃 JSON 未知键。因此 7 个新字段必须**显式加入模型定义**，不能靠「在 `sub_goals` JSON 里多塞键」绕过（对应 architecture §4.4 `extra` 策略提醒、§9.7 Q3）。
- `app/core/db.py::GoalPlanRow` 的列只有 `id` / `goal_id` / `version` / `status` / `sub_goals`(JSON) / `rejection_reason` / `created_at` / `updated_at`——**无 `trigger` / `context_digest` / `revision_of` / `evidence_refs` 列**。这正是 §9.7 Q2 的落点问题（本任务必须裁决，见 §4.4）。
- `app/models/tool.py::TOOL_EFFECT_KINDS = ("world", "memory", "relationship", "note", "external")`（5 值），`TOOL_FAILURE_KINDS`（6 值），`ToolSurface` 有 `run_kind` / `tool_ids` / `excluded` / `surface_hash`，`ToolBinding` 有 `tool_id` / `capability` / `action` / `definition`。
- `app/core/settings/enablement.py::enablement_violations(settings)` 已有 v23 段与 v24 段范式（子闸 → 总闸、跨版本依赖、中文可读理由），v25 段照抄该形态。
- 迁移链头为 `0046_tool_insight_types.py`。

## 2.2 为什么需要本任务

PLAN-002 是 tasks.md §2.2 关键路径的**第二个节点**，也是全版本**唯一**做类型与配置定义的任务。若缺此任务：

- PLAN-003 无法装配 `PlanContext`（无字段契约）；
- PLAN-004 无法绑定工具（无 `tool_id` 字段）；
- PLAN-003 的闸门 5/6 无配置可读（无 `v25_plan_tool_required`）；
- PLAN-005 的判据第四事实源无字段承载（无 `observation_keys`）。
- 且所有后续任务将各自散落新开关——违反 architecture §7.10「后续任务只从本任务定义的配置读取」。

**同时本任务是「零迁移」断言的第一道防线**：`GoalPlanRecord` 4 个新字段的落点若无裁决，实现期极易加列，从而摧毁 architecture §4.9 的强断言。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 定义计划域全部运行期值对象与枚举型字段的值集 | `app/models/plan.py` |
| R2 | 定义 `GoalPlanRecord` 的 4 个扩展字段并**裁决其落点**（Q2） | 模型字段 + 落点表 |
| R3 | 定义 `SubGoalSpec` 的 7 个扩展字段并裁决 `extra` 策略（Q3） | 模型字段 + 双向兼容测试 |
| R4 | 交付 ActionItem 契约（幂等键形态 + 状态映射表） | 契约表（§6.3） |
| R5 | 扩展 `CRITERION_FACT_SOURCES` 为四值，并冻结 `fact_source="tool"` 下的 `threshold_reached` 拒绝语义 | 值集 + 校验规则 |
| R6 | 定义 13 Flag + 14 参数与七条串行链校验 | `app/core/settings/plan.py` + `enablement.py` |
| R7 | 交付零迁移断言与模型层零依赖静态断言 | 测试指令 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | `PlanContext` 的六源装配实现 | PLAN-003 |
| N2 | 七道闸的判定实现 | PLAN-003 / PLAN-004 |
| N3 | 工具绑定的**执行**（`ToolSelector` 调用） | PLAN-004 / PLAN-006 |
| N4 | 判据求值扩展（`evaluate_criteria` 支持 `fact_source="tool"`） | PLAN-005（`PlanObserver.evaluate`） |
| N5 | `PlanAdvance` 落 `decision_records` 的写入实现 | PLAN-005 / PLAN-011 |
| N6 | 记忆 / 反思 / 世界 / 自治四个集成面 | PLAN-009 / PLAN-010 / PLAN-008 / PLAN-007 |
| N7 | 调试端点 | PLAN-011 |

## 3.3 职责边界一句话

> **本任务只定义「计划、步骤、上下文、结果长什么样」以及「开关怎么开」；它不生成计划、不校验计划、不执行计划。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块划分与依赖方向

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/models/plan.py` | **新增** | 计划域运行期值对象 + 枚举值集 + 纯校验辅助 | 仅 `pydantic` / 标准库 / `app.models.goal` / `app.models.tool`（**同为模型层**） |
| `app/models/goal.py` | **扩展** | `GoalPlanRecord` +4 字段；`SubGoalSpec` +7 字段；`CRITERION_FACT_SOURCES` 四值 | 无新依赖 |
| `app/core/settings/plan.py` | **新增** | `PlanSettings(BaseSettings)`：13 Flag + 14 参数 + 自校验 | `app.core.settings._shared` |
| `app/core/settings/enablement.py` | **扩展** | v25 段七条串行链校验 | 读 settings |
| 全局 `Settings` 组装 | **扩展** | 并入 `PlanSettings` | 增量追加 |

**分层纪律（静态断言强制）**：`app/models/plan.py` 与 `app/models/goal.py` / `app/models/tool.py` 同级，属纯值对象层——**禁止** import `app.repositories` / `app.services` / `app.application`。该约束由静态扫描测试强制（同 `models/action.py` / `models/tool.py` 纪律）。

### 4.1.2 Component 划分

```text
app/models/plan.py（新增，纯值对象）
├── 输入段
│     PlanContext                 # 规划输入契约（六源 + 预算 + degraded）
├── 绑定段
│     PlanStepBinding             # step_index + ToolBinding + binding_reason
│     RetryPolicy                 # mode + max_attempts（引用 settings，不自建退避）
├── 结果段
│     PlanStepOutcome             # 步骤执行与观测结果契约
├── 审计段
│     PlanAdvance                 # 推进裁决（落 decision_records）
│     PlanRevision                # 修订记录（落 goal_plans 新版本行）
└── 校验段
      PlanValidationReport        # passed + shape_errors + surface_errors + budget_errors

app/models/goal.py（扩展）
├── SubGoalSpec  +tool_id / kind / retry_policy / on_failure / expected_effects
│                / observation_keys / binding_reason
├── GoalPlanRecord +trigger / context_digest / revision_of / evidence_refs
└── CRITERION_FACT_SOURCES: ("world","state","memory") → ("world","state","memory","tool")
```

### 4.1.3 数据流（值对象生命周期）

```text
① 装配期（PLAN-003）      PlanContext（内存值对象，不落库）
                             ↓ 进 loop_runs.steps / decision_records.input_snapshot
② 拆解期（PLAN-004）      PlanStepBinding[] → 写入 SubGoalSpec.tool_id / binding_reason
                             ↓
③ 落库（PLAN-003）        GoalPlanRecord + SubGoalSpec[] → goal_plans（既有表）
④ 执行期（PLAN-005）      PlanStepOutcome（从 ActionRecord.steps[0].result 归一）
                             ↓
⑤ 推进期（PLAN-005）      PlanAdvance → decision_records（复用 kind='goal_lifecycle'）
⑥ 修订期（PLAN-005）      PlanRevision → 新 GoalPlanRecord（version+1，既有表）
⑦ 校验期（PLAN-004）      PlanValidationReport（纯函数返回，不落库）
```

## 4.2 Core Model

### 4.2.1 `PlanContext`（规划输入契约，不落库）

| 字段 | 类型 | 必填 | 来源（既有入口） | 说明 |
|---|---|---|---|---|
| `goal` | `GoalRecord` | ✅ | `goal_repository.get_goal` | 唯一硬依赖 |
| `ancestors` | `list[GoalRef]` | ⭕ | `goal_repository.list_children` / 逐级上溯 | 父目标链 |
| `siblings` | `list[GoalRef]` | ⭕ | `goal_repository.list_top_level_layered` | 同层同域目标 |
| `world` | `dict` | ⭕ | `world_engine.collect_facts` | 天气 / 时段 / 地点 / 显著事件 |
| `world_brief` | `WorldBrief` | ⭕ | `world_brief.build_world_brief` | prompt 级简报（≤ `world_brief_char_budget`） |
| `world_context` | `WorldContext` | ⭕ | `world_engine.build_context` | 完整世界切片（含库存 / 附近物） |
| `situations` | `list[UserSituation]` | ⭕ | `world_simulation_repository.get_active_situation` | 用户处境 |
| `scene` | `SceneProfile` | ⭕ | `scene_profiles.scene_profile_for` | 场景画像 |
| `relationship` | `dict` | ⭕ | `state_service`（`stage` / `tension`） | 关系阶段（工具面裁剪亦依赖） |
| `memories` | `list[MemoryRef]` | ⭕ | `memory2.retriever.retrieve` | 相关长期记忆（有界） |
| `insights` | `list[InsightSummary]` | ⭕ | `reflection/lifecycle.py::list_user_active_insights` | 活跃反思结论 |
| `tool_surface` | `ToolSurface` | ✅ | `ToolSurfaceResolver(registry, settings).resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx)` | **硬依赖** |
| `run` | `dict` | ⭕ | `RunContext` 投影 | `run_id` / `run_kind` / `trigger_type` |
| `budget` | `dict` | ✅ | settings 投影 | 步数 / 深度 / 修订 / 尝试四项上限 |
| `degraded` | `list[str]` | ⭕ | 装配器 | 降级源清单（可观测） |
| `evidence_refs` | `list[str]` | ⭕ | PLAN-010 注入 | 触发本轮规划的 Insight / 记忆 id（§7.6 ⑥） |

**`degraded` 的意义**：装配失败的源逐条登记并进 `loop_runs.steps`，使「计划为什么规划成这样」事后可解释。

**`GoalRef` 最小形态**：`id` / `type` / `status` / `layer` / `domain` / `priority`（只读投影，避免上下文持有完整 `GoalRecord` 造成的耦合）。

### 4.2.2 `PlanStepOutcome`（步骤结果契约，双落点）

| 字段 | 类型 | 说明 |
|---|---|---|
| `step_index` | int | 步骤序号 |
| `status` | str | `succeeded` / `failed` / `timeout` / `blocked` / `skipped` / `hold` |
| `action_id` | str \| None | 对应 `ActionRecord.id` |
| `tool_id` | str | 实际执行的工具（与计划绑定不一致时回填差异进审计） |
| `failure_kind` | str \| None | 取值即 `TOOL_FAILURE_KINDS`（6 值），**不新增** |
| `attempt` | int | Action 层尝试次数（`ActionRecord.attempt`） |
| `effects` | list[dict] | `ToolResult.effects` 投影（`kind` / `ref` / `reversible`） |
| `observations` | dict | 受 `observation_keys` 白名单裁剪后的键值 |
| `criteria_result` | bool \| None | 判据判定（`None` = 不可判定） |
| `duration_ms` | int \| None | 既有 usage |
| `at` | datetime | 时刻 |

**落点**：`action_records.steps`（执行态）+ `goal_plans.sub_goals`（计划态，步骤状态回填）。

### 4.2.3 `PlanAdvance`（推进裁决，落 `decision_records`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `goal_id` | str | 主体 |
| `plan_id` | str | 主体 |
| `plan_version` | int | 主体 |
| `decision` | str | `advanced` / `completed` / `failed` / `replanning` / `skipped` / `hold` |
| `reason` | str | ≤ 60 字 |
| `step_index` | int \| None | 涉及的步骤 |
| `facts_digest` | dict | 判据所用事实摘要（不含敏感内容） |
| `at` | datetime | 时刻 |

**落点裁决**：写 `decision_records` 时复用 `kind='goal_lifecycle'`（既有 `DecisionKind.GOAL_LIFECYCLE`，CHECK 五值之一），`decision` 承载上表取值，`input_snapshot`（既有 JSON 列）承载 `PlanAdvance`。**新增 kind 需改 `ck_decision_records_kind` = 需迁移，违反红线 1**——V2.4.0 `post_process._persist_tool_decision` 的「复用 kind + 差异化 decision」已是先例。

### 4.2.4 `PlanRevision`（修订记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| `from_version` | int | 修订链起点 |
| `to_version` | int | 修订链终点（= `from_version + 1`） |
| `reason` | str | 四个理由码之一（§4.6） |
| `trigger_source` | str | `step_attempt_exhausted` / `tool_persistently_unavailable` / `criteria_undecidable` / `insight_driven` |
| `evidence_refs` | list[str] | 触发它的 Insight / 记忆 id |
| `kept_steps` | list[int] | 从旧版本保留（已 `done`）的步骤序号 |
| `at` | datetime | 时刻 |

**落点**：新 `GoalPlanRecord`（`version+1`，`revision_of` 指回旧版）+ 旧版置 `superseded`（既有 `set_plan_status`）。

### 4.2.5 运行期值对象（不落库）

| 模型 | 结构 | 用途 |
|---|---|---|
| `PlanStepBinding` | `step_index` + `ToolBinding` + `binding_reason` | 拆解产物（PLAN-004） |
| `ToolBinding` | 既有（`apps/backend/app/models/tool.py`：`tool_id` / `capability` / `action` / `definition`） | 工具绑定 |
| `ToolSurface` | 既有（`run_kind` / `tool_ids` / `excluded` / `surface_hash`） | 工具面 |
| `PlanValidationReport` | `passed` + `shape_errors` + `surface_errors` + `budget_errors` | 三闸校验报告（PLAN-004） |
| `RetryPolicy` | `mode`（`none` / `once` / `until_budget`）+ `max_attempts` | 重试策略（引用 settings，**不自建退避**） |

### 4.2.6 `GoalPlanRecord` 扩展 4 字段（落 `goal_plans`）

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| `trigger` | str | 即既有 `PLANNING_TRIGGERS` 三常量（`goal_created` / `goal_blocked` / `goal_replan`） | 生成 / 修订触发源，**无新值** |
| `context_digest` | str | `PlanContext` 哈希摘要 | 可复现锚点（对齐 `ToolSurface.surface_hash` 工程标准）；由 `v25_plan_context_digest_enabled` 控制 |
| `revision_of` | int \| None | 上一版本号 | 修订链可追溯 |
| `evidence_refs` | list[str] | Insight / 记忆 id 列表 | 「这个计划凭什么这么改」 |

### 4.2.7 `SubGoalSpec` 扩展 7 字段（落 `goal_plans.sub_goals` JSON）

| 字段 | 类型 | 默认 | 值集 / 说明 |
|---|---|---|---|
| `tool_id` | str \| None | `None` | 工具绑定 id（10 个内置之一或注册工具）；**`None` 表示未绑定**（`v25_plan_step_binding_enabled` off 或不要求绑定） |
| `kind` | str | `"tool"` | `tool`（工具调用）/ `observe`（纯观测，不执行）/ `composite`（仅作为子步容器） |
| `retry_policy` | str | `"once"` | `none` / `once` / `until_budget` |
| `on_failure` | str | `"skip"` | `abort` / `skip` / `replan` / `continue` |
| `expected_effects` | tuple[str, ...] | `()` | 取值即既有 `TOOL_EFFECT_KINDS`（`world` / `memory` / `relationship` / `note` / `external`） |
| `observation_keys` | tuple[str, ...] | `()` | 允许进入判据的 `ToolResult.observations` 键白名单（防隐式契约） |
| `binding_reason` | str \| None | `None` | `tool_selector` / `capability_map` / `fallback`，进审计 |

> **默认值裁决**：7 个新字段全部给出默认值，使「旧 `sub_goals` JSON（无这些键）经扩展后模型解析成功且新字段取默认值」成立——这是 §10.1 双向兼容断言的前提。
> `on_failure` 默认取 `skip` 而非 `abort`：默认值必须**不放大失败影响**（`abort` 会使计划整体失败），与「默认拒绝 / 降级放行」的既有范式一致（architecture §2.3 红线 8）。

### 4.2.8 判据第四事实源（值集扩展）

```text
CRITERION_TYPES（既有 5 值，不改）       : action_succeeded / field_equals / threshold_reached / all_of / any_of
CRITERION_FACT_SOURCES（既有 3 → 4 值）  : world / state / memory / 【tool】
CRITERION_METRIC_PATHS（既有 4 值，不改） : tension / intimacy / mood / salient_memory_count
CRITERION_OPS（既有 2 值，不改）          : >= / <=
```

| `type` | `fact_source="tool"` 下的判定 | 数据来源 |
|---|---|---|
| `action_succeeded` | `action_records.steps[0].status ∈ ("succeeded",)` | 既有台账 |
| `field_equals` | `ToolResult.observations[key] == value`，`key ∈ step.observation_keys` | V2.4.0 结果契约 |
| `threshold_reached` | **拒绝**（`fact_source="tool"` 下不支持，保持值集最小） | — |

> **与 `SubGoalSpec.validate_criteria` 的接线**：`validate_criteria` 中 `field_equals` / `threshold_reached` 的 `source` 校验读 `CRITERION_FACT_SOURCES`；扩为四值后，除需新增「`source == "tool"` 且 `type == "threshold_reached"` → 拒绝」这一条组合校验外，既有三值行为**零变化**。

### 4.2.9 ActionItem 契约（步级执行映射）

| 项 | 形态 |
|---|---|
| 步级 `dedupe_key` | `plan:{goal_id}:{version}:{index}`（确定性、可复现；版本号进键是「重规划不重复副作用」的前提） |
| `ActionIntent` 字段投影 | `action_type` ← 由 (`capability`, `action`) 经既有映射反查；`params` ← `normalize_core_params(step.params)`；`confidence` ← `"confident"`；`source` ← `"autonomy"` |
| `PlanStepOutcome.status → ActionRecord.status` | 见 §4.6 映射表 |
| `attempt_count` 写入时机 | 仅在步骤**达到 Action 终态**（`succeeded` / `failed`）时递增；`executing` / `planned` 中间态不递增 |

## 4.3 State Machine

本任务定义**值域**，状态机本身由 PLAN-001（Goal）/ PLAN-005（Plan / Task）落地。此处只登记本任务引入的**枚举型字段状态集**。

### 4.3.1 `SubGoalSpec.kind`（三态，无迁移语义）

```text
tool        ── 有 tool_id 绑定，进入执行（唯一会产出 ActionRecord 的类型）
observe     ── 纯观测，只参与判据求值，不执行
composite   ── 仅作为子步容器（parent_index 的承载者），不作为执行单元
```

| `kind` | 进就绪集 | 产出 ActionRecord | 判据求值 |
|---|---|---|---|
| `tool` | ✅ | ✅ | ✅ |
| `observe` | ✅（仅观测） | ❌ | ✅ |
| `composite` | ❌（叶子优先，父步不执行） | ❌ | ❌（由子步结算） |

### 4.3.2 `SubGoalSpec.on_failure`（四态 × 后继矩阵）

| `on_failure` | 本步终态 | 后继步骤 | 计划终态 |
|---|---|---|---|
| `abort` | `failed` | 全部置 `failed` | `failed`（目标 `failed`，`failure_reason="plan_exhausted"`） |
| `skip` | `failed` | 直接后继 `failed`，旁支继续 | 视剩余步骤判定 |
| `replan` | `failed` | 暂停 | 触发 `TRIGGER_REPLAN` |
| `continue` | `failed` | 全部继续（`depends_on` 语义被显式放宽） | 视其余步骤判定 |

> 该矩阵**由 PLAN-005 的 `PlanScheduler` / `PlanObserver` 落地**；本任务只定义字段与值集。

### 4.3.3 `PlanStepOutcome.status`（六态）与 V9 `ActionStatus` 映射

| `PlanStepOutcome.status` | 映射到 `ActionRecord.status` | `gate_reason` | 说明 |
|---|---|---|---|
| `succeeded` | `succeeded` | — | 一致 |
| `failed` | `failed` | — | `failure_kind=permanent` |
| `timeout` | `failed` | — | `failure_kind=timeout`（可重试） |
| `blocked` | `cancelled` | `capability_unavailable` / `permission_denied` / `invalid_params` / `pending_confirmation` | 均属「未执行」，复用 V9 cancelled 语义 |
| `skipped` | —（无 `ActionRecord`） | — | 前置失败导致，不产生行动 |
| `hold` | `planned`（等 `next_retry_at`） | — | 留在计划中等待 |

> **不新增 `ActionStatus` 值，不新增 `GATE_REASONS` 值**（V9 六态 + V2.4.0 已扩的十值 `GATE_REASONS` 已完备）。

### 4.3.4 `RetryPolicy.mode`（三态）

| `mode` | 语义 | 对应设置 |
|---|---|---|
| `none` | 不重试（业务性一次判定） | — |
| `once`（默认） | Plan 层尝试上限 = 1 次业务判定 | — |
| `until_budget` | Plan 层尝试直到 `v25_plan_step_max_attempts` | `v25_plan_step_max_attempts`（默认 2） |

> **纪律**：`RetryPolicy` **不承载退避数学**。退避只有一份，在 Action 层（`action_retry_backoff_seconds`）。

## 4.4 落点裁决（Q2 / Q3 的正式结论）

### 4.4.1 Q2：`GoalPlanRecord` 4 个新字段的落点

**裁决**：4 个字段作为 `GoalPlanRecord` 的**模型字段**声明；**落库不新增列**——写入 `decision_records.input_snapshot`（既有 JSON 列）。

| 字段 | 模型层 | 落库落点 | 理由 |
|---|---|---|---|
| `trigger` | ✅ 模型字段 | `decision_records.input_snapshot`（规划轮次审计行） | `GoalPlanRow` 无该列；加列会使 architecture §4.9 零迁移断言失效 |
| `context_digest` | ✅ 模型字段 | 同上 | 同上（可复现锚点随规划轮次审计更自然） |
| `revision_of` | ✅ 模型字段 | 同上 | 同上 |
| `evidence_refs` | ✅ 模型字段 | 同上 + `PlanContext.evidence_refs` 注入 prompt | 同上；PLAN-010 消费 |

**判定读法**：投影 `PlanRevision` / 计划详情时，从 `goal_plans`（本体）+ `decision_records`（`kind='goal_lifecycle'` 且 `decision` 为规划轮次名）联合读取。**不新增列、不新增表。**

### 4.4.2 Q3：`SubGoalSpec` 的 Pydantic `extra` 策略

**裁决**：保持默认 `ignore`（不改 `extra` 设置），但 7 个新字段**必须显式加入模型定义**。

| 维度 | 结论 |
|---|---|
| 旧 JSON → 新代码 | 无扩展键 → 新字段取默认值 → 解析成功（**向后兼容成立**） |
| 新 JSON → 旧代码 | 扩展键为未知键 → `ignore` 静默丢弃 → 解析成功（**向前兼容成立**）；旧代码不会读到新字段，也不会因此报错 |
| 若改 `extra="forbid"` | ❌ 禁止：会使旧代码读新 JSON 直接报错，破坏 architecture §7.11「双向兼容成立」 |
| 若靠 JSON 多塞字段而不加模型字段 | ❌ 禁止：`ignore` 会静默丢弃，字段永不生效（这是最易犯的错） |

**双向兼容测试**（§9.1 U7）是本裁决的可判定证据。

## 4.5 配置骨架

### 4.5.1 13 个 `v25_*` Flag（照抄 architecture §7.10）

| Flag | 控制面 | 依赖 | 默认 |
|---|---|---|---|
| `v25_planning_enabled` | **总闸**：计划编排层启用 | — | off |
| `v25_plan_context_enabled` | `PlanContextAssembler` 六源装配 | 总闸 | off |
| `v25_plan_step_binding_enabled` | Step 的 `tool_id` 绑定与闸门 5/6 | 总闸 | off |
| `v25_plan_scheduler_enabled` | `PlanScheduler` 就绪判定与拓扑排序 | 总闸 | off |
| `v25_plan_execution_enabled` | `PlanExecutorBridge` 步骤执行接线 | 总闸 + `action_enabled` | off |
| `v25_plan_observation_enabled` | 判据第四事实源 `tool` 与 `PlanObserver` 推进 | 总闸 | off |
| `v25_plan_revision_enabled` | `PlanRevisionPolicy` 与重规划入队 | 总闸 | off |
| `v25_plan_memory_enabled` | 计划终态记忆边界表 | 总闸 + `v2_memory_enabled` | off |
| `v25_plan_reflection_enabled` | 计划证据窗 + `PlanningRevisionListener` | 总闸 + `v2_reflection_enabled` | off |
| `v25_plan_world_feedback_enabled` | 世界事实进 `PlanContext` + 终态广播 | 总闸 | off |
| `v25_plan_autonomy_enabled` | `PolicySnapshot.plan_facts` 与自治侧计划感知 | 总闸 + `v21_agent_runtime_enabled` | off |
| `v25_plan_tool_required` | **强制**要求工具面可用（off 时允许无面规划） | 总闸 + `v24_tool_system_enabled` | **on** |
| `v25_plan_debug_enabled` | 调试端点与管理面 | 总闸 | off |

### 4.5.2 14 个参数（照抄 architecture §7.10）

| 参数 | 默认 | 对齐来源 | 说明 |
|---|---|---|---|
| `v25_plan_max_steps` | 5 | `v2_autonomy_subgoal_max_count` | 单计划步骤数上限 |
| `v25_plan_max_depth` | 2 | `v2_autonomy_subgoal_max_depth` | 步骤嵌套深度上限 |
| `v25_plan_step_max_attempts` | 2 | `action_retry_max_attempts` | Plan 层业务性尝试上限 |
| `v25_plan_revision_budget` | 3 | `v2_autonomy_planning_max_attempts` | 计划版本数上限 |
| `v25_plan_ttl_hours` | 168 | `v2_autonomy_goal_max_active_hours` | 计划有效期 |
| `v25_plan_step_cooldown_minutes` | 30 | `v2_autonomy_subgoal_execute_cooldown_minutes` | 单目标步骤推进节流 |
| `v25_plan_observation_window_minutes` | 120 | `v2_autonomy_observation_window_minutes` | 判据观测窗 |
| `v25_plan_context_memory_limit` | 5 | `memory_top_k` | 进 `PlanContext` 的记忆条数 |
| `v25_plan_context_insight_limit` | 5 | `v2_reflection_context_max_items` | 进 `PlanContext` 的 Insight 条数 |
| `v25_plan_llm_profile` | `""` | `v2_autonomy_planning_llm_profile` | 规划用 LLM profile（空 = 默认） |
| `v25_plan_replan_min_confidence` | 0.7 | `v23_interest_confidence_threshold` | Insight 触发重规划的置信度下限 |
| `v25_plan_reflection_min_samples` | 3 | `v2_reflection_min_evidence` | 计划证据窗样本门槛 |
| `v25_plan_memory_importance_floor` | 0.6 | `memory_importance_threshold` | 计划终态记忆重要度下限 |
| `v25_plan_context_digest_enabled` | True | — | 是否计算 `context_digest` |

### 4.5.3 串行链校验（并入 `enablement_violations`，七条）

```text
① 任一 v25_* 子闸开启            ⇒ 必须 v25_planning_enabled
② v25_planning_enabled          ⇒ v2_autonomy_advanced_enabled AND v2_life_loop_enabled
③ v25_plan_execution_enabled    ⇒ v25_plan_scheduler_enabled AND action_enabled
④ v25_plan_step_binding_enabled ⇒ v25_planning_enabled AND v24_tool_system_enabled
⑤ v25_plan_tool_required        ⇒ v25_plan_step_binding_enabled AND v24_tool_system_enabled
⑥ v25_plan_reflection_enabled   ⇒ v25_planning_enabled AND v2_reflection_enabled
⑦ v25_plan_memory_enabled       ⇒ v25_planning_enabled AND v2_memory_enabled
⑧ v25_plan_autonomy_enabled     ⇒ v25_planning_enabled AND v21_agent_runtime_enabled
```

> 说明：architecture §7.10 列出八条链（含 `v25_plan_autonomy_enabled` 一条）。tasks.md 描述为「七条」。**本任务以 architecture §7.10 的八条为准实现，并把「七 vs 八」的表述差异在验收记录中留痕**（与 PLAN-012 对 GATE 计数差异的处理同款纪律）。其中①为「子闸 → 总闸」的通用条目，②~⑧为跨版本依赖条目，故 architecture 表述为「串行链校验」而 tasks.md 计为七条跨版本项。

**违规时启动 fail-fast**，理由中文可读（与 v23 / v24 同款）：例如 `"v25_plan_execution_enabled 要求 v25_plan_scheduler_enabled（先开调度子闸）"`。

## 4.6 重规划理由码（值集，判定在 PLAN-005）

| 理由码 | 触发条件 |
|---|---|
| `step_attempt_exhausted` | 步骤达 Plan 层尝试上限且 `on_failure=replan` |
| `tool_persistently_unavailable` | 工具连续 N 个 tick 始终 `off_surface` |
| `criteria_undecidable` | `evaluate_criteria` 连续返回 `None` |
| `insight_driven` | Reflection Insight 达门槛并指向该目标（PLAN-010） |

> 本任务定义四个值；`PlanRevisionPolicy.should_replan` 的判定逻辑属 PLAN-005，Q8 的优先级裁决属 PLAN-010。

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `PolicySnapshot.plan_facts` | 属 PLAN-007 | **不涉及**（只提供 `v25_plan_autonomy_enabled` 开关） |
| `decision_pipeline` 候选面 | 属 PLAN-007 | **不涉及** |

**为什么不涉及**：本任务只定义值对象与开关；`plan_facts` 的**内容**需要 `PlanContext` / `GoalPlanRecord` 的运行时数据，属装配与观察层（PLAN-003 / PLAN-007）。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `SubGoalSpec.tool_id` | 指向 `ToolDefinition.id`（`app/models/tool.py`） | **新增字段** |
| `expected_effects` | 取值即 `TOOL_EFFECT_KINDS`（5 值） | **新增字段**，零新增值集 |
| `observation_keys` | 约束 `ToolResult.observations` 可见键 | **新增字段** |
| `PlanContext.tool_surface` | 类型为既有 `ToolSurface` | **新增字段**（硬依赖） |
| 工具解析 / 面投影 / 选择 / 执行 | 属 PLAN-004 / PLAN-006 | **不涉及** |

**为什么不涉及治理逻辑**：本任务只声明 `tool_id` 字段与 `ToolSurface` 的**类型**；「如何绑定」「是否在面上」的判定属 PLAN-004（绑定的确定性规则）与 PLAN-006（治理链路断言）。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `PlanContext.world` / `world_brief` / `world_context` / `situations` / `scene` | 只读投影字段 | **新增字段（类型声明）** |
| 世界事实读取实现 | 属 PLAN-003（装配）/ PLAN-008（集成） | **不涉及** |
| `v25_plan_world_feedback_enabled` | 开关 | **新增开关** |

**为什么不涉及写入**：计划对世界的写入必须经 `deferred_world_op` → outbox → `world_engine`（architecture §7.4），属 PLAN-008；本任务**不引入任何世界写接口**。

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `PlanContext.memories` | `memory2.retriever.retrieve` 的只读投影 | **新增字段（类型声明）** |
| 记忆边界表 / 候选构造 | 属 PLAN-009 | **不涉及** |
| `v25_plan_memory_enabled` / `v25_plan_memory_importance_floor` | 开关与参数 | **新增** |

**为什么不涉及**：计划结果进记忆必须经 `memory_policy.apply_policy` R1~R8（零豁免），属 PLAN-009；本任务**不引入任何记忆写通道**。

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `PlanContext.insights` / `evidence_refs` | `reflection/lifecycle.py::list_user_active_insights` 的只读投影 + 触发证据 | **新增字段（类型声明）** |
| `EVIDENCE_CHANNEL_PLAN` | 属 PLAN-010 | **不涉及** |
| `v25_plan_reflection_enabled` / `v25_plan_replan_min_confidence` / `v25_plan_reflection_min_samples` | 开关与参数 | **新增** |

**为什么不涉及**：证据通道常量在 `app/models/reflection.py::EVIDENCE_CHANNELS`，扩一路属 PLAN-010；本任务不触碰 `models/reflection.py`。

## 5.6 与 V9 Action 域

| 既有设施 | 本任务的关系 | 是否改动 |
|---|---|---|
| `models/action.py::ActionIntent` / `ActionRecord` | 本任务只定义投影契约（§4.2.9） | ❌ 零改动 |
| `models/action.py::ActionStatus` | 映射表引用，不扩值集 | ❌ 零改动 |
| `models/action.py::GATE_REASONS` | 映射表引用，不扩值集 | ❌ 零改动 |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| Autonomy 2.0 | 不涉及（仅开关） | `plan_facts` 属 PLAN-007 |
| Decision Pipeline | 不涉及 | 候选面复用属 PLAN-007 |
| Action Engine 执行链 | 不涉及 | 执行桥属 PLAN-005 |
| outbox / event_bridge | 不涉及 | 世界写入与广播属 PLAN-008 |
| `reflection/evidence.py` | 不涉及 | 证据窗属 PLAN-010 |
| `memory2/ingest.py` | 不涉及 | 记忆候选属 PLAN-009 |
| `life_loop` 挂载 | 不涉及 | 属 PLAN-003 / PLAN-005 |

---

# 6. API / Interface Design

本任务的「接口」是**模型层与配置层契约**，非 HTTP 端点。

## 6.1 值对象接口（`app/models/plan.py`）

```text
model PlanContext:
    goal / ancestors / siblings
    world / world_brief / world_context / situations / scene / relationship
    memories / insights / tool_surface
    run / budget / degraded / evidence_refs

model PlanStepBinding:
    step_index: int
    binding: ToolBinding
    binding_reason: str | None

model PlanStepOutcome:
    step_index / status / action_id / tool_id
    failure_kind / attempt / effects / observations
    criteria_result / duration_ms / at

model PlanAdvance:
    goal_id / plan_id / plan_version
    decision / reason / step_index / facts_digest / at

model PlanRevision:
    from_version / to_version / reason
    trigger_source / evidence_refs / kept_steps / at

model PlanValidationReport:
    passed: bool
    shape_errors: list[str]
    surface_errors: list[str]
    budget_errors: list[str]

model RetryPolicy:
    mode / max_attempts
```

## 6.2 模型扩展接口（`app/models/goal.py`）

```text
model GoalPlanRecord:            # 既有 8 字段 + 新增 4
    trigger: str = "goal_created"                  # 取值 ∈ PLANNING_TRIGGERS
    context_digest: str | None = None
    revision_of: int | None = None
    evidence_refs: tuple[str, ...] = ()

model SubGoalSpec:               # 既有 12 字段 + 新增 7
    tool_id: str | None = None
    kind: str = "tool"                             # tool / observe / composite
    retry_policy: str = "once"                     # none / once / until_budget
    on_failure: str = "skip"                       # abort / skip / replan / continue
    expected_effects: tuple[str, ...] = ()         # ⊆ TOOL_EFFECT_KINDS
    observation_keys: tuple[str, ...] = ()
    binding_reason: str | None = None

CRITERION_FACT_SOURCES: tuple[str, ...] = ("world", "state", "memory", "tool")
```

**Input / Output 约定**

| 模型 | 构造输入 | 输出形态 |
|---|---|---|
| `PlanContext` | `PlanContextAssembler.assemble`（PLAN-003） | 内存值对象；`model_dump` 后进 `loop_runs.steps` / `decision_records.input_snapshot` |
| `PlanStepOutcome` | `PlanExecutorBridge` 归一（PLAN-005） | 序列化后进 `action_records.steps` 与 `goal_plans.sub_goals` |
| `PlanAdvance` | `PlanObserver.observe`（PLAN-005） | 序列化后进 `decision_records.input_snapshot` |
| `PlanRevision` | `PlanRevisionPolicy` / `PlanningEngine.revise`（PLAN-005 / PLAN-003） | 序列化后进 `decision_records.input_snapshot` |
| `PlanValidationReport` | `PlanValidator` 三闸（PLAN-004） | 只读返回，不落库 |

## 6.3 契约表（步级执行映射，供 PLAN-005 实现）

| 契约项 | 值 / 形态 |
|---|---|
| 步级 `dedupe_key` | `plan:{goal_id}:{version}:{index}` |
| Action 层 `dedupe_key`（既有对照） | `goal:{goal_id}:{version}:{index}`（`goal_execution.attempt_current_step` 既有公式） |
| `ActionIntent.action_type` 来源 | (`capability`, `action`) 反查既有映射（`ACTION_CAPABILITY_MAP` 系） |
| `ActionIntent.params` | `normalize_core_params(step.params)` |
| `ActionIntent.confidence` | `"confident"` |
| `ActionIntent.source` | `"autonomy"`（经 `run_action_planning(source=...)`） |
| 状态映射 | §4.3.3 六行表 |
| `attempt_count` 递增时机 | 仅 Action 终态（`succeeded` / `failed`） |

## 6.4 配置接口（`app/core/settings/plan.py`）

```text
class PlanSettings(BaseSettings):
    # 13 Flag（§4.5.1）
    v25_planning_enabled: bool = False
    v25_plan_context_enabled: bool = False
    v25_plan_step_binding_enabled: bool = False
    v25_plan_scheduler_enabled: bool = False
    v25_plan_execution_enabled: bool = False
    v25_plan_observation_enabled: bool = False
    v25_plan_revision_enabled: bool = False
    v25_plan_memory_enabled: bool = False
    v25_plan_reflection_enabled: bool = False
    v25_plan_world_feedback_enabled: bool = False
    v25_plan_autonomy_enabled: bool = False
    v25_plan_tool_required: bool = True          # 唯一默认为 on 的子闸
    v25_plan_debug_enabled: bool = False

    # 14 参数（§4.5.2）
    v25_plan_max_steps: int = 5
    v25_plan_max_depth: int = 2
    v25_plan_step_max_attempts: int = 2
    v25_plan_revision_budget: int = 3
    v25_plan_ttl_hours: int = 168
    v25_plan_step_cooldown_minutes: int = 30
    v25_plan_observation_window_minutes: int = 120
    v25_plan_context_memory_limit: int = 5
    v25_plan_context_insight_limit: int = 5
    v25_plan_llm_profile: str = ""
    v25_plan_replan_min_confidence: float = 0.7
    v25_plan_reflection_min_samples: int = 3
    v25_plan_memory_importance_floor: float = 0.6
    v25_plan_context_digest_enabled: bool = True
```

**Input**：环境变量 / `.env`。**Output**：只读配置对象。

| 参数自校验 | 约束 | 违规 |
|---|---|---|
| `v25_plan_max_steps` | ≥ 1 | 启动 fail-fast |
| `v25_plan_max_depth` | ≥ 1 | 启动 fail-fast |
| `v25_plan_step_max_attempts` | ≥ 1 | 启动 fail-fast |
| `v25_plan_revision_budget` | ≥ 0 | 启动 fail-fast（0 = 不许修订） |
| `v25_plan_ttl_hours` | ≥ 1 | 启动 fail-fast |
| `v25_plan_step_cooldown_minutes` | ≥ 0 | 启动 fail-fast |
| `v25_plan_observation_window_minutes` | ≥ 1 | 启动 fail-fast |
| `v25_plan_context_memory_limit` / `insight_limit` | ≥ 0 | 启动 fail-fast |
| `v25_plan_replan_min_confidence` | `[0.0, 1.0]` | 启动 fail-fast |
| `v25_plan_reflection_min_samples` | ≥ 1 | 启动 fail-fast |
| `v25_plan_memory_importance_floor` | `[0.0, 1.0]` | 启动 fail-fast |

## 6.5 启用链接口

```text
enablement_violations(settings) -> list[str]     # 既有函数，追加 v25 段（§4.5.3 八条）
```

| 契约项 | 约定 |
|---|---|
| 返回 | 违规理由列表；空列表 = 通过 |
| 理由语言 | 中文可读，含「哪个闸要求哪个闸」 |
| 调用时机 | 启动边界（与 v23 / v24 段同一调用点） |

## 6.6 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| Pydantic `ValidationError` | 值对象构造（非法 `status` / `mode` / `on_failure` 等） | 调用方在规划期转 `rejected`；不吞 |
| `ValueError`（`validate_criteria`） | 判据白名单 | 规划期转 `rejected` + `invalid_sub_goal_shape` |
| `ValueError`（参数自校验） | `PlanSettings` | 启动 fail-fast |
| 串行链违规 | `enablement_violations` | 启动 fail-fast，中文理由 |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | architecture §2.3 红线 1；plan / step / audit / evidence 全部落在 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表 |
| 新列 | 无 | `GoalPlanRecord` 4 个新字段为**模型字段**，落点为 `decision_records.input_snapshot`（既有 JSON 列，见 §4.4.1）；`SubGoalSpec` 7 个新字段落 `goal_plans.sub_goals`（既有 JSON 列，模型字段新增不触发 DDL） |
| 新索引 | 无 | 既有 `uq_goal_plans_goal_version` / `idx_goal_plans_goal_status` 覆盖 |
| 改 CHECK | 无 | `ck_goal_plans_status`（五值）不变；`ck_decision_records_kind`（五值）不变；`ck_character_goals_status` 不变 |
| 迁移 | 无 | 迁移链保持 **0046** |

**落库归属表**

| 数据 | 落点 | 表 / 列 | 是否新列 |
|---|---|---|---|
| 计划本体 + 步骤 | `goal_plans` | `sub_goals`（JSON） | ❌（JSON 内扩展） |
| 计划状态 | `goal_plans` | `status`（既有五值 CHECK） | ❌ |
| 计划拒绝理由 | `goal_plans` | `rejection_reason` | ❌ |
| `trigger` / `context_digest` / `revision_of` / `evidence_refs` | `decision_records` | `input_snapshot`（JSON） | ❌ |
| 步骤执行台账 | `action_records` | `steps`（JSON） | ❌ |
| 计划推进审计 | `decision_records` | `kind='goal_lifecycle'` + `decision` + `input_snapshot` | ❌ |
| 运行态步骤序列 | `loop_runs` | `steps`（JSON） | ❌ |
| 计划生成 job | `background_jobs` | `job_type='goal_planning'`（既有常量） | ❌ |
| 计划证据 | 投影自 `goal_plans` + `action_records` | — | ❌（不建表） |

**向后兼容的唯一接缝**：`goal_plans.sub_goals` 是 JSON 列——新代码写入的扩展字段对旧代码是未知键（Pydantic `ignore` 安全丢弃）；旧代码写入的 `sub_goals`（无扩展字段）对新代码可读（新字段取默认值）。**双向兼容成立**（可判定证据见 §9.1 U7）。

> **若实现期出现建列 / 建表需求**：说明 architecture §3.1 与 §4.1 的两条裁决已被违背，必须回退重审并在验收记录留痕（§9.7 Q2 的既定纪律）。

---

# 8. Implementation Plan

## Step 1 — 值对象模块（`app/models/plan.py`）

1. 定义枚举型字段的值集常量（`PLAN_STEP_OUTCOMES` / `PLAN_ADVANCE_DECISIONS` / `PLAN_REVISION_REASONS` / `STEP_KINDS` / `RETRY_MODES` / `ON_FAILURE_MODES`），导出 `get_args` 派生的 frozenset（对齐 `models/tool.py::TOOL_*_VALUES` 写法）。
2. 按 §6.1 定义 7 个值对象；`PlanContext` 的 `tool_surface` 与 `goal` 为必填，其余可选。
3. `PlanStepOutcome.observations` 只需结构承载；**白名单裁剪由 PLAN-005 的归一器完成**（本任务不做裁剪逻辑）。
4. 加派生只读属性：`PlanValidationReport.passed`（三 errors 全空）、`RetryPolicy.is_bounded`、`PlanAdvance.is_terminal`。
5. 单测：序列化往返、非法值负例、`passed` 派生。

## Step 2 — 模型扩展（`app/models/goal.py`）

1. `GoalPlanRecord` 追加 4 字段（§6.2），全部带默认值——**默认值必须使旧 JSON 解析结果不变**。
2. `SubGoalSpec` 追加 7 字段（§6.2），全部带默认值；**显式写入模型定义**（不得依赖 JSON 额外键）。
3. `CRITERION_FACT_SOURCES` 三值 → 四值（`"tool"` 追加在末尾，保持既有三值相对顺序）。
4. `validate_criteria` 追加一条组合校验：`source == "tool"` 且 `type == "threshold_reached"` → 拒绝（理由中文可读）；其余分支零改动。
5. 单测：双向兼容（§9.1 U7 / U8）、判据负例、既有三值行为零变化。

## Step 3 — 配置域（`app/core/settings/plan.py` + 全局组装）

1. 实现 `PlanSettings(BaseSettings)`，继承既有 `_shared` 基类与 `DOMAIN_MODEL_CONFIG`（模式照抄 `experience.py` / `world_simulation.py` / `tool.py`）。
2. 默认值全部取安全值：**总闸 off，唯一例外是 `v25_plan_tool_required` 默认 on**（architecture §7.10）。
3. 加参数自校验（§6.4 表），违规抛 `SettingsError` 级别失败。
4. 按 settings 包既有组装方式并入全局 `Settings`。
5. 单测：默认值逐条断言、非法参数 fail-fast。

## Step 4 — 启用链（`app/core/settings/enablement.py`）

1. `enablement_violations` 追加 v25 段：§4.5.3 的八条链，形态照抄 v23 / v24 段（子闸 → 总闸循环 + 跨版本条件 + 中文理由）。
2. 把「七条 vs 八条」的表述差异写入代码注释与文档留痕。
3. 单测：每条链一个违规负例，逐条命中并报出违规链名。

## Step 5 — 静态分层断言与零迁移断言

1. 静态扫描测试：`app/models/plan.py` 与 `app/models/goal.py` 零 `app.repositories` / `app.services` / `app.application` 依赖。
2. 零迁移断言：迁移链头仍为 `0046`；`ck_goal_plans_status` 五值、`ck_decision_records_kind` 五值未变；无新增 Alembic revision。
3. 双向兼容回归：用 V2.4.0 生成的 `sub_goals` JSON 快照喂给扩展后的 `SubGoalSpec`，断言解析成功且新字段取默认值。

## Step 6 — Flag 全 off 回归

1. 全量既有测试（零修改）通过。
2. prompt 快照对照：本任务不得引入任何 prompt 差异。
3. `.env` / `.env.example` 段落补写**不在本任务**（收口至 PLAN-012），本任务只保证环境变量可读。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 7 个值对象的 `model_dump(mode="json")` → `model_validate` 往返 | 往返一致（含 `datetime` / tuple / 嵌套 `ToolBinding`） |
| U2 | 枚举型字段非法值负例 | `PlanStepOutcome.status="whatever"` / `RetryPolicy.mode="always"` / `PlanAdvance.decision="x"` / `SubGoalSpec.kind="x"` / `on_failure="x"` / `retry_policy="x"` 均被拒 |
| U3 | `PlanValidationReport.passed` 派生 | 三 errors 全空 → True；任一非空 → False |
| U4 | `expected_effects` 取值约束 | 越出 `TOOL_EFFECT_KINDS`（5 值）即拒 |
| U5 | `GoalPlanRecord.trigger` 取值约束 | 越出 `PLANNING_TRIGGERS`（3 值）即拒 |
| U6 | 13 Flag 默认值与 §4.5.1 逐条一致 | 12 个 off + `v25_plan_tool_required` on |
| U7 | **双向兼容（旧 → 新）** | V2.4.0 快照 `sub_goals`（无扩展键）→ `SubGoalSpec.model_validate` 成功，7 个新字段取默认值；`GoalPlanRecord` 同理 |
| U8 | **双向兼容（新 → 旧）** | 新代码写出的扩展 JSON 对「旧版模型定义」解析成功（未知键被 `ignore` 丢弃，不报错） |
| U9 | `CRITERION_FACT_SOURCES` 四值 | 恰为 `("world", "state", "memory", "tool")` |
| U10 | `fact_source="tool"` + `threshold_reached` 负例 | `validate_criteria` 拒绝，理由可读 |
| U11 | 既有三值判据行为零变化 | `world` / `state` / `memory` 下三类判据的通过 / 拒绝结果与 V2.4.0 逐条一致 |
| U12 | 参数自校验 | 11 项约束各一负例，启动 fail-fast |
| U13 | 串行链七 / 八条 | 每条一个违规负例，逐条命中并报出违规链 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | `PlanSettings` 成功并入全局 `Settings` | 可通过 `get_settings()` 读取（与 `WorldSimulationSettings` / `ToolSettings` 同款验证） |
| I2 | v25 串行链在启动边界生效 | 违规组合 fail-fast，理由中文可读 |
| I3 | `CRITERION_FACT_SOURCES` 扩值后 | 既有判据相关测试（`goal_observation` / `evaluation_rules/goal`）零失败 |
| I4 | `SubGoalSpec` 扩展后 | `goal_planning.validate_sub_goals` 与 `goal_repository.update_plan_progress` 行为零变化（真实 `sub_goals` 读写用例） |
| I5 | `GoalPlanRecord` 扩展后 | `goal_repository.create_plan` / `get_plan` / `get_latest_plan` 行为零变化 |
| I6 | 静态分层断言 | `models/plan.py` 零 `app.repositories` / `app.services` / `app.application` 导入 |
| I7 | 零迁移断言 | 迁移链头 `0046`；`ck_goal_plans_status` / `ck_decision_records_kind` 值集未变；无新 revision |
| I8 | **Flag 全 off 时全量既有测试零修改通过** | 测试文件零 diff |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | Flag off 的规划链路 | 总闸 off → 触发一次规划 | `goal_planning` 走原路径；`sub_goals` 落库形状与 V2.4.0 **逐字节一致** |
| S2 | Flag on 的规划链路 | 总闸 on + 绑定子闸 on → 一次规划 | `sub_goals` 含 `tool_id` / `kind` / `on_failure` 等扩展键；旧读取路径仍可解析（U8 的端到端形态） |
| S3 | 「帮我规划一次旅行」判据第四源 | `fact_source="tool"` 的 `field_equals` 判据 + `observation_keys` 声明 | 已声明键可判定；未声明键返回 `None`（不可判定，**绝不默认 True**） |
| S4 | 配置违规启动 | 子闸 on + 总闸 off | 进程启动即失败，理由中文化 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 全部新增值对象 `model_dump` / `model_validate` 序列化往返测试通过；`RetryPolicy.mode` / `PlanStepOutcome.status` / `PlanAdvance.decision` / `SubGoalSpec.kind` / `on_failure` / `retry_policy` 等枚举型字段各有非法值负例。
- **双向兼容断言（旧 → 新 / 新 → 旧）**：旧版 `sub_goals` JSON（无扩展字段）经扩展后 `SubGoalSpec` 解析成功且新字段取默认值；新代码写入的扩展字段对旧读取方为未知键且安全忽略。
- `CRITERION_FACT_SOURCES` 为四值；`fact_source="tool"` 下的 `threshold_reached` 判据被拒（负例）；既有三值判据行为零变化。
- 13 个 `v25_*` Flag 默认值与 §4.5.1 表逐条一致（总闸 off；`v25_plan_tool_required` 默认 on 除外）。
- 14 个参数默认值与 §4.5.2 表逐条一致；11 项参数自校验各有负例。
- §4.5.3 串行链每条校验各有违规负例，逐条命中并报出违规链；任一子闸开启而总闸关闭时启动 fail-fast 且理由中文可读。
- **`extra` 策略裁决落地**：新字段显式加入模型定义（静态断言：字段名可 grep 到模型定义）；未改变 `extra` 设置。
- ActionItem 契约表（§6.3）逐条可核对：`dedupe_key` 形态、`ActionIntent` 投影四项、状态映射六行、`attempt_count` 递增时机。

## 10.2 Integration Acceptance

- `PlanSettings` 成功并入全局 `Settings`，可通过 `get_settings()` 读取。
- `SubGoalSpec` / `GoalPlanRecord` 扩展后，既有 `goal_planning` / `goal_observation` / `goal_execution` / `goal_repository` 的计划面路径行为零变化。
- `CRITERION_FACT_SOURCES` 扩值后，`goal_observation.evaluate_criteria` 与 `evaluation_rules/goal` 的既有用例零失败。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致（本任务引入任何 prompt 影响即为缺陷）。
- 静态断言：模型层零 `app.repositories` / `app.application` / `app.services` 依赖。

## 10.3 Quality Acceptance

- **零迁移断言**：迁移链头仍为 0046；`ck_goal_plans_status` 与 `ck_decision_records_kind` 值集未变；无新增 Alembic revision；无新表 / 新列 / 新索引 / 新 CHECK 值。
- **无逻辑泄漏**：`app/models/plan.py` 零 IO、零执行、零治理逻辑（无仓储调用、无 LLM 调用、无网络）；`PlanSettings` 只声明与自校验，无业务分支。
- **Q2 / Q3 裁决留痕**：落点裁决（§4.4.1）与 `extra` 策略裁决（§4.4.2）写入本文件与代码注释；「七条 vs 八条」串行链计数差异留痕。
- **文档一致**：本文件与 architecture §4.1 ~ §4.9、§5.6、§7.10、§7.11、§9.7 Q2 / Q3 及 tasks.md PLAN-002 Acceptance Criteria 逐条对应，无自相矛盾。
