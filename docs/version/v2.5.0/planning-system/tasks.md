# V2.5.0 Planning System Tasks

> **上游**：`docs/version/v2.5.0/planning-system/architecture.md`
> **状态**：任务拆分稿（仅拆分，未排期、未实现）
> **主干**：PLAN-001 ~ PLAN-012（依赖顺序即文档顺序）
> **说明**：本文档只做任务级拆分，不展开 Task Detail、不含代码、不含 DDL 与迁移脚本。
> **定位复述**：Planning System = **计划编排层**。把已存在的「目标分解」（`goal_planning` + `GoalPlanRecord` + `SubGoalSpec`）与「工具执行」（`ToolRegistry` + `ToolExecutor`）用一层可观测、可失败、可修订的多步计划焊起来。

---

## 1. 任务总览

### 1.1 总览表

| ID | Task Name | Priority | Dependencies | Phase |
|---|---|---|---|---|
| PLAN-001 | Goal Model & Lifecycle | P0 | 无 | Phase 1 规划地基 |
| PLAN-002 | Planning Domain Model | P0 | PLAN-001 | Phase 1 规划地基 |
| PLAN-003 | Planning Engine Core | P0 | PLAN-002 | Phase 1 规划地基 |
| PLAN-004 | Task Decomposition System | P0 | PLAN-002, PLAN-003 | Phase 1 规划地基 |
| PLAN-005 | Plan Execution Engine | P0 | PLAN-004 | Phase 2 执行引擎 |
| PLAN-006 | Tool System Integration | P0 | PLAN-005 | Phase 2 执行引擎 |
| PLAN-007 | Autonomy Integration | P1 | PLAN-005, PLAN-006 | Phase 3 系统集成 |
| PLAN-008 | World Simulation Integration | P1 | PLAN-005, PLAN-006 | Phase 3 系统集成 |
| PLAN-009 | Memory Integration | P1 | PLAN-005, PLAN-006 | Phase 3 系统集成 |
| PLAN-010 | Reflection Integration | P1 | PLAN-005 | Phase 3 系统集成 |
| PLAN-011 | Planning API / Interface | P1 | PLAN-005, PLAN-006 | Phase 4 接口与验收 |
| PLAN-012 | Testing & Validation | P0 | PLAN-001 ~ PLAN-011 | Phase 4 接口与验收 |

**Priority 语义**：P0 = 版本发布阻断项（缺一不可上线）；P1 = 版本价值主体；P2 = 可延后至版本内末尾或下一版本。
**Priority ≠ 顺序**：PLAN-012 为 P0 但必须最后执行（验收性质决定）。
**Priority 分布**：本文档无独立 P2 任务——architecture §9.2 中唯一的 P2 交付面（调试端点与管理面）已作为 PLAN-011 的可延后子项并入，见 §6 追溯矩阵。
**Dependencies 记法**：只列**直接**前置；由于 PLAN-005 传递依赖 PLAN-004 → PLAN-003 → PLAN-002 → PLAN-001，故 PLAN-006 ~ PLAN-011 不再重复罗列 PLAN-001 ~ PLAN-004。

### 1.2 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| **Phase 1 规划地基** | 001, 002, 003, 004 | Goal 契约冻结；计划域值对象与 Flag 就位；六源装配与七道闸可用；Goal → Task → Action 拆解可校验 |
| **Phase 2 执行引擎** | 005, 006 | 步骤可调度、可执行、可观测、可推进、可修订；双层重试语义对齐；工具治理不被绕过 |
| **Phase 3 系统集成** | 007, 008, 009, 010 | 与 Autonomy / World / Memory / Reflection 四系统接线完成且各自验收通过 |
| **Phase 4 接口与验收** | 011, 012 | 内部接口与可观测面就位；全部 Gate 全绿；零迁移断言成立 |

---

## 2. 依赖关系

### 2.1 依赖关系图

```text
Phase 1 规划地基
─────────────────────────────────────────────────────────────────
PLAN-001 Goal Model & Lifecycle
    │
    ▼
PLAN-002 Planning Domain Model
    │
    ▼
PLAN-003 Planning Engine Core
    │
    ▼
PLAN-004 Task Decomposition System
    │
    ▼
Phase 2 执行引擎
─────────────────────────────────────────────────────────────────
PLAN-005 Plan Execution Engine
    │
    ├─────────────────────┬──────────────┬──────────────┐
    │                     │              │              │
    ▼                     ▼              ▼              ▼
PLAN-006              PLAN-008       PLAN-009       PLAN-010
Tool System           World Sim      Memory         Reflection
Integration           Integration    Integration    Integration
    │                                                （仅依赖 005）
    ├──────────────┐
    ▼              ▼
PLAN-007       PLAN-011
Autonomy       Planning API
Integration    / Interface
    │              │
    └──────┬───────┘
           │
           ▼
Phase 4 接口与验收
─────────────────────────────────────────────────────────────────
PLAN-012 Testing & Validation
    ▲ 全量扇入：PLAN-001 ~ PLAN-011（含 PLAN-008 / PLAN-009 / PLAN-010）
```

### 2.2 关键路径

```text
PLAN-001 → PLAN-002 → PLAN-003 → PLAN-004 → PLAN-005 → PLAN-006 → PLAN-007 → PLAN-012
```

（8 个任务，为本版本最长依赖链。经 PLAN-008 / PLAN-009 / PLAN-011 的三条链与之等长；经 PLAN-010 的链为 7 个任务。）

### 2.3 并行建议

| 可并行组 | 任务 | 前提 |
|---|---|---|
| A | PLAN-007 ‖ PLAN-008 ‖ PLAN-009 ‖ PLAN-010 ‖ PLAN-011 | PLAN-006 完成（PLAN-010 只需 PLAN-005 完成即可启动） |
| B | PLAN-005 的 PlanScheduler 搬运工作可先于 PLAN-004 收尾启动 | PLAN-002 完成即可（纯函数模块，只依赖模型与既有 `goal_observation`；对齐 architecture §9.4 风险提示） |
| C | PLAN-011 的调试端点骨架可在任意时点搭起 | PLAN-002 完成（端点骨架 + Flag 门控可先于数据面） |

**关键风险点**：PLAN-005 的「搬运等价性」必须先于执行桥接与观测推进定稿——若搬运引入行为变更，后续全部观测语义被污染。因此 PLAN-005 列为 P0，且要求新旧实现逐条对照测试（对齐 architecture §9.4）。

---

## 3. 任务明细

## PLAN-001 Goal Model & Lifecycle

Priority: P0

Goal: 冻结 Goal 域的**四项契约**（Goal Entity / Goal State / Goal Priority / Goal Lifecycle）为 Planning 的只读消费面与单一写回面，并把「计划对目标生命周期的介入点」钉死在三处，使 Planning 成为 Goal System 的纯只读消费者 + 单一状态写回者。

Description:

- 复用 `app/models/goal.py` 的 `GoalRecord` / `GoalPlanRecord` / `SubGoalSpec` 与全部类型域（`GoalType` 4 值 / `GoalStatus` 7 值 / `GoalSource` 3 值 / `GoalHorizon` 2 值 / `GoalLayer` 3 值 / `GoalDomain` 3 值 / `GoalPlanStatus` 5 值 / `SubGoalStatus` 4 值）——**零新增字段、零新增状态值**（对应 architecture §3.2.1）。
- 复用 `GOAL_TRANSITIONS` 与 `goal_transitions(layer, current)` 为唯一迁移权威；`goal_repository.set_status` / `finish_goal` / `complete_goal` / `fail_goal` / `reactivate_goal` 为唯一写面；目标终态一律经 `goal_arbitration.record_goal_lifecycle` 落归因行（对应 architecture §3.2.2）。
- 复用 `goal_arbitration.compute_priority(goal, overlay, relationship_params, settings)` 为唯一优先级算法，分层排序仍由 `goal_arbitration._rank` / `goal_service.select` 的 tier 提升完成；**Planning 不引入第二套优先级**——计划步骤顺序只由 `depends_on` DAG + `index` 决定（结构序），Goal priority 只决定「先规划哪个目标」（对应 architecture §3.2.3）。
- 钉死 Planning 对生命周期的**三个介入点**：目标创建后 `enqueue_planning(trigger=TRIGGER_CREATED)`（既有行为不变）、步骤执行被阻塞 `enqueue_planning(trigger=TRIGGER_BLOCKED)`（新增判定来源）、重规划裁决通过 `enqueue_planning(trigger=TRIGGER_REPLAN)`（新增 Reflection 触发源）；计划终态仍走既有 `goal_observation._complete` → `finish_goal`（对应 architecture §3.2.2 介入点表）。
- 不新增 `GoalStatus` 值：`GoalStatus` 的新增语义一律通过 `failure_reason` 字符串承载（`plan_exhausted` / `criteria_undecidable` 等），不扩 CHECK、不加迁移；计划被拒（`GoalPlanStatus.rejected`）**不改变** `GoalStatus`（对应 architecture §3.2.4、§5.1、§5.4）。
- 四条联动不变量作为本任务的评审红线：计划状态不得单独改写 `GoalStatus`；`GoalStatus` 终态时其 active 计划必须同进终态或冻结；同一 `goal_id` 同时刻最多一个 active 计划；同一 `(layer, domain)` 顶层 active 目标 ≤ 1（对应 architecture §5.4 联动不变量）。
- 对应 architecture §3.2（§3.2.1 ~ §3.2.4）、§5.1、§5.4、§7.2。

Dependencies: 无

Acceptance Criteria:

- **契约零改动断言**：`GoalStatus` / `GOAL_TRANSITIONS` / `LAYER_DEPTH` / `GOAL_TIER` / `GOAL_ORIGINS` 值集与迁移数学零变化（差异对照为空）；`character_goals` 表结构与既有列语义未动。
- **单一写面断言**：Planning 路径对 `character_goals` 的写入只经 `goal_repository.set_status` / `finish_goal` / `reactivate_goal`，零旁路（静态与运行时断言）。
- **不重算优先级断言**：优先级计算调用点唯一（`goal_arbitration.compute_priority`）；Planning 目录零导入角色优先级资产。
- 计划步骤顺序按 `depends_on` DAG + `index` 升序排列；用例：高 `GoalType` tier 目标的后继步骤不越过其前驱（结构序优先于优先级）。
- 计划被拒时目标仍为 `active`（端到端用例）；计划全步达成时目标为 `completed`；计划全步失败且达放弃阈值时目标为 `failed` 且 `failure_reason="plan_exhausted"`；计划被判不值得继续时经 `goal_arbitration.check_abandonment` 双信号转 `abandoned`。
- 四条联动不变量各有可判定用例，含「目标已终态不得留下仍在推进的计划」与「同一 `goal_id` 同时刻最多一个 active 计划」。
- 计划触发入队只用既有三个 `PLANNING_TRIGGERS` 常量，无新增值。
- Flag 全 off 时既有 Goal 域测试零修改通过。

---

## PLAN-002 Planning Domain Model

Priority: P0

Goal: 交付计划域的**完整值对象与配置骨架**——Plan（`GoalPlanRecord` 扩展）/ PlanStep（`SubGoalSpec` 扩展）/ ExecutionContext（`PlanContext`）/ ActionItem（步级执行映射契约）以及结果、审计、校验值对象；并建立 `v25_*` Flag 与参数域及串行链校验。

Description:

- 新建 `app/models/plan.py`（纯值对象模块）：`PlanContext`、`PlanStepBinding`、`PlanStepOutcome`、`PlanAdvance`、`PlanRevision`、`PlanValidationReport`、`RetryPolicy`（对应 architecture §4.2、§4.5、§4.6、§4.7、§4.8）。全部为运行期值对象，**不落库**（`PlanContext` 进 `loop_runs.steps` / `decision_records.input_snapshot`）。
- **Plan = `GoalPlanRecord` 扩展 4 个字段**：`trigger`（取值即既有 `PLANNING_TRIGGERS` 三常量）/ `context_digest`（`PlanContext` 哈希摘要，对齐 `ToolSurface.surface_hash` 工程标准）/ `revision_of` / `evidence_refs`（对应 architecture §4.3）。落点裁决：若 `GoalPlanRow` 无对应列，**优先落 `decision_records.input_snapshot`（既有 JSON 列）而非加列**——加列会使零迁移断言失效（对应 architecture §4.3 落点裁决、§9.7 Q2）。
- **PlanStep = `SubGoalSpec` 扩展 7 个字段**：`tool_id` / `kind`（`tool` / `observe` / `composite`）/ `retry_policy`（`none` / `once` / `until_budget`，默认 `once`）/ `on_failure`（`abort` / `skip` / `replan` / `continue`）/ `expected_effects`（取值即既有 `TOOL_EFFECT_KINDS`）/ `observation_keys` / `binding_reason`（对应 architecture §4.4）。**必须显式加入 `SubGoalSpec` 模型定义**——Pydantic 默认 `ignore` 会静默丢弃 JSON 未知键，不能靠「JSON 里多塞字段」绕过（对应 architecture §4.4 `extra` 策略提醒、§9.7 Q3）。
- ActionItem 契约：步级 `dedupe_key` 形态 `plan:{goal_id}:{version}:{index}`、`ActionIntent` 字段投影与 `PlanStepOutcome → ActionRecord.status` 映射表（对应 architecture §3.7、§5.6）。
- **判据第四事实源**：`CRITERION_FACT_SOURCES` 由三值扩为四值（新增 `"tool"`）；`CRITERION_TYPES`（5 值）/ `CRITERION_METRIC_PATHS`（4 值）/ `CRITERION_OPS`（2 值）值集不改；`fact_source="tool"` 下拒绝 `threshold_reached`（对应 architecture §3.5 ③、§4.4、§9.7 Q4）。
- 新建 `app/core/settings/plan.py`：13 个 `v25_*` Flag 与 14 个参数（对应 architecture §7.10 两张表），并把 v25 串行链校验收入既有 `app/core/settings/enablement.py::validate_enablement_chain`，违规启动 fail-fast、理由中文可读。
- **零迁移是本任务的强断言**：本任务与全版本不新增任何表、列、索引与 CHECK 值；迁移链保持 0046（对应 architecture §4.9、§7.11）。
- 对应 architecture §4.1 ~ §4.9、§5.6、§7.10、§7.11。

Dependencies: PLAN-001

Acceptance Criteria:

- 全部新增值对象 `model_dump` / `model_validate` 序列化往返测试通过；`RetryPolicy` / `PlanStepOutcome.status` / `PlanAdvance.decision` 等枚举型字段有非法值负例。
- **双向兼容断言（旧 → 新 / 新 → 旧）**：旧版 `sub_goals` JSON（无扩展字段）经扩展后 `SubGoalSpec` 解析成功且新字段取默认值；新代码写入的扩展字段对旧读取方为未知键且安全忽略（对应 architecture §7.11 唯一接缝）。
- `CRITERION_FACT_SOURCES` 为四值；`fact_source="tool"` 下的 `threshold_reached` 判据被拒（负例）；既有三值判据行为零变化。
- 13 个 `v25_*` Flag 默认值与 §7.10 表逐条一致（总闸 off；`v25_plan_tool_required` 默认 on 除外）；任一子闸开启而总闸关闭时启动 fail-fast 且理由中文可读。
- §7.10 串行链七条校验各有违规负例，逐条命中并报出违规链。
- 静态断言：模型层零 `app.repositories` / `app.application` / `app.services` 依赖（纯值对象纪律，同 `models/action.py` / `models/tool.py`）。
- **零迁移断言**：迁移链头仍为 0046；`ck_goal_plans_status` 与 `ck_decision_records_kind` 值集未变；无新增 Alembic revision。
- Flag 全 off 时全量既有测试零修改通过。

---

## PLAN-003 Planning Engine Core

Priority: P0

Goal: 交付规划引擎核心：`PlanContextAssembler` 六源输入装配（Goal / Context / World State / Memory / Reflection / ToolSurface，逐源可降级）与 `PlanningEngine` 的计划生成与修订（七道闸短路），并挂进既有 `life_loop` 维护步。

Description:

- 新建 `app/services/planning/context.py`：`PlanContextAssembler.assemble(goal, *, run, now)` 六源装配（对应 architecture §3.3 六源表、§6.3 装配流程）。
  - **硬依赖两源**：Goal 缺失 → 直接返回 `PlanUnavailable("goal_missing")`，**不进入 LLM**；ToolSurface 不可得（总闸 off / registry 不可得）→ 返回 `PlanUnavailable("tool_system_disabled")` / `PlanUnavailable("registry_unavailable")`，宁可这一轮不规划（对应 architecture §3.3 关键约束、§6.3）。
  - **可降级四源**：Context（`scene_profiles.scene_profile_for` + `world_simulation_repository.get_active_situation`）、World（`world_engine.collect_facts` / `build_context` / `world_brief.build_world_brief`）、Memory（`memory2.retriever.retrieve`，受 `v2_memory_retrieval_budget` 与 `v25_plan_context_memory_limit` 约束）、Reflection（`reflection_lifecycle.list_user_active_insights` + `reflection.tool_feed.interest_signal`）；失败降级为空包并逐条登记 `degraded`。
  - ToolSurface 一律按 `RUN_KIND_AUTONOMOUS_TICK` 解析（`build_tool_context` 装配 `ToolContext`）：计划的执行发生在后台节拍，「必须用户在线」的 `channel.*` 类工具被结构性地剔除，规划层不可能规划出「趁用户不在时发消息」的步骤（对应 architecture §6.3 裁决理由）。
  - 契约纪律：除 `assemble` 外组件零 IO；装配只读、零写库；`PlanContextProbe` 提供只读探测（`world_available` / `surface_size` / `degraded_sources`）（对应 architecture §8.2）。
- 新建 `app/services/planning/engine.py`：**包装既有 `goal_planning`，不新建规划器**；`plan` / `revise` / `enqueue` / `run_jobs` / `register_runtime` 签名与 job 形态不变（对应 architecture §3.4 结构、§8.1 接口）。
  - **七道闸短路顺序**：`attempt_cap` → `subgoal_count_exceeded` → `invalid_sub_goal_shape` → `capability_unaligned` → **`plan_tool_unresolvable`（新增）** → **`plan_tool_off_surface`（新增）** → `llm_failed`，理由码沿用既有 `REASON_*` 常量范式（对应 architecture §3.4 闸门表）。
  - 闸门 5 与 6 的区别必须保住：闸门 5 是「这个工具存在吗」（声明面，`ToolRegistry.resolve`），闸门 6 是「这一刻它能用吗」（运行时面，`tool_id ∈ ctx.tool_surface.tool_ids`）——一个工具可能 `enabled` 但被日时段剔除，此时闸门 5 过、闸门 6 拒，计划的步数与内容不变，只是暂不装配该步（对应 architecture §3.4）。
  - `revise(plan, ctx, reason)` 修订语义：`rejected` → 等价于按 `TRIGGER_REPLAN` 重新生成；`active` → 新版本 `version+1` 且旧版置 `superseded`；已终态步骤保留 `index` 与 `depends_on` 语义**不重做**；版本数受 `v25_plan_revision_budget`（默认 3）约束（对应 architecture §3.4 修订语义）。
  - 契约纪律：`plan` / `revise` **不直接落库**（落库经 `goal_repository.create_plan` / `set_plan_status`，保证单一写面）；`plan` 必须 async 且受 `llm_gateway` 与 `life_loop_budget` 双重约束；`enqueue` 必须幂等；**拒绝路径不得抛异常**（拒绝是正常业务结果，异常仅用于实现缺陷）（对应 architecture §8.1）。
- 挂载：`life_loop._step_goal_supply` 与 `agent_runtime` 的 `goal_supply` 阶段内部改走 `PlanningEngine.enqueue` / `run_jobs`，**不改签名、不新增 stage**；规划 job 类型仍为既有 `JOB_TYPE_PLANNING = "goal_planning"`，重规划走同一 `job_type` 并以 `idempotency_key` 区分；规划 LLM 沿用 `v2_autonomy_planning_llm_profile` / `v25_plan_llm_profile`，**不新增 capability 位**（对应 architecture §7.8）。
- 遗留问题 Q6（六源装配中 Memory 检索的嵌入调用与规划 LLM 叠加对 `v2_life_loop_cycle_llm_budget=1` 的压力）在本任务内记录，压测后决定是否给规划单独预算位；若新增 capability 位须同步 §7.8 预算数学说明（对应 architecture §9.7 Q6）。
- 对应 architecture §3.3、§3.4、§6.3、§7.8、§8.1、§8.2、§9.7 Q6。

Dependencies: PLAN-002

Acceptance Criteria:

- 六源各有「可用 / 不可用」两态用例；`degraded` 清单可读并以子步骤记入 `loop_runs.steps`。
- `world_enabled=False` 时 world 为空包且 `degraded` 含 `world_disabled`（对应 architecture §6.3）。
- **零 LLM 断言**：`goal` 缺失或 `tool_surface` 不可得时返回 `PlanUnavailable` 且零 LLM 调用（打桩断言）。
- 装配过程**零写库**（含「不得调用 `world_engine.build_context` 内部写路径」的断言）；除 `assemble` 外组件零 IO（静态断言）。
- 七道闸各有负例，拒绝理由码与 §3.4 表逐条一致；闸门 5 与闸门 6 可分别独立关闭并单独验证；「闸门 5 过、闸门 6 拒」单列用例通过。
- `enqueue` 幂等：同 `idempotency_key` 重复调用不产生第二个 job；job_type 仍为既有 `goal_planning`。
- `revise` 产生 `version+1` 且旧版置 `superseded`；达修订预算上限后计划置 `rejected` 且目标转 `failed("plan_exhausted")`；拒绝路径零异常抛出。
- `life_loop` 九步序列与 `autonomous_tick` stage 序列不变（形状快照对照）；`v2_life_loop_cycle_llm_budget` 数学未变（无新增 capability 位）。
- Flag off 时走 `goal_planning` 原路径（`world_facts` 直入、无 `PlanContext`），prompt 与 V2.4.0 逐字节一致，行为快照对照零差异。

---

## PLAN-004 Task Decomposition System

Priority: P0

Goal: 交付 Goal → Task → Action 的**拆解与校验**：结构解析 → 工具绑定 → 判据补全 → 预算校验四阶段，以及 `PlanValidator` 三闸（形状 / 工具面 / 预算）。

Description:

- 新建 `app/services/planning/decompose.py`：`TaskDecomposer` 四阶段（对应 architecture §3.5）。
  - **① 结构解析（复用既有）**：`PlanningProposal.sub_goals` → `SubGoalSpec.model_validate`；判据白名单（`CRITERION_TYPES` / `CRITERION_FACT_SOURCES` / `CRITERION_METRIC_PATHS` / `CRITERION_OPS`）；序号连续、无前向依赖、`v2_autonomy_subgoal_max_depth`（2）深度封顶。
  - **② 工具绑定（B2 关闭点）**：`SubGoalSpec.capability`（裸能力名）+ LLM 建议的 `tool_id` 提示 → 经 `ACTION_TOOL_MAP`（角色资产，9 → 10 映射）与 `ACTIONS` 反查 → `ToolBinding`（既有 `models/tool.py` 值对象）；一个能力对应多工具时（如 `send_notification` → `builtin.notification.send` / `channel.feishu.send`）由 `ToolSelector.select_with_reason` 的确定性规则（priority + `tool_id` 字典序）裁决；绑定失败步标记 `capability_binding_missing` 并进入闸门 5/6 的拒绝路径；`binding_reason` 记 `tool_selector` / `capability_map` / `fallback`。
  - **③ 判据补全（B7 关闭点）**：`criteria.fact_source="tool"` 允许——`action_succeeded` 以 `action_records.steps[].status` 判定，`field_equals` 以 `ToolResult.observations` 的键判定且受 `step.observation_keys` 白名单约束；**未声明判据的步骤视为不可判定，不参与自动推进**（沿用 `evaluate_criteria` 返回 `None` 的语义）。
  - **④ 预算校验（复用既有）**：步数（`v25_plan_max_steps` / `v2_autonomy_subgoal_max_count`）、深度（`v25_plan_max_depth`）、每步尝试上限（`v25_plan_step_max_attempts`）、计划 TTL（`v25_plan_ttl_hours`）四项过闸。
- 交付 `PlanValidator` 三闸（对应 architecture §8.6）：`validate_shape` / `validate_binding` / `validate_budget`，**全部为纯函数、零 IO、零 LLM**，返回可读理由列表，空列表 = 通过（对齐既有 `ValidationReport` 形态与语义）。
- 粒度裁决落地为可举证清单：L1 Goal（`GoalRecord`，谁产生 `goal_planning.materialize` / `goal_service.review`）/ L2 **Task**（`PlanStepSpec`，谁产生 `TaskDecomposer`）/ L3 Action（`ActionIntent` / `ActionRecord`，谁产生执行桥）/ L4 Tool（`ToolBinding` / `ToolExecution`，谁产生 `ToolSelector`）；L2 粒度判据三条：有独立达成判据 + 有独立工具绑定 + 可在一次 Action 内完成（对应 architecture §3.5 粒度裁决）。
- 遗留问题 Q4（`fact_source="tool"` 与 `threshold_reached` 的组合语义）在本任务内冻结：当前裁决为 `fact_source="tool"` 下**拒绝** `threshold_reached`，保持值集最小（对应 architecture §9.7 Q4）。
- 对应 architecture §3.5、§3.1（PlanValidator）、§7.7（工具绑定与不新增选择逻辑）、§8.6、§9.7 Q4。

Dependencies: PLAN-002, PLAN-003

Acceptance Criteria:

- Goal → Task → Action 三级（含 L4 Tool）映射可逐条举证；L2 粒度三条判据各有通过用例与反例（无判据的步骤不构成 Task）。
- 一能力多工具的绑定 tiebreak 可复现：重复运行输出完全一致（priority + `tool_id` 字典序）；`binding_reason` 与裁决路径一致。
- 绑定失败步进入拒绝路径且理由可读；`capability_binding_missing` 有专项目例。
- `fact_source="tool"` 的 `observation_keys` 白名单生效：未在 `observation_keys` 声明的键的 `field_equals` 判据返回 `None`（不可判定，**绝不默认 True**）。
- 三闸全部为纯函数（零 IO / 零 LLM 静态断言）；三类非法产物（形状 / 工具面 / 预算）各有可读拒绝理由，理由码对齐 §3.4 与 §8.6。
- `v25_plan_tool_required` off 时允许无面规划并退化为 V2.4.0 行为（用例）；`v25_plan_step_binding_enabled` off 时不写 `SubGoalSpec.tool_id`，绑定只在执行期由 `ToolSelector` 发生。
- 深度与步数上限、TTL 三类越界各有负例。
- Flag off 时 `goal_planning` 原拆解路径生效，`sub_goals` 落库形状与 V2.4.0 逐字节一致。

---

## PLAN-005 Plan Execution Engine

Priority: P0

Goal: 交付计划执行引擎：就绪排序（`PlanScheduler`）→ 步骤执行桥接（`PlanExecutorBridge`）→ 观测推进与终态结算（`PlanObserver`）→ 重规划裁决（`PlanRevisionPolicy`），并把 Action 层技术性重试与 Plan 层业务性放弃的**双层重试语义对齐**。

Description:

- **`app/services/planning/scheduler.py`（先搬后改，行为零变更）**：把 `goal_observation._execution_order` / `_current_step` / `_all_done` / `_has_executable` 搬运为公开纯函数，再新增 `ready_steps` / `blocked_reason`（对应 architecture §3.6、§8.4）。
  - 调度规则五条：**依赖优先**（`depends_on` 全 `done`；前驱 `failed` 且 `on_failure=abort` → 后继标 `skipped`）、**叶子优先**（父步不作为执行单元，只在子步全 `done` 后由 `advance_goal` 结算）、**结构序**（同层就绪步按 `index` 升序，不按 Goal priority 重排）、**单步并发上限**（每 tick 每目标最多推进一步，对齐 `v2_autonomy_subgoal_execute_cooldown_minutes` / `v25_plan_step_cooldown_minutes`）、**面感知**（`ready` 但 `tool_id` 不在当前工具面 → 不进可执行集，记 `blocked_reason=off_surface`）。
  - 步骤幂等锚点沿用既有形态 `goal:{goal_id}:{plan.version}:{step.index}`；全部函数同输入同输出（可复现锚点，对齐 `ToolSurface.surface_hash` 的工程标准）。
- **`app/services/planning/executor_bridge.py`**：`to_intent` / `execute_step` / `reconcile`（对应 architecture §3.7、§6.4、§8.4）。
  - 执行链**零新建环节**：`PlanScheduler.current_step` → `to_intent`（`dedupe_key = plan:{goal_id}:{version}:{index}`，`confidence="confident"`，`params` 经 `normalize_core_params`）→ `action_engine.run_action_planning(user_id, intent, session_id, goal_id, source="autonomy")`（六闸门 → `assemble_plan` → `execute_plan` → `integrate_result`）→ 从 `record.steps[0].result` 读 `ToolResult` → `reconcile` 回填 → `goal_repository.update_plan_progress` 落 `goal_plans`。
  - 两道**防御性**断言（不是第二次决策）：① 就绪复核（`ready_steps` 不含该步 → `outcome=skipped`）；② 面复核（`tool_id` 不在当前面 → `outcome=blocked`），用于防「规划到执行之间世界 / 关系 / 时段变化」（对应 architecture §6.4）。
  - `to_intent` 必须产出确定性 `dedupe_key` 且不得生成空 `action_type`；`execute_step` **只**经 `action_engine.run_action_planning`，不得直调 `Capability.execute` 或 `ToolExecutor.run`；`reconcile` 只写内存副本，落库由调用方统一完成（对应 architecture §8.4 契约纪律）。
  - `attempt_count` 的写入时机是步骤**达到 Action 终态**时（而非每次尝试），与 V9 的 `executing` 中间态解耦（对应 architecture §3.7 纪律）。
- **`app/services/planning/observer.py`**：`collect_facts`（四源事实包，含新增 `tool` 源）/ `observe`（委托既有 `advance_goal`）/ `evaluate`（委托 `evaluate_criteria`，扩事实源）/ `settle`（终态 completed / failed / blocked）（对应 architecture §3.8、§8.5）。
  - **事实源扩展（B7 关闭点）**：`CRITERION_FACT_SOURCES` 四值——`world` / `state` / `memory` / **`tool`**；`tool` 源下 `action_succeeded` 以 `action_records.steps[].status` 判定、`field_equals` 以 `ToolResult.observations[<key>]` 判定（key 受 `observation_keys` 白名单约束，未声明键一律不可见，防「偶发字段」变成隐式契约）。
  - 推进结果值集**沿用既有 `advance_goal` 返回值**，不新增：`advanced` / `completed` / `retrying` / `failed` / `replanning` / `skipped`（含 `skipped_ahead`）/ `error`；观测自身 `error` 只 log、不改变计划状态（与 V9「投递失败不回滚执行」同款纪律）。
  - `evaluate` 对未声明判据或无对应事实一律返回 `None`，**绝不默认 `True`**；`observe` 的 `facts` 由调用方注入，组件内零 IO。
  - `settle` 是**唯一**改 `GoalStatus` 的入口，必经 `goal_repository.set_status` / `finish_goal` 并调 `goal_arbitration.record_goal_lifecycle`；计划推进审计落 `decision_records`，**复用既有 `kind='goal_lifecycle'` + 差异化 `decision` 值，不新增 kind**（新增 kind 需改 CHECK = 需迁移，违反红线）。
- **`app/services/planning/revision.py`**：`should_replan` / `policy_for` / `explain` 纯函数策略（对应 architecture §3.9、§6.6、§8.5）。
  - **四条重规划触发判据**：`step_attempt_exhausted`（达 Plan 层尝试上限且 `on_failure=replan`）/ `tool_persistently_unavailable`（连续 N tick `off_surface`，换工具重规划）/ `criteria_undecidable`（`evaluate_criteria` 连续返回 `None`）/ `insight_driven`（Reflection Insight 达门槛，见 PLAN-010）。
  - 修订预算与终止：版本数受 `v25_plan_revision_budget` 约束；达上限后计划置 `rejected`（`rejection_reason` 记原因），目标转 `failed("plan_exhausted")` 或交 `goal_arbitration.check_abandonment` 裁决放弃。**避免「无限重规划」是本模块存在的首要理由**——既有 `_LLM_RETRY_ATTEMPTS` 只管 LLM 调用失败，管不了「计划本身行不通」。
  - **保留已完成步骤策略**：`kept_steps = [s.index for s in plan.steps if s.status == "done"]`，新版本复用同 `index` / 同 `criteria`，不重做、不重复副作用（对应 architecture §6.6 ②）——版本号进 `dedupe_key` 会使幂等键改变，若不保留已完成步骤，重规划会把已产生世界副作用的步骤再做一遍。
- **双层重试对齐（B5 关闭点）**：Action 层 `action_retry_max_attempts`（2）/ `action_retry_backoff_seconds`（30）回答「是不是网络抖了一下」；Plan 层 `v25_plan_step_max_attempts`（默认 2）回答「这个做法是不是不行了」；**退避数学只有一份（在 Action 层）**，Plan 层不等待、不退避，只在 Action 落终态后做一次裁决（对应 architecture §3.7 双层表、§5.5）。
- **失败处理完整判定树**（对应 architecture §6.5）：`blocked` 四类各有处置（`permission_denied` 不重试、`invalid_params` 转 permanent、`pending_confirmation` 等既有确认流、`capability_unavailable` 等下一 tick 复面并计入 `off_surface`）；`on_failure` 四值（`abort` / `skip` / `replan` / `continue`）的后继状态矩阵逐条落地（对应 architecture §5.3 矩阵）。
- 挂载：`life_loop._step_goal_advance` 内部改走 `PlanObserver.collect_facts` + `observe`，**不改签名**；计划阶段以子步骤记入 `loop_runs.steps`（`plan_execute` / `plan_observe`），受既有 `budget_state` 约束（对应 architecture §7.8）。
- 对应 architecture §3.6、§3.7、§3.8、§3.9、§5.3、§5.5、§5.6、§6.4、§6.5、§6.6、§7.8、§8.4、§8.5。

Dependencies: PLAN-004

Acceptance Criteria:

- **搬运等价性测试**：`PlanScheduler` 公开函数与 `goal_observation` 私有实现对同一 plan（含深层嵌套与 `depends_on` DAG 用例）输出逐条一致。
- 拓扑序与 `ready_steps` 确定性（同输入同输出，可复现锚点）；`blocked_reason` 覆盖 `off_surface` / 冷却中 / 前置失败三类。
- `on_failure` 四值 × 后继状态矩阵逐条测试，与 §5.3 矩阵完全一致（含 `skip` 只影响直接后继、`continue` 显式放宽 `depends_on`、`replan` 暂停后继、`abort` 全置 `failed`）。
- 步级 `dedupe_key = plan:{goal_id}:{version}:{index}` 唯一且可复现；`to_intent` 不产出空 `action_type`。
- **执行唯一入口断言**：步骤执行只经 `action_engine.run_action_planning`；静态断言 `services/planning/` 零直调 `ToolExecutor.run` / `Capability.execute`（G-EXEC）。
- `pending_confirmation` 步骤经既有 `run_confirmation_round` 三条路径端到端通过：用户批准续跑（参数与幂等键复用原调用）/ 用户否定转 `failed` / TTL 过期转 `failed`。
- **`attempt_count` 时机断言**：只在 Action 终态（`succeeded` / `failed`）递增；`executing` / `planned` 中间态不递增（用例）。
- **零退避断言**：Plan 层无退避实现、无等待（静态与运行时断言），退避数学调用点唯一在 Action 层。
- `fact_source="tool"` 的 `action_succeeded` 与 `field_equals` 各有端到端用例；不可判定一律返回 `None`（绝不默认 True 断言）。
- **单一写面断言**：终态结算必经 `goal_repository.set_status` 且调 `goal_arbitration.record_goal_lifecycle`；`decision_records.kind` 仍为五值；计划推进审计可从 `decision_records` 正确投影。
- **保留步不重做断言（G-RETRY）**：重规划后已完成步骤的 `tool_id` / `criteria` / `index` 不变，且 `deferred_world_op` 计数不增加（使用 `action_repository` 落库计数验证，确认未产生重复世界副作用）。
- 修订预算达上限的终止路径可判定：计划置 `rejected` + 目标 `failed("plan_exhausted")`，且不再产生新版本。
- `goal_plans.sub_goals` 落库形状快照测试通过；零新表、零新列。
- 观测故障隔离：`error` 只 log、计划状态不变（用例）。
- Flag off 时 `CRITERION_FACT_SOURCES` 仍为三值、`fact_source="tool"` 判据一律 `None`，`goal_observation` / `goal_execution` 原路径生效，行为与 V2.4.0 逐字节一致。

---

## PLAN-006 Tool System Integration

Priority: P0

Goal: 钉死 Planning → Action → Tool 的执行契约：步骤的工具绑定必须经 `ToolRegistry.resolve` 与 `ToolSurface` 投影裁决，执行必须经 `action_engine` 六闸门与 `ToolExecutor` 五段短路——**规划层不得新增任何工具选择逻辑，不得绕过任何治理闸**。

Description:

- **规划期工具面接线（B3 / B4 关闭点的运行时面）**：闸门 5 校验 `ToolRegistry.resolve(tool_id)` 可解析；闸门 6 校验 `tool_id ∈ ctx.tool_surface.tool_ids`（对应 architecture §3.4、§7.7）。
  - 熔断工具经 `tool_status:tripped` 被工具面剔除 → 闸门 6 自动拒；`TOOL_UNAVAILABLE_TOOL_IDS`（如 `builtin.search.query` 恒 `unavailable`）与通道未启用时的 `disabled`（如 `channel.feishu.send`）不会进入计划。
  - 工具面按 `RUN_KIND_AUTONOMOUS_TICK` 装配，复用既有 `build_tool_context(base, settings, now)` 的八段装配与逐段降级（对应 architecture §6.3）。
- **执行期治理不绕过**：`action_engine.run_action_planning` 六闸门（`disabled` / `ambiguous_params` / `capability_unavailable` / `duplicate` / `quota_exceeded` / `effect_already_satisfied`）+ `planner.assemble_plan`（v24 总闸 on → `_assemble_plan_via_tools` → `ToolSurface` → `ToolSelector`）+ `ToolExecutor.run` 五段短路（resolve → permission → validate → invoke → normalize）（对应 architecture §3.7 执行链、§7.7）。
- **关键裁决：Planning 不新增任何工具相关的选择逻辑**。规划期的「选哪个工具」是**绑定**（`TaskDecomposer`，确定性，一能力多工具时按 `ToolSelector` 的确定性规则）；执行期的「选哪个工具」是**决策**（`ToolSelector` 在真实 intent 与真实面上）。二者用同一套规则、同一个函数，因此不会产生分歧（对应 architecture §7.7 关键裁决）。
- **校验分层**：步骤参数在规划期只做**弱校验**（必填齐备），强校验（结构 + 语义）留给执行期 `ParamValidator.validate`（唯一权威）；规划期弱校验不过的步骤在规划期即被拒（对应 architecture §7.7 校验行）。
- **授权分层**：步骤遇 `confirm_required` 时等既有确认流（`app/services/tool/confirmation.py` + `action_engine.run_confirmation_round`），**不得自动绕过**；`permission_denied` 属授权拒绝非瞬时，不重试（对应 architecture §7.7 授权行、§6.5）。
- **扩展工具一视同仁**：`ext.api.*` / `user.*` 命名空间工具只要在面上且可解析即可被规划，不设特判（对应 architecture §7.7 扩展行）。
- **结果契约**：`ToolResult{status, effects, observations, failure_kind, usage}` 归一为 `PlanStepOutcome`；`effects` 进判据事实源；`failure_kind` 取值即既有 `TOOL_FAILURE_KINDS`（6 值），**不新增**（对应 architecture §7.7 结果行、§4.5）。
- 对应 architecture §3.4（闸门 5/6）、§3.7（执行链）、§6.3（工具面装配）、§7.7、§7.9（Action / Tool 契约行）。

Dependencies: PLAN-005

Acceptance Criteria:

- **链路断言**：一次步骤执行完整经过六闸门与五段短路（每段可观测），且任一前置段失败路径**零外部调用**（打桩断言，含 DB 写与网络）。
- **G-EXEC**：静态扫描断言 `app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute`。
- 闸门 5/6 各有工具状态用例，四类工具均不进计划：`disabled` / 恒 `unavailable` / 熔断 `tripped` / 被日时段或 Run Profile 剔除（如 `channel.*` 在 `late_night`）；其中「闸门 5 过、闸门 6 拒」**必须单列用例**，且断言计划步数与内容不变、仅该步暂不装配。
- 一能力多工具时，规划期绑定结果与执行期 `ToolSelector` 选择结果一致（同函数同规则，用例对照）。
- `confirm_required` 步骤**零外部调用**（打桩断言）且经既有确认流恢复；规划期弱校验不过的步骤在规划期即被拒（不进入执行）。
- 工具面投影的八维裁剪理由逐条可解释，每条 `excluded` 携带 reason；`surface_hash` 同输入同输出。
- 扩展命名空间工具（`ext.api.*` / `user.*`）在面上且可解析时可被规划（用例）。
- `PlanStepOutcome.failure_kind` 取值全部落在既有 `TOOL_FAILURE_KINDS`（6 值）内；`ActionStatus` 与 `GATE_REASONS` 值集未扩（对应 architecture §5.6）。
- V2.4.0 工具侧既有测试零失败（注册表 / 面投影 / 选择器 / 执行器 / 健康度 / 确认流契约未被改动）。
- Flag off 时工具面不参与规划（`SubGoalSpec.tool_id` 不写），绑定只在执行期由 `ToolSelector` 发生，行为与 V2.4.0 逐字节一致。

---

## PLAN-007 Autonomy Integration

Priority: P1

Goal: 让自治策略感知计划事实，并让计划推进意图经既有候选面进入决策——**Autonomy 决定「此刻做什么」/ Planning 决定「怎么做」/ Tool 负责执行**，三者串联且职责不重叠。

Description:

- **计划事实进策略快照（B9 关闭点）**：`PolicySnapshot`（`app/services/autonomy_policy.py`）在既有 `world_facts` / `action_facts` / `tool_facts` / `tool_insights` 四段之外新增**有界第五段** `plan_facts`：`active_goal_id` / `plan_version` / `current_step` / `steps_total` / `blocked_steps` / `last_advanced_at`；由既有行动事实收集同源扩展、一处装配；装配失败降级为空包，**不阻塞 tick**（与 `tool_facts` 同款纪律）（对应 architecture §7.3 接线 1）。
  - 用途：自治策略避免「在计划正在推进时抢同一动作」导致额度被重复消耗。
- **计划态参与决策候选**：计划推进产生的意图经**既有 `goal_compile` 候选面**进入 `decision_pipeline.collect_candidates`（`goal_compile` 优先级 P2 原样保留）；**不新增候选源、不改 `_SOURCE_PRIORITY` 数学、不改六维权重**。这样计划的「该做下一步了」与自治的「要不要主动」在同一张评分表上竞争（对应 architecture §7.3 接线 2）。
- **额度不绕过（评审红线）**：计划触发的执行仍走 `action_engine.run_action_planning(source="autonomy")`，因此 `action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` 与冷却窗口原样生效；**计划不得成为绕过额度的后门**（对应 architecture §7.3 接线 3）。
- **明确不做四条**：不新建自治执行器（`autonomy_engine._produce_autonomy_action` 原样复用）；不让 Planning 决定「该不该主动」（那是 `autonomy_policy` 八步裁决的独占职责）；不让 Autonomy 决定步骤顺序（那是 `PlanScheduler` 的独占职责）；不新建 LLM 决策循环（规划沿用既有 `v2_autonomy_planning_llm_profile`，`llm_gateway` 预算不变）（对应 architecture §7.3 不做什么）。
- **`autonomy_engine.tick` 二十步序列零改动**（`plan_facts` 由 `_collect_action_facts` 同源扩展，一处装配）（对应 architecture §7.8）。
- 三者分工对照表（问题 / 权威函数 / 输入契约 / 输出契约 / 决策粒度 / 触发频度 / 额度与预算 / 不做什么）作为职责不重叠的举证清单（对应 architecture §7.3 对照表）。
- 对应 architecture §7.3、§7.8、§7.9（Autonomy 契约行）。

Dependencies: PLAN-005, PLAN-006

Acceptance Criteria:

- 自治 tick 的 `plan_facts` 有界（受既有可观测预算约束）且各字段可追溯；装配失败降级为空包且**不阻塞 tick**（用例）。
- **额度与冷却未放宽**：`action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` / 冷却窗口的生效用例通过；负例：额度耗尽时计划步骤不执行、不产生 `ActionRecord`。
- 六维权重数学与候选优先级表未改（快照对照零差异）；未新增候选源；计划推进意图确实经 `goal_compile` 面进入。
- `autonomy_engine.tick` 步数与顺序不变（形状快照对照）；`_produce_autonomy_action` 形态未变。
- **G-BOUNDARY 输出契约断言**：Autonomy 只出 `AutonomyVerdict` + intention、Planning 只出 `GoalPlanRecord` + `PlanStepSpec[]`、Tool 只出 `ToolResult`（各自静态与运行时断言）；三者无交叉写面。
- 行为差异只在 Flag on 时出现；Flag off 时 `PolicySnapshot.plan_facts` 不存在（`{}` 原状），与 V2.4.0 逐字节一致。

---

## PLAN-008 World Simulation Integration

Priority: P1

Goal: 钉死计划与世界的读写契约：**世界事实只经预读注入规划**，**计划永不直接修改世界状态**（写入一律经 `deferred_world_op` → outbox → `world_engine`），计划终态经既有 `event_bridge` 广播。

Description:

- **反向（World → Plan）预读装配**：九类世界事实进 `PlanContext`——时间 / 日时段（`world_engine.build_time_context`）、天气环境（`collect_facts`）、地点与可用动作（`get_location_context`）、库存与附近物（`get_objects_by_location`）、显著事件（`list_active_events` + `event_impact.evaluate_batch`，其 `goal_opportunity` 为规划素材）、用户处境（`world_simulation_repository.get_active_situation`）、场景画像（`scene_profiles.scene_profile_for`）、世界简报（`world_brief.build_world_brief`，≤ `world_brief_char_budget`）、`WorldContext` 完整切片（对应 architecture §3.3 六源之 World、§7.4 反向表）。全部逐段可降级。
- **正向（Plan → World）三条合法路径**（对应 architecture §7.4 正向表）：
  - **只读世界**：如「查天气」步骤直调 `world_engine.get_*`（无副作用）。
  - **延迟写世界**：如创建提醒的步骤产出 `deferred_world_op={op:"create_event", args:[...]}` → `action_repository.save_record_with_outbox`（幂等键 = `record.id`，同一事务）→ `outbox_consumer._apply_world_op` → `world_engine.create_event`。
  - **提交世界意图**：`services/tool/world_intent.py::WorldIntentSubmitter`（TOOL-007 冻结形状）**本版本仍不接线**（`WIRED=False`）。
  - 合法世界操作白名单（均出自 `world_engine`）：`create_event` / `cancel_events_by_type` / `create_object` / `move_object` / `apply_object_action` / `set_environment` / `set_location`。
- **Character 域边界铁律**：`character_goals` 仅经 `goal_repository.set_status` / `finish_goal` 改状态；`character_state` / `personality_state` / `relationship_state` / `relationship_events` 一律不可写（关系域效果只经既有工具 `effects(kind=relationship)` → `relationship_bridge`）；`worlds` / `world_entities` / `world_events` 一律不可直写（对应 architecture §7.4 边界表）。
- **Event System 集成**：计划达成（`outcome="completed"`）与计划放弃（`outcome="abandoned"`）经 `event_bridge.register_goal_event` 广播为 `world_events`（`EventSource.CHARACTER`）；**计划修订不广播**（内部结构变化，非世界事件）；**不新增 `world_events.type`**，复用既有 `goal_completed`，从而自动获得既有重要事件升级链路 `trigger_router.evaluate_event_escalation`（对应 architecture §7.4 事件表）。
- **静态扫描护栏**：`app/services/planning/` 零 `world_repository` 导入；计划层禁止 import `world_repository`、禁止写 Character 域（对应 architecture §2.3 红线 5、§7.1）。
- 遗留问题 Q9（计划完成是否应同时产生关系域信号）在本任务内记录，涉及 `relationship_*` 写入面扩张，需与 V8.5 / V2.2 一并评估，接线推后续版本；Q5（`WorldIntentSubmitter` 接线）在本任务内记录评估结论（对应 architecture §9.7 Q5、Q9）。
- 对应 architecture §7.4、§6.7（⑨ 世界广播）、§2.3（红线 5）、§7.1 集成总则、§9.7 Q5 / Q9。

Dependencies: PLAN-005, PLAN-006

Acceptance Criteria:

- **G-WORLD 静态扫描断言**：`app/services/planning/` 零 `world_repository` 导入；零 `character_state` / `personality_state` / `relationship_*` 写入。
- 计划写世界**全部**经 outbox；消费幂等与崩溃重放续走行为与 V9 一致；`outbox_consumer._apply_world_op` 幂等键机制未改。
- 终态广播落 `world_events`（`source=character`）且可被既有升级链路（`trigger_router.evaluate_event_escalation`）消费；`world_events.type` 值域未扩。
- 九类世界事实可进 `PlanContext` 且逐段可降级；`world_enabled=False` 时为空包且 `degraded` 含 `world_disabled`。
- 世界操作白名单外无调用路径（负例：非白名单 op 被拒）。
- `WorldIntentSubmitter` 仍为 `WIRED=False`（未接线断言），冻结形状的 schema 测试通过。
- 关系域效果只经工具 `effects(kind=relationship)` → `relationship_bridge` 通道（零直写断言）。
- V2.3.0 / V8 世界侧既有测试零失败（世界唯一写面与事件唯一事实源未被触碰）。
- 计划修订不产生任何 `world_events`（负例断言）。
- Flag off 时世界侧行为与 V2.4.0 逐字节一致。

---

## PLAN-009 Memory Integration

Priority: P1

Goal: 交付计划结果的**记忆分层判据**：计划本体与中间步骤不进 `memories`，只有「计划终态」这类事件性事实进候选，且 `memory_policy` R1~R8 **零豁免**。

Description:

- 新建 `app/services/planning/memory_policy.py`：`PlanMemoryPolicy` 纯数据资产，形态对齐 `services/tool/memory_policy.py`（对应 architecture §7.5.2 边界表）。
  - 计划完成（全部步骤 `done`）→ deposit ✅ `important_event` / `importance 0.7` / `source user_derived`。
  - 计划失败（达预算 / `on_failure=abort`）、计划被放弃（`abandonment` 双信号）→ deposit ✅ `important_event` / `importance ≥ 0.6`，内容带未完成语义（与 V9 失败纪律一致）。
  - 计划创建 / 计划修订 / 单个步骤成功（中间态）/ 单个步骤失败（未达 Plan 层上限）→ deposit ❌。
  - 涉及用户隐私的步骤参数 → 经 `memory_policy` R3（`action="forget"` 分支）转隐私执行。
  - **易错点**：`ai_inferred` 会被 R1 直接丢弃（「AI 推测不入库」），因此失败 / 放弃类沉淀必须走加权重路径——提升 `importance` 并把 `source` 定为 `user_derived`（内容锚定在用户委托的目标描述上），或复用既有 `ingest_from_goal_completion`（其 `source` 取自目标本身）（对应 architecture §7.5.2 ※ 提醒、§9.6 G-MEMORY）。
- **判据 A（计划本体是否落 `goal_plans`）**：三条条件全满足才落计划（步骤数 ≥ 2 或需跨 tick 观测；每步有独立达成判据；需要幂等/重试/失败恢复），任一不满足走 action 直通；五类场景裁决（单步当场可验 → 不落；多步跨天 → 落；单步但需跨天确认送达 → 不落；需先查再定的两步 → 落；纯查询 → 不落）（对应 architecture §7.5.1）。
- **判据 C（步骤级沉淀）**：中间步骤是否沉淀**不由 Planning 决定**，而是由该步调用的工具按 V2.4.0 `TOOL_MEMORY_TEMPLATES` 与 `services/tool/memory_policy.py` 决定（`builtin.reminder.create` 沉淀 / `world.env.query` 强制不沉淀 / `builtin.memory.save` skip）；两层判据正交：Planning 判「计划整体值不值得记住」，Tool 判「这次调用值不值得记住」（对应 architecture §7.5.3）。
- **记忆通道零新建**：分类 → 优先复用 `memory2.ingest.ingest_from_goal_completion(user_id, goal_id, description)` 构造候选（按计划终态调整 `importance` / `content` 模板）→ `memory_policy.apply_policy([candidate], active_contents)` R1~R8 → `memories`（既有表，零新列）→ `effects` 登记 `kind=memory` 做重复投递检测（既有 `has_memory_effect` 泛化）；未通过政策闸 → 丢弃，**不回滚计划执行**（与 V9 同款纪律）（对应 architecture §7.5.5）。
- 对应 architecture §7.5（§7.5.1 ~ §7.5.5）、§6.2 ⑦、§6.7 ⑩、§9.6 G-MEMORY。

Dependencies: PLAN-005, PLAN-006

Acceptance Criteria:

- **零写入断言**：计划本体与中间步骤零写入 `memories`；计划创建 / 计划修订 / 单步成功 / 单步失败（未达上限）四类事件均不沉淀。
- 计划完成 / 失败 / 放弃三类终态各沉淀一条，且内容语义正确（失败与放弃类带未完成语义）。
- **R1 不误杀断言（G-MEMORY）**：失败 / 放弃类候选的 `source` 与 `importance` 能通过 `memory_policy` R1；若被 R1 丢弃则用例失败。
- **R1~R8 零豁免**：全部候选经 `memory_policy.apply_policy`，无旁路写库（静态与运行时断言）。
- 工具侧 deposit 决策**不被覆盖**：`builtin.reminder.create` 步骤成功仍按 V2.4.0 边界表沉淀一条；`world.env.query` 仍强制不沉淀（即使配置为沉淀）；`builtin.memory.save` 仍 skip（避免二次投递）。
- 幂等：同一次执行重复投递不产生第二条记忆（`has_memory_effect` 泛化生效）。
- 判据 A 的三条条件与五类场景裁决各有用例，边界场景（单步但需跨天确认送达 → 不落计划）可判定。
- `memories` 表结构零变更、零迁移；Flag off 时记忆通道走既有原路径（逐字节一致）。

---

## PLAN-010 Reflection Integration

Priority: P1

Goal: 建立「执行结果 → 反思 → 计划优化」闭环：计划执行结果进证据窗，达门槛的 Insight 只投一个幂等的重规划触发；**反思分析计划效能，但不改写计划**。

Description:

- **扩一路证据通道**：在 `app/services/reflection/evidence.py` 的既有 `EVIDENCE_CHANNEL_MEMORY` / `EVIDENCE_CHANNEL_TOOL` 之外新增 `EVIDENCE_CHANNEL_PLAN = "plan"`；窗口分组键沿用既有 `GROUP_KIND_*` 范式（按 `plan_kind` / `step_kind` / `failure_kind`），证据 id 沿用既有形态 `plan:<goal_id>:<version>:<step_index>`（对应 architecture §7.6 ①）。
- **三个计划证据窗（B6 关闭点）**（对应 architecture §7.6 表）：
  - **计划成功率**：`goal_plans` 按 `status` × `goal.type` 聚合 → Insight 类型 `capability_note`（例：「面试类计划 4 步做不完，实际两步就够」）。
  - **步骤失败模式**：`action_records.steps` 按 `tool_id` × `failure_kind` 聚合 → `capability_note` / `usage_preference`（例：「查天气这一步总是超时，先别排它」）。
  - **判据可判定性**：`goal_plans.sub_goals` 中 `criteria_result=None` 的步占比 → `pattern`（例：「我给自己定的判据太虚，常判不出来」）。
  - 门槛复用既有 `passes_gate`（`evidence_count` / `span` / `coherence`）或 `passes_tool_gate`（`samples` / `failures` / `span`）；`v25_plan_reflection_min_samples`（默认 3）对齐 `v2_reflection_min_evidence`。
- **三道闸零豁免**：证据门槛（`passes_gate`）+ 当日额度（`_quota_used`）+ 幂等入队（`background_job_repository.has_job(idempotency_key)`），完全复用既有 `trigger_for_user`（对应 architecture §7.6 ②）。
- **交付 `app/services/planning/revision_listener.py`**：`PlanningRevisionListener.on_insight_created` **注册进既有 `reflection_lifecycle.notify_insight_created_listeners`**——这是本版本**唯一**的 Planning 侧反思接线（既有消费者只有 `development/policy.py` / `relationship_narrative.py` / `world/event_bridge.py` 三处）（对应 architecture §7.6 ④）。
  - **门槛一**：`insight.type ∈ PLAN_INFLUENCE_INSIGHT_TYPES`（默认 `capability_note` / `pattern`）。
  - **门槛二**：`insight.confidence ≥ v25_plan_replan_min_confidence`（默认 0.7）。
  - **门槛三**：存在可映射的 active 目标（按 `scope` 与目标 `domain` / `layer` 匹配）。
  - **幂等键**：`plan_replan:{goal_id}:{insight_id}`。
  - **唯一动作**：`goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)`。
  - **✗ 不允许**：直接改 `plan.sub_goals`、直接改 `GoalStatus`、直接写 `goal_plans`。
- **新规划轮次携带证据**：`PlanContext.evidence_refs = [insight_id, ...]` → 进 prompt 与 `GoalPlanRecord.evidence_refs`，即「我上一次这么做没成，这次换个做法」的闭环（对应 architecture §7.6 ⑥）。
- **Reflection 不做的事五条**：不直接改写 `sub_goals` / `GoalPlanStatus`；不因计划失败产出「性格类」Insight；不绕过三道闸（计划证据与用户证据走完全相同闸门）；不直接终止计划、不自动把工具下线（健康度与运维另有通道）；不在 `foreground` 关键路径里做计划反思（仍在 `memory_extract` 步与后台节拍里）（对应 architecture §7.6 明确边界）。
- 遗留问题 Q8（`insight_driven` 与其余三条重规划判据的优先关系）在本任务内裁决，须保证同时命中时只产生**一个**重规划触发（对应 architecture §9.7 Q8）。
- 对应 architecture §7.5.4、§7.6、§6.1 ⑦、§8.6（PlanningRevisionListener）、§9.6 G-REFLECT、§9.7 Q8。

Dependencies: PLAN-005

Acceptance Criteria:

- 三个计划证据窗各有场景用例（成功率 / 失败模式 / 判据可判定性）；证据不足时**不产 Insight**（零 LLM 断言）。
- 计划证据与用户证据走**完全相同**的三道闸（零豁免）；当日额度与幂等入队行为不变。
- **隔离断言（G-REFLECT）**：`on_insight_created` 不改变任何 `GoalPlanRecord` / `GoalStatus` / 工具注册表状态。
- 幂等键 `plan_replan:{goal_id}:{insight_id}` 重复触发只入队一次；`insight_driven` 与其他三条判据同时命中时只产生**一个**重规划触发（Q8 裁决落地用例）。
- 三道门槛各有负例：类型不在 `PLAN_INFLUENCE_INSIGHT_TYPES` / 置信度低于 `v25_plan_replan_min_confidence` / 无可映射 active 目标 → 均不触发。
- 重规划轮次的 `evidence_refs` 正确落 `GoalPlanRecord.evidence_refs` 并注入 prompt（可判定用例）。
- 不产出「性格类」Insight（计划失败不改变人格）；不在 `foreground` 关键路径做计划反思（阶段位置断言）。
- 监听器注册不改变既有三个消费者的行为（回归对照）。
- Flag off 时证据聚合只有 `memory` 与 `tool` 两通道、无 `planning/revision_listener`，行为与 V2.4.0 逐字节一致。

---

## PLAN-011 Planning API / Interface

Priority: P1

Goal: 冻结并验证 Planning 的**内部接口契约**（Planning Service / Plan Executor / Goal Service），交付 `goal_repository` 只读扩展与计划可观测面（审计投影 + 管理面调试端点）。

Description:

- **内部接口契约冻结与一致性验证**（对应 architecture §8.1 ~ §8.6）：
  - `PlanningEngine`：`plan` / `revise` / `enqueue` / `run_jobs` / `register_runtime`（由 PLAN-003 交付，本任务冻结签名并做契约对照）。
  - `PlanContextAssembler` + `PlanContextProbe`：`assemble` / `world_available` / `surface_size` / `degraded_sources`（由 PLAN-003 交付）。
  - `PlanRepository`：**扩展既有 `goal_repository`，不新建仓储模块**（对应 architecture §8.3）。
  - `PlanScheduler` / `PlanExecutorBridge`：`order` / `ready_steps` / `current_step` / `all_done` / `has_executable` / `blocked_reason`；`to_intent` / `execute_step` / `reconcile`（由 PLAN-005 交付）。
  - `PlanObserver` / `PlanRevisionPolicy`：`collect_facts` / `observe` / `evaluate` / `settle`；`should_replan` / `policy_for` / `explain`（由 PLAN-005 交付）。
  - `PlanValidator` / `PlanningRevisionListener`：`validate_shape` / `validate_binding` / `validate_budget`；`on_insight_created` / `enqueue_replan`（由 PLAN-004 / PLAN-010 交付）。
- **`goal_repository` 只读扩展三项**：`list_plans_by_status(user_id, statuses)` / `count_plan_versions(goal_id)` / `list_terminal_plans_since(user_id, since)`（后者供计划证据窗投影，PLAN-010 消费）；既有 `create_plan` / `get_plan` / `get_latest_plan` / `list_plans` / `count_plans` / `set_plan_status` / `set_plan_rejection` / `update_plan_progress` / `list_active_plans` **零改动**。
- **计划审计与运行态投影**：`PlanAdvance` 落 `decision_records`（复用既有 `kind='goal_lifecycle'` + 差异化 `decision` 值，**不新增 kind**）；计划阶段子步骤记入 `loop_runs.steps`（`plan_assemble` / `plan_execute` / `plan_observe`），受既有 `budget_state` 约束（对应 architecture §4.6、§4.9、§7.8）。
- **管理面调试端点**：沿用既有 `app/api/v1/debug.py` 风格（与 V2.3.0 world debug 面板、V2.4.0 tools 面板同构）扩 6 个端点——计划清单 / 单计划详情（步骤 + 绑定 + 判据 + 推进历史）/ 步骤视图（含 `tool_id` 绑定与 `blocked_reason`）/ `PlanContext` 装配结果（六源 + `degraded` 清单）/ 修订链（from-to version + reason + evidence_refs）/ 待推进步骤（含 `off_surface` 与冷却中原因）。全部受 `v25_planning_enabled` + `v25_plan_debug_enabled` + 调试总闸门控，Flag off 时端点不可见（对应 architecture §8.7）。
- **本任务子项（可延后，P2 语义）**：6 个调试端点与前端视图的落地。此子项即 architecture §9.2 中唯一标注为 P2 的交付面，不阻断其余验收条目。
- 遗留问题 Q10（计划可观测面是否纳入 `apps/frontend/` 调试控制台）在本任务内记录，不在本版本实现（对应 architecture §9.7 Q10）。
- 对应 architecture §8.1 ~ §8.7、§4.6、§4.9、§7.8、§7.9、§9.7 Q10。

Dependencies: PLAN-005, PLAN-006

Acceptance Criteria:

- 六个模块的公开接口与 §8.1 ~ §8.6 签名逐条一致（契约对照）；任何签名漂移即用例失败。
- `goal_repository` 既有九个计划函数零改动（差异对照为空）；新增三个只读函数有测试且**零写库**（打桩断言）。
- 计划推进审计可从 `decision_records`（`kind='goal_lifecycle'`）正确投影 `PlanAdvance`；`decision_records.kind` 仍为五值（零新增 CHECK 值）。
- 修订链可从 `goal_plans` + `decision_records` 正确重建：`from_version` / `to_version` / `reason` / `trigger_source` / `evidence_refs` / `kept_steps` 逐条可读。
- `loop_runs.steps` 中计划子步骤（`plan_assemble` / `plan_execute` / `plan_observe`）记账正确且受既有 `budget_state` 约束；`life_loop` 九步阶段序列不变。
- 六个调试端点全部受总闸 + 调试子闸门控；Flag off 时端点不可见；`PlanContext` 投影含六源与 `degraded` 清单；步骤视图含 `tool_id` 绑定与 `blocked_reason`。
- **零新建表断言**：计划可观测面全部投影自 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表。
- 内部接口契约的"只读 / 零 IO / 纯函数"三条纪律各有静态断言（`PlanScheduler` / `PlanValidator` / `PlanRevisionPolicy` 为纯函数；`PlanObserver` 的 `facts` 由调用方注入）。

---

## PLAN-012 Testing & Validation

Priority: P0

Goal: 交付版本级验收：四类端到端场景集（单目标规划 / 多步骤规划 / Tool 调用流程 / 失败恢复）、Flag 矩阵一致性测试、`regression-checklist.md`，以及 architecture §9.6 全部 Gate 的可执行判定与 §9.7 遗留问题收口。

Description:

- **四类端到端场景集**（对应 architecture §6.1、§6.2、§6.4、§6.5、§6.6）：
  - **单目标规划**：任一 active Goal 产出 `GoalPlanRecord`，每步有明确 `tool_id` 绑定与达成判据；同时覆盖判据 A 的两侧（落计划 / 走 action 直通）。
  - **多步骤规划**：architecture §6.2 的四步「面试准备」样例全链可复现——目标成熟 → 六源装配 → 拆解（4 Task + 工具绑定）→ 逐 tick 单步执行（受 cooldown 节流）→ 观测推进 → 终态广播 → 记忆沉淀 → 反思回环。
  - **Tool 调用流程**：`PlanStep → ActionIntent → 六闸门 → assemble_plan → ToolExecutor 五段短路 → ToolResult 归一为 PlanStepOutcome` 全链可追溯（Run 台账 / 决策记录 / 行动记录三账对齐）。
  - **失败恢复**：§6.5 判定树全覆盖（`blocked` 四类 + `failed` / `timeout` + 观测 `error`）；§5.5 双层重试（Action 退避 / Plan 放弃）；§6.6 重规划五步（预算检查 → 保留与丢弃 → 新版本生成 → 落库与切换 → 审计）。
- **Flag 矩阵一致性测试**：13 个 `v25_*` Flag 的组合矩阵与 §7.10 串行链校验逐条对照；总闸 off 时逐字节一致（prompt + 行为快照 + 维护步骤序列）。
- **交付 `docs/version/v2.5.0/planning-system/regression-checklist.md`**。
- **§9.6 全部 Gate 的可执行判定**：G-COMPAT / G-PLAN / G-DECOMPOSE / G-BIND / G-EXEC / G-RETRY / G-WORLD / G-MEMORY / G-REFLECT / G-BOUNDARY / G-ZERO-MIGRATION。（architecture §9.2 与标题表述为「十个 Gate」，而 §9.6 表实际列出 11 条；**以 §9.6 表列为准**，差异在验收记录中留痕。）
- **§9.7 遗留问题收口**：Q1（多步并行编排不在本版本，`action_plan_max_steps` 保持 1）/ Q2 / Q3（PLAN-002 内裁决并补双向兼容测试）/ Q4（PLAN-004 内冻结）/ Q5（PLAN-008 内记录，仍 `WIRED=False`）/ Q6（PLAN-003 内记录，压测后决定）/ Q7（计划与 `daily_plans` 互不引用）/ Q8（PLAN-010 内裁决）/ Q9（PLAN-008 内记录）/ Q10（PLAN-011 内记录）逐条核对留痕，无悬空项。
- **零迁移断言**：全版本不新增任何表、列、索引与 CHECK 值；迁移链保持 0046；若实现阶段出现建表 / 建列需求，说明设计已被违背，须回退重审 §3.1 与 §4.1 两条裁决并留痕（对应 architecture §4.9、§7.11）。
- **兼容窗口兑现**：V2.4.0 承诺「V9 既有读键保留到 V2.5.0」——本版本继续双写 `world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`；正式退役窗口推到 V2.6.0 并在 V2.6.0 文档中显式登记（对应 architecture §7.11）。
- **边界不变量核对**：§2.3 十条红线逐条核对，尤其红线 1（零新建表/迁移）、2（不新建 Goal 系统）、3（不放开 `action_plan_max_steps`）、5（不直接写世界/Character 域）、6（不绕过记忆政策）、7（反思不直接改写计划）、10（Flag 全 off 与 V2.4.0 逐字节一致）。
- 对应 architecture §9.6、§9.7、§2.3、§6.1 ~ §6.6、§7.10、§7.11。

Dependencies: PLAN-001 ~ PLAN-011

Acceptance Criteria:

- 四类端到端场景全部通过，且 §6.2 的四步计划样例全链可复现（含跨 tick 单步推进与 cooldown 节流）。
- Flag 全 off 时与 V2.4.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）；既有测试**零修改**通过。
- §9.6 全部 Gate 各有自动化或人工可判定条目，且全部可追溯到 §9.6 原文；「十个 Gate」与表列 11 条的表述差异在验收记录中留痕并以表列为准。
- **零迁移断言成立**：迁移链头仍为 0046；无新表 / 新列 / 新索引 / 新 CHECK 值；`ck_goal_plans_status` 五值、`ck_decision_records_kind` 五值未变；若出现建表 / 建列需求必须回退重审 §4.9 并留痕。
- **失败恢复全链可判定**：Action 层技术性退避重试与 Plan 层业务性放弃双层语义各有用例；重规划不重做已完成步骤、不产生重复世界副作用（`deferred_world_op` 计数验证）；「无限重规划」被 `v25_plan_revision_budget` 阻断（达上限后计划 `rejected` + 目标 `failed("plan_exhausted")`）。
- §9.7 十项遗留问题各有裁决结论或记录留痕，无悬空项。
- V9 旧读键（`world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`）双写断言通过，兼容窗口 ≥ 一个版本。
- 回归清单覆盖 §2.3 十条边界不变量与「零新建 Agent Core / Memory System / Event System / Tool System」复用声明。
- 计划对世界的写入路径与 V9 一致性（outbox 幂等 + 崩溃重放）在世界侧既有测试中零失败。

---

## 4. 里程碑

| 里程碑 | 含任务 | 出口判定 |
|---|---|---|
| **M1 规划地基** | 001, 002, 003, 004 | Goal 契约冻结、计划域值对象与 Flag 就位；计划可被生成、校验、绑定工具；Flag off 与 V2.4.0 逐字节一致 |
| **M2 执行闭环** | 005, 006 | 步骤可调度、可执行、可观测、可推进、可修订；双层重试语义对齐；工具治理不被绕过 |
| **M3 四系统集成** | 007, 008, 009, 010 | Autonomy / World / Memory / Reflection 四系统接线完成且各自验收通过 |
| **M4 接口与验收** | 011, 012 | 内部接口与可观测面就位；全部 Gate 全绿；零迁移断言成立 |

---

## 5. 遗留问题挂载

Architecture §9.7 登记十项，按任务归属挂载，**在对应任务内或任务启动前完成裁决**：

| # | 问题 | 挂载任务 | 裁决时点 |
|---|---|---|---|
| Q1 | 多步工具编排语义（并行步骤 / 部分失败回滚） | 不在本版本（`action_plan_max_steps` 保持 1） | 后续版本 |
| Q2 | `GoalPlanRecord` 新增字段（`trigger` / `context_digest` / `revision_of` / `evidence_refs`）落点 | PLAN-002 | 任务启动前裁决（加列会使零迁移断言失效，须回写 §4.9 并留痕） |
| Q3 | `SubGoalSpec` 的 Pydantic `extra` 策略 | PLAN-002 | 任务内裁决并补双向兼容测试 |
| Q4 | `fact_source="tool"` 与 `threshold_reached` 的组合语义 | PLAN-004 | 任务内冻结（当前裁决：拒绝，保持值集最小） |
| Q5 | `WorldIntentSubmitter`（`WIRED=False`）的接线 | PLAN-008 | 任务内记录（本版本仍不接线） |
| Q6 | `PlanContext` 装配的 LLM 成本与延迟 | PLAN-003 | **已记录并裁决（PLAN-003 §11.4）**：装配侧零 LLM、嵌入调用为既有 `retriever` 行为、周期步骤数不变 ⇒ 本版本**不新增** capability 位 / 预算位；若压测显示挤占再于 PLAN-011 / PLAN-012 追加并同步 architecture §7.8 |
| Q7 | 计划与 `daily_plans`（V2.3.0 日程）的语义收敛 | 不在本版本（互不引用） | 独立评估 |
| Q8 | Reflection Insight 与 `PlanRevisionPolicy` 优先级 | PLAN-010 | 任务内裁决（须保证只入队一次） |
| Q9 | 计划完成对 Character State 的间接影响路径 | PLAN-008 | 任务内记录（涉及关系域，需与 V8.5 / V2.2 一并评估） |
| Q10 | 计划可观测面是否纳入前端调试控制台 | PLAN-011 | 任务内记录 |

---

## 6. 与 Architecture §9 的追溯矩阵

Architecture §9.2 定义 14 项任务，本文档按推荐方向重组为 12 项，**交付面无遗漏、无越界**：

| Architecture §9.2 任务 | 本文档任务 | 说明 |
|---|---|---|
| PLAN-001 Plan Core Model & Settings | **PLAN-002** | 一一对应（编号顺延）；同时吸收 architecture §4.3 / §4.4 模型扩展与 §7.10 Flag 设计 |
| PLAN-002 PlanContextAssembler | **PLAN-003** | 并入引擎核心（装配与引擎同属"规划输入 → 规划输出"一段） |
| PLAN-003 PlanningEngine | **PLAN-003** | 与 PlanContextAssembler 合并交付 |
| PLAN-004 TaskDecomposer | **PLAN-004** | 一一对应 |
| PLAN-005 PlanScheduler | **PLAN-005** | 并入执行引擎（含架构 §9.4 要求的"先搬后改 + 等价性对照"） |
| PLAN-006 PlanExecutorBridge | **PLAN-005** | 并入执行引擎；工具治理契约部分归 PLAN-006 |
| PLAN-007 PlanObserver | **PLAN-005** | 并入执行引擎（判据四事实源与推进同属观测段） |
| PLAN-008 PlanRevision | **PLAN-005** | 并入执行引擎（重规划装配与保留步策略） |
| PLAN-009 Memory 集成 | **PLAN-009** | 一一对应 |
| PLAN-010 Reflection 集成 | **PLAN-010** | 一一对应 |
| PLAN-011 World 集成 | **PLAN-008** | 一一对应（编号调整，对齐用户指定的集成顺序） |
| PLAN-012 Autonomy 集成 | **PLAN-007** | 一一对应（编号调整，对齐用户指定的集成顺序） |
| PLAN-013 调试端点与管理面 | **PLAN-011** | 并入内部接口与管理面；该子项保留 architecture 的 P2（可延后）定级 |
| PLAN-014 系统验收与回归清单 | **PLAN-012** | 一一对应（编号调整） |
| —（architecture §3.2 Goal 契约） | **PLAN-001** | 本文档**独立成任务**：把散落在 §3.2 / §5.1 / §5.4 的 Goal 四项契约与四条联动不变量集中冻结，避免"Planning 悄悄引入第二套优先级 / 第二套状态机" |
| —（architecture §7.7 Tool System 集成） | **PLAN-006** | 本文档**独立成任务**：把散落在 §3.4 闸门 5/6 与 §7.7 的工具治理契约集中交付并做链路断言，避免工具治理在计划层被稀释 |

**Priority 对照说明**：Architecture §9.2 中 PLAN-013（调试端点与管理面）为 P2；本文档因 PLAN-011 同时承载"内部接口契约冻结 + `goal_repository` 只读扩展 + 审计投影"（属版本价值主体，且 `list_terminal_plans_since` 被 PLAN-010 依赖），整体定级 P1，并把其中**调试端点子项**明确标注为可延后（P2 语义）。除此之外，两文档 Priority 定级一致。

**无新增任务声明**：本文档未新增任何超出 PLAN-001 ~ PLAN-012 的编号，也未扩到 V2.6.0 内容（多步并行编排、`WorldIntentSubmitter` 接线、V9 旧读键退役均明确排除）。

---

## 7. 边界与复用声明

本版本所有任务**复用既有系统**，任何任务不得违反下列边界（对应 architecture §1.2 既有资产盘点、§1.4 对应关系、§2.3 十条边界不变量）：

**复用的既有系统（禁止新建同类系统）**

| 既有系统 | 复用方式 | 禁止事项 |
|---|---|---|
| Goal System（`models/goal.py` + `goal_repository` + `goal_arbitration` + `goal_service`） | 只读消费 + 单一状态写回 | 不新建第二套 Goal 系统 / 第二套优先级算法 |
| Memory 2.0（`memory_policy` R1~R8 + `memory2.retriever` + `ingest_from_goal_completion`） | 计划终态候选经既有政策闸 | 不新建记忆系统、不绕过 R1~R8 |
| Reflection（`reflection/evidence.py` + `reflection_lifecycle` + 三道闸） | 扩一路证据通道 + 新增一个监听器 | 不新建反思系统、不绕三道闸 |
| Autonomy 2.0 / Decision Pipeline（`autonomy_policy` + `decision_pipeline`） | 增量接线（`plan_facts` 一段 + 既有 `goal_compile` 候选面） | 不新建自治执行器 / 不新增候选源 |
| World Simulation（`world_engine` + `outbox_consumer` + `event_bridge`） | 只读预读 + 延迟写经 outbox | 不直写世界表、不新建事件类型 |
| Tool System V2.4.0（`ToolRegistry` / `ToolSurface` / `ToolSelector` / `ToolExecutor` / 健康度） | 规划期查询 + 执行期经 Action 编排器 | 不新增工具选择逻辑、不绕过五段短路 |
| Action Engine（V9，`run_action_planning` 六闸门 + 退避 + `integrate_result`） | 唯一执行编排器 | 不新建执行编排器、不放开 `action_plan_max_steps` |
| Agent Runtime / Life Loop（`life_loop` 九步 + `background_jobs` + `loop_runs`） | 挂既有维护步 | 不新增 stage、不新建调度循环 / Worker |

**四条硬纪律（逐任务验收红线）**

1. 不新建表、不加迁移——计划 / 步骤 / 审计 / 证据全部落在 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表上。
2. Flag 全 off 时与 V2.4.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）。
3. 计划只编排：不直接执行工具、不直接写世界、不直接写 Character 域、不直接写记忆。
4. 反思只管认知：不直接改写计划、不自动熔断工具、不产出性格类 Insight。

---

## 8. 执行状态台账

> 状态流转：TODO → DOING → DONE（由 Coding Agent 逐任务更新，记录完成内容 / 修改文件 / commit / 测试结果）。

| Task | 状态 | 完成内容 | 修改文件 | commit | 测试结果 |
|---|---|---|---|---|---|
| PLAN-001 | DONE | Goal 域契约冻结与生命周期边界（零迁移、零新增字段/值集） | `app/services/planning/__init__.py`、`app/services/planning/goal_contract.py`、`tests/v25/*`（共 12 文件） | 8e4ba52 | tests/v25: 75 passed / 5 skipped；pylint app/services/planning: 10.00/10；compileall OK；既有 goal 子集零新增失败 |
| PLAN-002 | DONE | 计划域值对象 + 配置骨架（零迁移；Q2/Q3 落点裁决落地） | `app/models/plan.py`、`app/core/settings/plan.py`、`app/models/goal.py`、`app/core/settings/enablement.py`、`app/core/settings/__init__.py`、`tests/v25/*`（新增 6 + 更新 2） | ed80000 | tests/v25: 231 passed / 5 skipped；pylint 新模块 10.00/10；compileall OK；既有 goal 子集零新增失败 |
| PLAN-003 | DONE | 六源装配（两源硬依赖、四源可降级）+ 七道闸规划引擎（闸门 5/6 新增）+ `revise` 版本语义 + `goal_supply` 挂载接线（零迁移、零新 stage） | `app/services/planning/context.py`、`app/services/planning/engine.py`、`app/services/planning/__init__.py`、`app/services/planning/goal_contract.py`、`app/services/goal_planning.py`、`app/application/life_loop.py`、`tests/v25/*`（新增 3 + 更新 5） | e14bac8 | tests/v25: 315 passed / 4 skipped；pylint app/services/planning: 9.71/10（余项为逐源降级捕获与冻结接口结构后果）；compileall OK；goal/life_loop/autonomy 子集零新增失败；prompt golden 9 passed |
| PLAN-004 | DONE | 任务拆解（四阶段）+ 三闸校验（validate_shape/binding/budget）+ 四级映射 L1~L4 与粒度判据 G1~G3 | `app/services/planning/decompose.py`、`app/services/planning/__init__.py`、`tests/v25/*`（新增 8 + 更新 4） | 2abc580 | tests/v25: 441 passed / 4 skipped；pylint decompose.py 9.97/10（仅 R0903，与既有规划模块同款）；compileall OK；tests/v24 工具侧 1579 passed；既有失败零新增 |
| PLAN-005 | TODO | — | — | — | — |
| PLAN-006 | TODO | — | — | — | — |
| PLAN-007 | TODO | — | — | — | — |
| PLAN-008 | TODO | — | — | — | — |
| PLAN-009 | TODO | — | — | — | — |
| PLAN-010 | TODO | — | — | — | — |
| PLAN-011 | TODO | — | — | — | — |
| PLAN-012 | TODO | — | — | — | — |