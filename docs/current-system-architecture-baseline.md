# Current System Architecture Baseline

> **性质**：本文档是当前系统**唯一可信架构基线**，描述当下真实存在并已实现的系统，非未来规划。
> **依据**：全部结论基于当前代码（`apps/backend/app/`）、数据库模型（`migrations/` 0001~0052 + `core/db.py`）、配置系统（`core/settings/`）与已封版文档（`docs/version/`）。
> **纪律**：不设计新功能、不修改架构、不把未实现的模块当作现状描述。后续 Agent Runtime / Memory Evolution / Self Improvement / Multi Channel 开发均以此为基准。
> **生成时间**：2026-09-20。

---

## 1. System Overview

### 1.1 项目定位

「角色对话 Agent」——让「亚丝娜」成为具备记忆、情感、目标与自主行为的 AI Agent。

| 维度 | 现状 |
|---|---|
| 后端 | Python 3.13 + FastAPI + LangChain + PostgreSQL 16（SQLAlchemy + Alembic），uv 管理依赖 |
| 前端 | React 19 + TypeScript + Vite + TanStack Query + Zustand + Tailwind 4（调试控制台 Debug Console） |
| 部署 | Docker 多阶段构建 + docker compose（`postgres` + `console` 完整栈） |
| 角色 | 单一角色 `character/asuna/`，单人用户模型（用户行由登录链路派生，无固定 owner id） |

### 1.2 当前系统能力

系统已完成并投入运行的能力（按版本演进）：

- **V1–V9（对话与角色基座）**：会话/流式对话、角色状态（V2）、场景连续性（V3）、长期记忆（V4）、情绪与关系（V5）、目标与意图（V6）、行为精修（V6.5）、自主行为（V7）、角色评估（V7.5）、运行时智能（V7.8）、世界状态系统（V8）、关系演化系统（V8.5）、行动能力系统（V9）。
- **V2.0.0（六 Phase 深化）**：Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced。
- **V2.1.0（Agent 运行时）**：Agent Runtime（Run 台账 / Profile 注册表 / Trigger Router / LLM Gateway）、Character State、Goal Stack、Decision Pipeline、Evolution、Agent Evaluation。
- **V2.2.0（角色）**：Character（风格契约 / Style Context 等 CHAR-001~007）。
- **V2.3.0（世界模拟）**：World Simulation（日计划 / 用户处境 / 世界简报等 WS-001~019）。
- **V2.4.0（工具系统）**：Tool System（声明注册 / 权限 / 确认 / 校验 / 健康度 / 外部 API / 自定义工具 TOOL-001~012）。
- **V2.5.0（规划系统）**：Planning System（规划引擎 / 拆解 / 观察 / 修订 / 调度 PLAN-001~012）。
- **V2.6.0 / V2.6.1（行动执行与反思）**：Action Execution（TASK-001~009）、Reflection（REF-001~007）。
- **横切**：Channel Adapter 接入 + 飞书机器人真实链路验证、后端架构重构（新增 application 编排层）、Feature Flag / Version Gate 清理、`vXX_` 版本变量清理（2026-09-19 收官）。

### 1.3 Agent 整体工作流程

```
User Input
   ↓
Channel Layer        （Web REST / 飞书 Webhook → 通道无关 InboundMessage）
   ↓
Application Layer    （chat_pipeline / life_loop 编排，统一收口为 Run）
   ↓
Agent Runtime        （Run Controller / Profile Registry / Trigger Router / LLM Gateway）
   ↓
Core Systems         （Character / World / Relationship / Planning / Action / Memory / Reflection / Development / Tool）
   ↓
Persistence          （Repositories → PostgreSQL，Alembic 迁移链为 Schema 唯一真相）
```

---

## 2. Overall Architecture

### 2.1 分层图

```
Channels              （channels/：通道无关契约 base.py + feishu/ 适配器；Web 走 REST）
   ↓
API / Application     （api/v1/ HTTP 表现层；application/ 编排层：chat_pipeline、life_loop、agent_runtime、world_engine、action_engine、autonomy_engine）
   ↓
Agent Runtime         （application/agent_runtime/：Run Controller、Profile Registry、Trigger Router、LLM Gateway、Models）
   ↓
Domain Services       （services/：领域服务，按领域子包组织（goal/ relationship/ conversation/ evaluation/ delivery/ …）+ 门面；chains/：LangChain LLM 链）
   ↓
Pure Engines          （engines/：纯函数引擎，无 IO / 无 LLM / 无 DB；application 与 services 均可直接调用）
   ↓
Repositories          （repositories/：每张表一个仓储，唯一 DB 访问面）
   ↓
Database              （PostgreSQL 16；core/db.py SQLAlchemy ORM；migrations/ Alembic）
```

### 2.2 分层职责与依赖方向

分层单向依赖，禁止反向引用（权威边界见 `docs/version/v1.0.0/backend-refactor/target-architecture.md`）：

| 层 | 职责 | 允许依赖 | 禁止 |
|---|---|---|---|
| `api/v1/` | HTTP 表现：schema 校验、流式装配、错误→HTTP 映射 | application、services、schemas | repositories、langchain |
| `application/` | 编排：只做调度与容错，不做状态计算 | services、chains | 直接 SQL、prompt 文本 |
| `agent_runtime/` | Run 生命周期唯一管理者：open→执行阶段→close，唯一写面 = loop_runs | services、repositories | 持有业务语义 |
| `services/` | 领域服务 + 纯函数引擎（无 IO/LLM 的引擎可直接单测） | engines、repositories、chains、core | api |
| `engines/` | 纯函数引擎：无 IO / 无 LLM / 无 DB，可零 fixture 单测（state / autonomy / decision / behavior / mode / memory_policy 等） | models、core.settings、core.constants、纯数据资产 | repositories、chains、services 业务模块、任何 IO |
| `chains/` | LangChain 链，统一经 `chains/structured.py` 结构化输出 | prompts、models、core.llm_factory | repositories、services |
| `repositories/` | CRUD/Query，唯一 DB 访问面 | core.db、models | 一切业务判断 |
| `core/` | 配置（settings/）、DB 引擎（db.py）、LLM 工厂（llm_factory.py）、常量 | — | 业务 |

关键约定：

- **LLM 唯一来源**：`core/llm_factory.get_llm()`（profile 机制）；结构化输出统一走 `chains/structured.py::build_structured_chain`（主链 + 一层降级）。
- **DB 唯一写面**：业务层禁止直接操作 ORM，一律经 `repositories/`。
- **Schema 唯一真相**：Alembic 迁移链（`migrations/versions/`，2026-09-29 起为单一基线迁移 `0001` + 增量迁移（`0002` briefing_preferences 起），ADR-14），`create_all` 已退役（测试内存 SQLite 属豁免）。
- **数据流纪律**：读取进链、写入出链——DB 写入在流式回答结束后执行；后处理失败不影响已产出回答。

---

## 3. Module Architecture

### 3.1 Character System（角色系统）

**角色定义 / 人格 / 状态** 三层：

| 子域 | 实现 | 说明 |
|---|---|---|
| 角色定义 | `character/asuna/identity.py`、`personality.py`、`personality_profile.py` | 静态人设资产（身份 / 人格画像 / 基线），按人设分子目录 |
| 人格（动态） | `personality_state` 表 + `services/development/` + `services/evolution.py` | 人格轴（baseline/current/bound），由 Development 域编译 Insight 调制，受 `agent_evolution_worker` 周期性重编译 |
| 状态 | `character_state` 表（`mood/energy/intensity/current_topic/inner_state/cause`）+ `services/state_engine.py` + `services/state_service.py` | 离散情绪（8 值）+ 能量 + 强度，事件驱动 + 按小时衰减，读即衰减 |

角色资产（`character/asuna/`）还包括：`behavior.py` / `behavior_policy.py` / `behavior_instructions.py`（行为策略）、`modes.py`（对话模式）、`goals.py` / `habits.py` / `habit_triggers.py`（目标/习惯）、`relationship.py` / `relationship_lexicon.py` / `stages.py`（关系词表与阶段）、`emotion_expression.py`（情绪表达）、`world.py` / `action.py` / `tool.py` / `calendar.py` / `routine.py` / `scene_profiles.py` / `narrative.py`（世界/行动/工具/日历/日程/场景/叙事）。

### 3.2 World Simulation（世界模拟）

| 子域 | 实现 | 说明 |
|---|---|---|
| World State | `worlds` 表 + `application/world_engine.py` | 单一世界（`home`），`time_mode`（real_sync/simulated/story）、`sim_time`、`current_location`、`environment`、`notes`；**归属维度（V4.0 PLA-002）**：`owner_type`/`owner_id`（NULL 归一为 `character`），角色世界对用户只读可见，用户容器跨用户拒绝 |
| Object | `world_entities` 表 + `models/world.py::WorldObject` + 对象状态机 `OBJECT_STATE_MACHINES` | 物品（category 7 类），状态机迁移、消耗扣减、别名解析、默认家庭库存幂等播种 |
| Environment | `worlds.environment` JSON（weather/lighting）+ `services/world/weather.py` | 天气演化、光照建议 |

世界服务（`services/world/`）细分：`interpreter.py`（用户消息→世界迁移解释）、`locations.py` / `movement.py`（地点与移动）、`time_provider.py` / `time_advancer.py` / `day_cycle.py` / `catch_up.py`（时间与日循环）、`daily_plan.py` / `user_situation.py` / `world_brief.py`（日计划/处境/简报）、`context_selector.py`（世界切片装配）、`event_impact.py`（事件影响裁决）、`memory_bridge.py` / `event_bridge.py`（记忆/事件桥）。

**世界旁路纪律**：世界读写只经 `world_repository`，任何异常仅 log 并降级（None），聊天与主动链路永不因世界而失败。

### 3.3 Relationship System（关系系统）

| 子域 | 实现 | 说明 |
|---|---|---|
| Relationship State | `relationship_state` 表（intimacy/trust/familiarity/respect/comfort/tension 六维 + stage + conflict_status + neglect_active，带 version 乐观锁） | 四阶段（stranger/friend/close_friend/partner）+ 冲突状态机 |
| Interaction | `relationship_events` 表（账本）+ `services/relationship_signal.py`（Interaction Analyzer） | 信号是演化唯一上游输入（词表 + 既有 LLM 可选字段，P0 零新增 LLM），升格后落账本 |

关系服务（`services/relationship_*.py`）：`signal.py`（信号分析）、`evolution.py`（派生指标 + 演化引擎，全纯函数可重放）、`conflict.py`（冲突状态机 none→strain→conflict→cold→recovery→resolved）、`milestone.py`（里程碑注册表 + 检测）、`memory.py`（关系记忆候选）、`narrative.py`（叙事里程碑）、`patterns.py`（关系模式只读消费）、`shared.py`（共同经历只读投影）、`audit.py`（账本重放对账）、`evaluation.py`（离线评估）。

**账本纪律**：`relationship_events` 是关系事件时序权威（全量）；`relationship_state` 是当前状态（upsert 强一致）；`relationship_snapshots` 是版本化快照（`relationship_evolution` 逐字节可重放）。

**数据治理（V4.0 PLA-003）**：财务数据分级由 L2「不保存」重裁为 **L1 受控保存**（本地 + 用户可控 + 可导出删除 + 明细永不进 Prompt）；`services/governance/` 提供领域注册点 / 导出 / 删除 / 溯源 / Prompt 护栏；`GET /life/export` 与 `DELETE /life/data` 为用户权利面出口。记忆域 R1~R8 与 R9 不动。

### 3.4 Planning System（规划系统）

| 子域 | 实现 | 说明 |
|---|---|---|
| Goal | `character_goals` 表（type/priority/status/horizon/source/layer/domain/parent_goal_id）+ `services/goal_*.py` | 目标分层（short_term/medium/long_term），Goal Stack（`goal_stack.py`）只读编译 + 后台长期化 |
| Plan | `goal_plans` 表（sub_goals JSON，versioned）+ `services/planning/engine.py::PlanningEngine` | 七道闸规划引擎：attempt_cap → 形状 → 步数 → 能力对齐 → 工具可解析 → 工具在面 → LLM 失败；计划落库只经 `goal_repository` 计划面 |
| Decision | `decision_records` 表 + `services/decision_pipeline.py` | 统一决策管线：候选评估 + 胜者审计，前台/后台同一代码路径；目标栈长期化写入只发生在后台（铁律 4） |

规划服务（`services/planning/`）：`engine.py`（七道闸引擎）、`decompose.py`（拆解）、`context.py`（上下文装配 + digest）、`goal_contract.py`（失败理由契约）、`observer.py`（四源观察）、`revision.py` / `revision_listener.py`（重规划裁决）、`scheduler.py`（当前步调度）、`executor_bridge.py`（执行桥）、`memory_policy.py`（记忆策略）。

目标生命周期：`materialize`（供给装配，三来源候选）→ `PlanningEngine.enqueue/plan`（七道闸）→ `PlanScheduler` 执行 → `PlanObserver` 观察推进 → `PlanRevisionPolicy` 重规划 → 终态经 `goal_repository.settle` 单一写面。

### 3.5 Action Execution（行动执行）

| 子域 | 实现 | 说明 |
|---|---|---|
| Action Definition | `models/action.py`（Action/ActionSchema/ActionStep/ActionResult/CapabilityResult/ACTION_TYPES/ACTION_EXECUTION_MAP）+ `character/asuna/action.py::ACTION_CAPABILITY_MAP` | 动作类型 → 执行方式（internal/tool/external）映射 |
| Executor | `services/action/executor.py`（CapabilityExecutor + ActionExecutor）+ `services/action/capabilities/` | CapabilityExecutor 超时包裹/异常归一/usage 统计；ActionExecutor 按分派；工具绑定优先（五段：权限/确认/校验/归一/健康） |
| Result | `action_records` 表 + `action_schedules` 表 + `services/action/result.py` | 行动台账（status 状态机 created→planned→executing→succeeded/failed/cancelled），steps[] 增量落 tool_id/permission/validation/duration_ms |

行动编排器：`application/action_engine.py::ActionEngine`（create_record → evaluate_gates → assemble_plan → execute_plan → integrate_result），发生在 post_process 第 9 步（per-user 写锁内）或重试维护循环。

内置六能力（`services/action/capabilities/`）：`reminder`（提醒）、`memory`（记忆）、`world_action`（世界动作）、`environment_query`（环境查询）、`search`（搜索）、`notification`（通知）；另有两项条件/无条件注册：`channel_feishu`（通道工具，通道可用时注册）、`external_api`（外部 API，无条件注册）。能力是"手脚不是逻辑"：只知道怎么做，调度权/重试决策/回复生成不在能力里。

### 3.6 Memory System（记忆系统）

当前记忆体系由三层构成（V4 长期记忆 + Memory 2.0 生命周期化 + Reflection/Development 上层）：

**已实现部分：**

| 层 | 实现 | 说明 |
|---|---|---|
| V4 长期记忆 | `services/memory_service.py` + `services/memory_policy.py` + `services/memory_conflict.py` | 提取 → 策略 → 冲突消解（LCS 同题检测）→ 落库 → 打分召回（词法/重要性/时效/类型加权）→ 注入上下文 |
| Memory 2.0 | `services/memory2/`（`types`/`sources`/`ingest`/`evaluator`/`retriever`/`lifecycle`/`embeddings`/`commands`/`attribution`/`migration`/`offline_metrics`/`job_worker`） | 7 类类型封顶（user_preference/user_fact/experience/relationship_fact/commitment/milestone_event/behavior_pattern）；四源摄取（Conversation/ActionRecord/WorldEvent/RelationshipEvent）幂等入 `memory_candidates`；三段评估（规则分 → 灰区 lite LLM 兜底 → 转正/拒绝）；混合检索（语义 cosine + 结构化 recency/importance/salience/类型亲和）；六态生命周期（active/superseded/invalidated/decayed/forgotten + 软删后物理删，salience·exp(-λ·Δdays) 衰减）；Embedding 批处理；显式命令（记住/忘掉） |
| Reflection（反思） | `services/reflection/` + `insights`/`reflection_runs`/`evidence_links` 表 | 证据窗聚合 → LLM 结构化推理 → confidence 校准 → 三闸复检 → Insight 落库；Insight 生命周期（active→superseded/invalidated） |
| Development（成长） | `services/development/` + `development_state`/`development_changes`/`personality_state` 表 | belief/preference/pattern 三类发展状态，编译为对人格轴的调制，可回滚/重放 |

**未实现部分（当前不存在，仅作边界标注）：**

- **显式 Episodic / Semantic 记忆分层**：当前记忆是扁平 7 类型 + 反思/成长上层，尚无显式的"情景记忆 / 语义记忆"双通道子系统（见 §8 Extension Points）。
- **Self Improvement**：尚未实现，属未来方向（见 §11）。

---

## 4. Agent Runtime Flow

> **V3.0.0 Agent Runtime 更新（2026-09-22）**：本节描述的运行路径在 V3.0.0 中已由
> **Agent Runtime**（`application/agent_runtime/`）承载。落点与形态：
>
> | 面 | 落点 |
> |---|---|
> | 契约 | `agent_runtime/contracts.py`（`RuntimeInput` / `SessionContext` / `RunResult` / `RuntimeEvent` / `RuntimeFailure`） |
> | 会话 | `agent_runtime/session.py`（`open/resume/close_session`；无会话表，`loop_runs.session_id` 挂接） |
> | 循环 | `agent_runtime/loop.py::AgentLoop` + `profiles.py`（**段序列唯一声明处**） |
> | 状态 / 上下文 | `agent_runtime/state.py`（版本投影）/ `context.py`（四段装配，Run 内可冻结） |
> | 事件 | `agent_runtime/events.py`（进程内同步总线，零业务表写入；跨域可靠投递仍走 Outbox） |
> | 通道归一 | `agent_runtime/inbound.py` / `outbound.py`（`ChannelAdapter` 契约零改动） |
> | 持久化 / 恢复 | `agent_runtime/recovery.py`（孤儿 Run 收敛）/ `execution_history.py`（执行历史只读投影） |
> | 观测 | `agent_runtime/debug_view.py`（Debug / Replay 组合）+ `services/observability/trace_query.py`（仓储级读面） |
> | Schema | 唯一扩展 = 迁移 `0052`（`loop_runs.session_id` + `runtime_traces.correlation_id`）；**零新建表** |
>
> **⚠️ 唯一认知循环裁决（H-1 裁决 B → R-15 灰度）**：默认在跑的循环是 `profiles.py` 声明的
> **Profile 阶段序列**（`loop.py::_run_stages`，段本体为既有阶段实现：`chat_pipeline` 22 步闭包 /
> 自治 Profile 阶段）。`runtime_six_stage_loop_enabled=True` 时 `run()` 改走六段方法
> （observe/reason/plan/act/reflect/update）。详见
> `docs/version/v3.0.0/architecture.md` 附「实现期裁决登记 D-1」。
> `life_loop._step_*`）。`AgentLoop.observe/reason/plan/act/reflect/update` 与
> `agent_runtime/stages/*` 是**影子 / 测试实现**，**未接入生产 `run()`**，已从生产导出面隔离。
> 完整裁决、护栏与「方案 A 真收编」的前置条件见
> `docs/version/v3.0.0/architecture.md` 附「实现期裁决登记 D-1」。
>
> **前台回退开关**：`RUNTIME_FOREGROUND_LOOP_ENABLED`（默认 `True`）。关闭时前台走
> `chat_pipeline._drive_foreground_linear`（线性旧链：同一段序列与段本体，**不建 Run 台账、
> 不发运行时事件、不冻结上下文**），用于一键回退而不必回滚代码。
>
> 验收与评审：`docs/version/v3.0.0/acceptance-report.md`（G1~G12）、
> `docs/version/v3.0.0/reviews/RT-ALL-code-review.md` + `RT-ALL-remediation.md`。

### 4.1 前台交互生命周期（一次用户消息）

Web 与飞书最终都收敛到 `services/agent_service.stream_chat` → `application/chat_pipeline.run_chat_pipeline`，整链包裹为 `foreground_chat` Run（台账记账）。

```
User Message
   ↓ Channel 归一（web REST / feishu adapter → InboundMessage）
   ↓
1. open_foreground_run          打开 foreground_chat Run（loop_runs 建行 + Profile 快照）
   输入: user_id               输出: RunContext        模块: agent_runtime.controller
   ↓
2. assemble_snapshot            装配 Agent 状态快照（人格基线/目标栈/状态）
   输入: user_id               输出: snapshot         模块: agent_state_assembler
   ↓
3. build_context                世界上下文切片（只读、有界、失败降级 None）
   输入: user_id/session_id    输出: world_ctx        模块: world_engine
   ↓
4. context_builder.build        装配上下文（历史窗口/摘要/记忆召回）
   输入: session_id/content    输出: ConversationState 模块: services.context_builder
   ↓
5. scene_service.load           加载场景状态
   输入: session_id            输出: scene_state      模块: services.scene_service
   ↓
6. _select_goal                 目标选择（紧张度/情绪/深夜豁免/发展权重）
   输入: state/scene_state     输出: SelectedGoal     模块: services.goal_service
   ↓
7. 四链并行（asyncio.gather）
   role_router                  路由：候选 mode + 置信度  chains.router_chain
   turn_analyzer                轮次分析：情绪/事件/行为  chains.turn_analysis_chain
   scene_intent                 场景意图分类           chains.scene_intent_chain
   intention                    意图决策               chains.intention_chain
   ↓
8. mode_stabilize               mode 稳定（候选 vs 已确认，稳定器 R5 兜底）
   输入: role_mode/state       输出: ModeDecision     模块: services.mode_service
   ↓
9. scene_service.resolve        场景收敛（pending 动作续接/新意图）
   输入: scene_intent/state    输出: resolved_state/directive
   ↓
10. enforce_intention           意图确定性校验（策略降级）
   输入: intention_candidate   输出: validated_intention 模块: services.intention_policy
   ↓
11. 前台决策管线                统一决策（goal_stack 只读 + decision_pipeline）
   输入: validated_intention   输出: decision_audit    模块: decision_pipeline + goal_stack
   ↓
12. behavior_engine.resolve     行为策略解析（策略/预算/习惯/关系解锁）
   输入: intention/state/scene 输出: behavior_ctx      模块: services.behavior_engine
   ↓
13. build_style_context         风格契约装配（人格轴快照 + development overlay）
   输入: state/turn            输出: style_ctx        模块: services.experience.style_context
   ↓
14. detect_action_intent        行动意图检测（可选）
   输入: content/scene/world   输出: action_intent    模块: services.action.detector
   ↓
15. yield turn_meta             首段元数据（role_mode/analysis/scene/intention/goal/behavior/mode）
   ↓
16. answer_chain.astream        流式回答（token 逐字产出，受 inventory grounding 可选缓冲）
   输入: mode/state/turn/ctx   输出: reply 流         模块: chains.answer_chain + llm_gateway
   ↓
17. conversation_service.save_turn  落库本轮（读进链、写流出链）
   输入: session_id/reply      输出: ai_message_id    模块: services.conversation_service
   ↓
18. schedule_post_process       后台编排（scene_update ‖ state_update ‖ goal_review ‖ summary ‖ memory_extract，独立容错）
   输入: 本轮全部状态          输出: 后台任务          模块: application.post_process
   ↓
19. observability 收口           trace 落库 + decision 记录 + turn 决策审计
   输入: trace/turn            输出: 落库             模块: application.observability
   ↓
20. yield done                  会话 id / turn_id / request_id
   ↓
21. close_run                   关闭 Run（终态 + 成本汇总）
```

### 4.2 后台自治周期（life_loop）

`life_loop.py::run_life_loop_worker` 常驻循环，先 sleep 后 tick；`run_life_loop_tick` 先工作发现（0 LLM），再逐用户跑 `agent_runtime.run_autonomous_cycle`（autonomous_tick Profile），最后跑事件预闸与维护步。

**调度路径（V4.0.0 PLA-018 统一）**：`run_autonomous_cycle` **固定经 `AgentLoop`** 驱动自治 tick 的 Profile 段序列，不再按配置分支；`controller._legacy_run_autonomous_cycle` 为**代码级回退位**，仅回滚期可显式调用、**不可由配置触达**。`runtime_autonomous_cycle_enabled` 字段保留但**已无读取点**，待 flag-removal 批次清理（`docs/refactor/flag-removal-audit.md` 附录 H.16）。六段认知循环（`agent_runtime/stages/*`）**仍为影子实现**，未接入生产 `run()`。

**autonomous_tick Profile 阶段序列**（`profiles.py` 唯一声明处，禁止另开阶段序列）：

```
perception → state_update → state_snapshot → goal_check → goal_stack →
goal_supply → goal_advance → memory_retrieval → reflection_check →
decision → world_experience
```

- `decision` 是唯一 LLM capable 且 critical 阶段：两道既有预算闸 → `llm_gateway.acquire` 第三道闸 → `autonomy_engine.tick`（V7 决策管线）。
- `event_driven` Profile（Flow C）：白名单世界事件（`escalation_whitelist`）升级为完整 Run，其余 0 消耗。

**维护步**（`_run_maintenance`，按间隔调度）：world_maintenance、world_simulation、action_retry、action_schedule、outbox_consume（`action_outbox_enabled` 门控）、trigger_reconcile、**ledger_digest**（PLA-011 日结/周报，数字只来自聚合）。

**其它常驻后台循环**（`main.py` lifespan）：memory reclaim、job worker（`memory2.job_worker`）、agent evolution worker（指标快照 + 人格编译 + goal rebalance）、observability retention（`observability_persist_enabled` 门控）、世界维护循环。

---

## 5. Channel Architecture

### 5.1 Adapter 设计

通道层遵循**通道无关契约 + 通道适配器**模式。核心契约在 `channels/base.py`（全层允许依赖的最底层契约，仅标准库、零 `app.*` 依赖、零第三方依赖）：

- 入站基元：`InboundMessage`（channel/external_user_id/text/received_at/external_thread_id/reply_ref/metadata）
- 身份：`ChannelIdentity`、`RecipientRef`
- 出站协议：`ChannelReply`、`OutboundMessage`（含 idempotency_key）、`SendResult`
- 错误：`ChannelErrorKind`（not_found/auth/rate_limited/timeout/server_error/client_error/disabled/invalid_request/unknown）
- 适配器协议：`ChannelAdapter.send(message) -> SendResult`

身份派生（`open_id → internal_user_id`）属通道无关逻辑，落在 `services/identity/channel.py`，经 `channel_identities` 表持久化。**2026-10-03 起（ADR-16）**`internal_user_id` 不再由凭据派生（原 `feishu:{open_id}`），改为**雪花 ID**（`app/core/ids.py`）；且通道身份首次出现时**补建对应 `users` 行**——同一个人跨通道（飞书 + 邮箱）解析到**同一个 `user_id`**，凭据本身只作为 `channel_identities` 里的一行绑定。`channel_identities` 因此成为**全通道统一的凭据绑定表**（`channel='email'` 行承载邮箱登录，`session_id` 改为可空——仅飞书等有「默认会话」语义的通道写入）。

### 5.2 当前通道

| 通道 | 入站 | 出站 | 说明 |
|---|---|---|---|
| Web | `POST /api/v1/chat/message`（StreamingResponse NDJSON：turn_meta → delta* → done；Bearer token 鉴权，user_id 由 token 解析） | 同一流式响应 | 移动 App 产品通道 + 调试控制台通道 |
| Feishu（飞书） | `POST /api/v1/feishu/events`（Webhook：验签/解密/challenge/去重/限流 → `feishu.adapter.ingest_inbound_message`） | `feishu.delivery`（Reply 有锚点 / Proactive 无锚点共用切分/幂等/收口） | 已通过真实链路验证 |

飞书适配器（`channels/feishu/`）细分：`adapter.py`（入站编排：收件箱合并/排队 → 身份 → 会话串行 → LLM → 既有管线 → TurnOutcome）、`delivery.py`（出站）、`client.py`（API）、`events.py`（验签/解密）、`identity.py`（身份组装）、`inbox.py`（SessionInbox 每会话 FIFO）、`outbound.py`、`errors.py`。

背压：`feishu_session_queue_limit`（排队批次数上限）+ `feishu_max_concurrent_turns`（进程内全局并发闸门，容量对齐 DB 连接池）。

### 5.3 未来通道

Discord、Telegram、微信——**当前未实现**，仅作为扩展方向（见 §8）。

### 5.4 Channel 边界（铁律）

Channel **不应该**包含：Agent 逻辑、Memory 逻辑、World 修改。

只负责：

```
Message In   →   归一为 InboundMessage   →   Agent Request   →   消费事件流组装回复
   ↓
Response Out →   经 OutboundMessage 契约发送
```

证据：飞书 `adapter.py` 只做"取身份/排队/取 LLM/消费事件流/组装回复"；对话逻辑唯一在 `chat_pipeline`；出站发送由 `delivery` 消费 `TurnOutcome`（经通道无关 `OutboundMessage`），不 import 任何 Autonomy 模块（R3）。

---

## 6. Data Architecture

### 6.1 核心表与关系

Schema 唯一真相 = Alembic 迁移链（`migrations/versions/`，基线迁移 `0001`（2026-09-29 由原 0001~0058 折叠，ADR-14）+ 增量迁移 `0002` 起）；ORM 模型集中定义于 `core/db.py`；领域 Pydantic 模型在 `app/models/`。

| 域 | 核心表 | 关系/关键约束 |
|---|---|---|
| 会话 | `conversations`、`messages`、`conversation_summaries` | messages.conversation_id → conversations.id；summary 1:1 conversation |
| 身份 | `users` | `id` = **雪花 ID 的十进制串**（ADR-16，2026-10-03；`VARCHAR` 为**最终形态**，列类型翻转已评估后取消，见 §9）；email 唯一**部分索引**（邮箱验证码登录绑定，原 0057 引入、随折叠并入 `0001` 基线）；`is_default` 列与唯一索引已删除（默认用户概念退役，原 0058） |
| 简报 | `briefing_preferences` | user_id 主键（一行一人）；时刻 HH:MM 字符串 + 定位城市及地理编码坐标（API-008 偏好落库，增量 `0002` 引入） |
| 角色状态 | `character_state`、`emotion_history`、`personality_state` | character_state.user_id 主键；emotion_history 按 user 时序；personality_state 唯一 (user,character,axis) |
| 关系 | `relationship_state`、`relationship_events`、`relationship_milestones`、`relationship_conflicts`、`relationship_snapshots` | state 为当前态（version 乐观锁）；events 为账本（时序权威）；snapshots 版本化快照 |
| 目标/计划 | `character_goals`、`goal_plans` | goals.parent_goal_id 自引用分层；goal_plans.goal_id → goals，版本号 version |
| 场景 | `scene_state` | session_id 主键，pending_action 跨轮延续 |
| 记忆 | `memories`、`memory_candidates`、`memory_links`、`insights`、`reflection_runs`、`evidence_links` | candidates 唯一 (source_table,source_id) 幂等；links 记忆间关系；insights ← evidence_links ← memories |
| 成长 | `development_state`、`development_changes` | changes 追溯 before/after + insight 溯源 |
| 世界 | `worlds`、`world_entities`、`world_events`、`world_snapshots`、`daily_plans`、`user_situations` | worlds.user_id 唯一；entities/events → world_id；events idempotency_key 幂等 |
| 行动 | `action_records`、`action_schedules` | records 台账（run_id/status 状态机）；schedules 1:1 action 定时 |
| 自主 | `proactive_actions`、`trigger_registry`、`outbox_events`、`background_jobs` | proactive dedupe_key 幂等；trigger registry 触发登记；outbox 事件投递 |
| Agent 运行时 | `loop_runs`、`agent_state_snapshots`、`agent_metric_snapshots`、`decision_records` | loop_runs 为 Run 台账（steps/预算）；decision_records 为决策审计 |
| 通道 | `channel_identities`、`feishu_dedupe_ledger` | identities 复合主键 (channel, external_id)，**全通道统一凭据绑定表**（`channel ∈ {email, feishu}`），`internal_user_id` = 真实 `users.id`（雪花），`session_id` 可空（仅飞书等有默认会话语义的通道写入）；dedupe_ledger 以 `event_id` 为主键承载跨进程入站去重（FEISHU-010，`FEISHU_DEDUPE_PERSISTENT_ENABLED` 控制，默认关闭） |
| 观测 | `runtime_traces`、`llm_call_records`、`prompt_snapshots`、`evaluation_reports` | 按 request_id/turn_id 关联 |

### 6.2 生命周期

- **状态表**（character_state / relationship_state）：upsert 强一致，读即衰减（情绪/关系按小时衰减），带 version 乐观锁。
- **账本表**（relationship_events / action_records / decision_records / loop_runs）：append-only 事件流，只增不改。
- **版本化表**（goal_plans / relationship_snapshots / agent_state_snapshots / world_snapshots）：version 递增，旧版本置 superseded。
- **终态清理**：世界事件/快照按保留期裁剪；trigger/outbox/background_jobs 达上限转 failed 死信。

### 6.3 Source of Truth

| 真相源 | 表/链 | 说明 |
|---|---|---|
| Schema 真相 | `migrations/`（Alembic） | `create_all` 已退役 |
| 角色当前状态 | `character_state`、`relationship_state` | 单一写面（state_service/relationship_evolution） |
| 关系事件时序 | `relationship_events` | 账本是事件时序权威 |
| 记忆真相 | `memories`（+ candidates/links） | Memory 2.0 六态生命周期 |
| 世界真相 | `worlds` + `world_entities` + `world_events` | 世界旁路纪律，快照可恢复 |
| 行动真相 | `action_records` | 行动台账 + 幂等键 |
| Run 台账 | `loop_runs` | Agent Runtime 唯一写面 |
| 决策审计 | `decision_records` | 候选/胜者/理由可审计 |

---

## 7. Configuration Architecture

### 7.1 当前配置方式

| 维度 | 机制 | 说明 |
|---|---|---|
| Environment | pydantic-settings（`.env`，`extra="ignore"`） | 环境变量名 = 字段名全大写，无 alias 层、无 env_prefix |
| Runtime Config | `Settings` = 25 个领域模块多继承组合的**扁平命名空间** | `core/settings/`：llm/database/pipeline/character/memory/reflection_development/relationship/goal/autonomy/life_loop/autonomy_advanced/agent_runtime/action/action_execution/evaluation/feishu/email/ledger/observability/world/world_simulation/tool/plan/weather/**ids** |
| Feature Config | 按领域命名的布尔开关 + 调参字段 | 开关语义已从"版本门控"收敛为"策略位/裁决位/调试位" |
| LLM Profiles | `llm_profiles.json`（`LLM_PROFILES_FILE`）或 `LLM_PROFILES_JSON`（内联优先） | 多模型 profile，消息级切换（body `profile_id` > header `X-LLM-Profile` > query） |

### 7.2 已移除项（确认）

- **Version Gate 体系**：`core/settings/enablement.py` 已删除（版本桶常量 `V25_SUB_FLAGS` 等随文件移除）。
- **`vXX_` 版本变量**：带 `vXX_` 前缀 **0**（settings 字段总数 2026-09-28 实测 **423**；200 字段去前缀 + 死开关/未接线字段删除 + 各批 ON 转常开）。
- **启动期未知 env 键告警**：`unknown_versioned_env_keys()` 已删除（2026-09-28，连带 `app/main.py` lifespan 的告警循环与 3 条自测）。删除时全仓 `V<数字>_` 键为 0、函数返回 `[]`，故**零行为变化**；代价是**生产启动边界不再有「env 键 ↔ settings 字段」一致性检查**（`tests/conftest.py::set_known_env` 只在测试进程生效），部署侧死键将完全静默。
- **世界域四闸**：`world_enabled`（总闸，曾 11 处读取）与 `world_household_autoseed_enabled` / `world_interpreter_enabled` / `world_memory_bridge_enabled` 已删除（2026-09-28，固化常开，世界域不可再配置旁路）。TOOL-007 的 `world["world_enabled"]` 键保留为**装配标记**（「已装配 vs 未装配」数据契约，非配置开关）。记录见 `docs/refactor/remaining-flag-audit.md` 附录 E.7 / E.8。
- **剩余策略位**：仍有少数按领域命名的布尔开关作为策略/裁决保留（如 `action_outbox_enabled`、`foreground_gateway_enforced`，以及 tool/plan/action 域的调试与策略子闸），语义非版本门控。2026-10-02 新增 `roleplay_prompt_mode`（`full`（默认）/ `off`，模式串口径同 `inventory_grounding_mode`，不引入 `*_enabled` 字段）：**只控制回答链 prompt 是否注入演绎段**（人设 / 情绪 / 角色状态 / 关系 / 世界 / 场景 / 行为 / 风格），`off` 仅保留功能上下文（记忆 / 认知 / 目标 / 意图 / 行动段 / 摘要 / 历史）；世界与角色**引擎照常运行**，世界域「不可配置旁路」裁决与 `world_enabled` 已删除的结论不受影响。

---

## 8. Extension Points

### 8.1 Tool System（工具系统）

支持 **Function Calling / External API**：

| 能力 | 现状 | 说明 |
|---|---|---|
| 声明注册 | `ToolRegistry`（`tool/registry.py`） | 注册期七项校验（id 格式/唯一/命名空间/capability 可解析/schema 自洽/permission/长度预算）；模块级单例，代码注册非热插拔 |
| 内置工具 | `tool/builtin.py` + `tool/manifests/` | 点分命名空间（如 `builtin.reminder.create`） |
| 执行五段 | `tool/executor.py` | 权限 → 确认 → 校验 → 归一 → 健康度；健康度滑动窗 + 熔断（`ToolHealth`） |
| External API | `tool/ext_api.py` + `external_api` 能力 | 声明式清单（`tool_ext_manifest_path`）生成 `ext.api.*` 工具，统一执行器可解析 |
| 自定义工具 | `tool/user_defined.py` | 用户自定义工具注册/注销（经 `CapabilityRegistry.unregister`） |
| 通道工具 | `tool/channel_tools.py` | `channel.feishu.send`（通道可用时注册） |

### 8.2 Memory Evolution（记忆演进）

支持 **Episodic Memory / Semantic Memory** 的落点：当前 `memory2` 已是类型化（7 类）+ 生命周期化 + 混合检索（语义 cosine + 结构化）的底座，`reflection`（Insight）与 `development`（belief/preference/pattern）是上层加工。显式 Episodic/Semantic 双通道在此之上扩展，**当前尚未实现**。

### 8.3 Multi Channel（多通道）

支持 **Discord / Telegram**（未来含微信）的落点：`channels/base.py` 的 `ChannelAdapter` 协议 + `channel_identity_service` 身份派生 + `delivery` 出站端口 + `channel_tools` 通道工具注册，均已为多通道预留；新增通道只需实现 adapter + delivery 并注册，无需改动 Agent 核心。

### 8.4 Email 发件（邮箱验证码登录，2026-09-27）

| 能力 | 现状 | 说明 |
|---|---|---|
| 发件端口 | `services/email/sender.py` 的 `EmailSender` 协议 | 验证码服务只依赖协议；换 Resend / 阿里云 / 腾讯云 = 新增实现类 + `build_email_sender` 的 provider 分支，业务零改动 |
| SMTP 实现 | `SmtpEmailSender`（aiosmtplib，按次建连） | MVP 163 个人邮箱：465 SSL + 授权码；`EMAIL_*` 配置域（`core/settings/email.py`） |
| 验证码存储 | `services/identity/code_store.py` 的 `VerificationCodeStore` 协议 + `RedisCodeStore` | 短 TTL 一次性状态入 Redis：SETNX 冷却 / INCR+EXPIRE 小时·日频控 / GETDEL 单次消费 / 尝试超限作废；多实例前必须保证 Redis 可用 |
| 登录端点 | `POST /auth/email/code` + `POST /auth/email/verify`（`api/v1/auth.py`） | 校验通过 find-or-create：先按 `channel_identities(channel='email', external_id=<规范化邮箱>)` 查绑定，命中即返回其 `user_id`；未命中则新建 `users` 行（id = 雪花）+ 写入绑定行。幂等由 `ux_users_email` 唯一索引 + 插入冲突重查兜底。签发无状态 HMAC 令牌；SMTP / Redis / 令牌密钥缺一 503 |

---

## 9. Current Technical Debt

| 问题 | 影响 | 优先级 |
|-|-|-|
| `services/agent_service.py` 是"兼容壳"，编排已迁 `chat_pipeline` 但壳仍保留供 api/测试依赖 | 双入口符号残留，新同学易误入旧路径 | P2 |
| `services/` 巨型文件尚未拆完：`tool/ext_api.py`(1507) / `planning/decompose.py`(963) / `planning/observer.py`(864)，次一级 `tool/confirmation.py`(771) / `grounding/inventory_guard.py`(768) / `planning/context.py`(742) / `development/evaluation.py`(708)（`evaluation/context.py` 与 `reflection/evidence.py` 已于 2026-09-30 包化） | 单文件承担多职责，阅读与改动半径变大；`observer` 经补丁缝 + AST 调用图审计判定**不拆**（广播与 settle 双向调用，改用文件内分节导航） | P3 |
| ORM 模型集中于 `core/db.py`（44 表），`app/models/` 为 Pydantic 领域模型，二者边界靠约定无显式约束 | 模型层职责易混淆，新增表需人工判断落位 | P2 |
| **迁移链头钉测已收口**（2026-09-29 全链折叠为单迁移 `0001`，ADR-14）：钉测单点 `tests/support/schema_pins.py`（`MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`），v24 取证常量单点 `tool012_support.py`；新增迁移只需 bump 钉文件 | 残余：`v24`/`v25`/`v26`/`v30`/`v40` 部分测试文件名仍带历史版本号字面量（如 `test_runtime_migration_0052.py`），语义已泛化为最终态断言，待未来顺手改名 | P2 |
| `foreground_gateway_enforced` / `action_outbox_enabled` 两个门控未收敛（前者缺 `light_llm_profile` 裁决保留，后者 outbox 灰度暂留） | 配置面仍有两处门控语义残留 | P2 |
| 调试台面端点（`/debug/*`、`/state`、action）`user_id` 省略时取 token 身份（`require_user`），可显式传入覆盖——**已无魔法默认值**（2026-09-28 IDENT-009）；调试面无多用户隔离（可任意指定 user_id 查看他人数据），产品面已隔离 | 调试面无多用户隔离；产品面已隔离 | P2 |
| **身份 ID 列保持 `VARCHAR`**（ADR-16，2026-10-03 **评估后主动取消翻转**）：`users.id` 与 37 张表的 `user_id` 存**雪花 ID 的十进制串**，不做 `BIGINT` 列翻转。已实测收益只剩「DB 类型层强制 ID 为数字」，成本为 **584 处**测试字面量（**180 个文件**，191 个不同字面量）+ 删库重建（与 B1「存量用户下次登录自动回填绑定」的自愈路径矛盾）；而存储差异在 `users` 规模下 **< 2KB**、对外契约（字符串出 JSON）两种方案完全一致 | 需强约束时改在**应用边界**校验（成本 1 处）；列类型与 Python 类型均为字符串，语义一致 | P3 |
| **雪花 ID 可枚举性**（ADR-16，2026-10-03）：`user_id` 由不可枚举的 `email-<sha256[:16]>` 变为**高位含时间戳、按时间递增**的雪花 ID，攻击者可推算「某时刻注册的用户 ID 落在某区间」 | 与上一行「调试面无多用户隔离」叠加后，同一缺陷的**严重度上升一档**；需配套：调试面环境门禁 + 「产品端点忽略显式 `user_id` 参数」测试 | P2 |
| **ID 出 JSON 必须为字符串**（ADR-16，2026-10-03）：雪花 ID 当前 **57 位**、2036 年达 61 位，超出 JS `Number.MAX_SAFE_INTEGER`（53 位）约 **11 倍**；以 JSON number 返回会被浏览器 / 调试台（React + TS）静默截断 | 属**硬约束**而非偏好；与 Discord / Twitter 对外策略一致。任何新增 ID 字段都须以字符串出参 | P1 |
| `docs/` 169 文件、1589 处 `vXX_` 引用未改写（历史文档不改写是约定，靠 `flag-rename-map.md` 桥接） | 读历史文档需查对照表，存在导航断层 | P2 |
| 测试侧版本标记残留 188 处（fixture 名/函数名如 `v24_tool_env`、`v21_on`） | 测试命名仍带历史版本号，语义混淆 | P3 |
| settings 命名一致性建议未采纳（`flag-rename-map.md` §七：部分字段去前缀后丧失域归属，如 `decision_weight`、`planning_enabled`） | 扁平命名空间局部可读性下降 | P3 |
| `ActionExecutor.execute_external` 返回 `external_adapter_reserved` 占位（外部 API 功能实际经 Tool 路径 `execute_tool` 实现，`external` ExecutionKind 是保留桩） | 分派面与实现面存在语义错位 | P2 |
| `enablement.py` 源文件已删但 `__pycache__/enablement.cpython-313.pyc` 残留 | 字节码残留（gitignore 兜底，非功能影响） | P3 |

---

## 10. Architecture Decision Records

已确定并落地的重要决策：

1. **Channel Adapter 独立**：通道层只做消息归一与出站发送（`channels/base.py` 契约 + feishu/web 适配器），不包含 Agent/Memory/World 逻辑。
2. **Agent Core 不依赖具体平台**：Web 与飞书最终都收敛到 `agent_service.stream_chat` → `chat_pipeline.run_chat_pipeline`，对话逻辑唯一。
3. **去除版本开关**：`vXX_` 版本前缀与 `enablement.py` 版本门控体系整体删除（2026-09-19 收官），字段名不带版本号，env 名 = 字段名大写（无 alias 层）。
4. **World 作为独立状态系统**：世界域独立（`worlds`/`world_entities`/`world_events` + `world_engine` + `world_repository`），遵循旁路纪律——异常只降级不阻断聊天/主动链路。
5. **application 编排层**：新增 `application/` 只做调度与容错，状态计算下沉纯函数引擎；能力以注册新 post-process 步骤 / 新 context 段的方式接入，不改 agent_service。
6. **分层单向依赖**：`api → application → services → repositories → core`；`api` 禁依赖 repositories/langchain；业务层禁直接操作 ORM。
7. **Agent Runtime 单管线**：三种 Run Profile（foreground_chat/autonomous_tick/event_driven）在 `profiles.py` 唯一声明，禁止另开阶段序列——"无第二套 Agent Pipeline"。
8. **关系账本与状态分离**：`relationship_events`（账本，时序权威）与 `relationship_state`（当前态，强一致 upsert）+ `relationship_snapshots`（版本化快照，可逐字节重放）。
9. **单一写面纪律**：计划落库只经 `goal_repository` 计划面；行动写世界只走 `deferred_world_op → outbox → world_engine` 唯一路径；Run 唯一写面 = `loop_runs`。
10. **能力是手脚不是逻辑**：`Capability` 只执行不做决策，调度权/重试/回复生成在引擎（ActionEngine/AutonomyEngine）；`ToolRegistry`/`CapabilityRegistry` 代码注册非热插拔。
11. **前台/后台同一决策代码路径**：统一 `decision_pipeline`，前台目标栈只读（长期化写入只发生在后台）。
12. **邮箱验证码登录（Redis + EmailSender 端口，2026-09-27）**：验证码是短命一次性状态，存 Redis（GETDEL 单次消费 / SETNX 冷却 / INCR 频控），不建 PG 表；发件走 `EmailSender` 协议（MVP = SMTP 163），换云厂商只加实现类；任意邮箱校验通过即 find-or-create 用户行（多用户就绪，display_name 取邮箱前缀），令牌沿用无状态 HMAC 体系（原 `/auth/pair` 设备配对链路已随邮箱登录退役）。
13. **用户身份收口（token 唯一身份源，2026-09-27；默认用户概念整体退役 2026-09-28）**：产品端点（移动端实际调用面：chat / history / ledger / governance / proactive + 既有生活域六 router）的 `user_id` 一律经 `require_user` 从 Bearer token 解析，**不再回落 `default_user`**（V4.0.0「缺失回落 default_user 与现状逐字节一致」兼容裁决废止）。**IDENT-009（2026-09-28）：默认用户概念不再存在**——用户行一律由登录链路派生（邮箱 → `email-<sha256[:16]>`；通道 → `feishu:{open_id}`）。具体：①删 `settings.default_user` 字段与 `DEFAULT_USER` env 键；②删启动播种 `ensure_default_user()` / `upsert_default()`（空库冷启动不再造幽灵行）；③`/debug/*` 与 `/state`（共 20 个端点）的回落值由魔法 id 改为 **token 身份**（`user_id` 省略即取 `require_user`，显式传入可覆盖）；④删 `users.is_default` 列与唯一索引（迁移 `0058`；该列此前是纯装饰，全仓无查询用它）与 `UserContext.is_default`；⑤删一次性归并脚本 `adopt_owner_identity.py` 与 `resolve_user` 死代码。历史 owner 行的 id 迁移由 `scripts/migrate_owner_id_to_email.py` 承担（幂等 / 默认 dry-run，级联 `user_id` + `worlds.id` + `world_id`；**执行后所有已签发 token 失效**）。V4.0.0 任务册 §14 为本次登记。
14. **迁移链折叠为单迁移（2026-09-29）**：`migrations/versions/` 由 0001~0058（58 个增量）折叠为单一基线迁移 `0001_squashed_full_schema.py`（revision `0001`、`down_revision = None`），由 `Base.metadata` autogenerate 生成并人工校正（PG 分支保留 pgvector 扩展可用性守卫与 `idx_memories_embedding_hnsw` HNSW 索引；布尔默认值修正为 `sa.false()`；补回 0026 兜底约束；`VectorType` 以迁移内本地副本声明，不依赖 `app.core.db`，基线迁移自包含）。**前提**：项目处开发期、库可整库重建，无线上存量数据需保留；**旧库（≤`0058`）与新链不兼容，必须删库重跑 `alembic upgrade head`**。**顺带修正三处模型/迁移漂移**：①`character_goals.ck_character_goals_domain` 值域补 `budget`（旧链漏更，迁移库上写 budget 域目标会违约）；②`action_records.ix_action_records_user_id` 由 UNIQUE 改普通索引（对齐模型；旧链 0047 误建唯一索引）；③`uq_development_state_active_key` 部分唯一索引与 `ck_development_changes_subject` CHECK 补回 ORM 模型（此前仅存在于迁移、测试建表路径缺失）。迁移头钉测保持 `tests/support/schema_pins.py` 单点（折叠时 `MIGRATION_HEAD="0001"`，**现值 `"0002"`**——随 `0002_briefing_preferences` 入链同步）；v24 取证常量同步改写（`SQUASHED_MIGRATION_FILE` 等）。此后结构变更加 `0002+` 增量迁移，禁止再折叠除非再次整库重建。
15. **services 目录领域化重组（2026-09-30）**：裁决「领域优先 + 引擎收口 + 统一去后缀」——①49 个顶层散落单文件模块按业务领域收进领域子包（goal / relationship / conversation / evaluation / delivery / autonomy 等），`goal_planning` 不并入 `planning/`（Goal 写面与 Planning 白名单分域）；②无 IO / 无 LLM / 无 DB 的纯函数模块收口 `app/engines/`（**独立层，与 services 平级**，落地 `target-architecture.md` §2 目标态），依赖规则 = 只允许 models / core.settings / core.constants / 纯数据资产，禁止 repositories / chains / services 业务模块 / 任何 IO；③文件名去 `_service` / `_engine` 等后缀（已有子包内文件不改名）；④`services/__init__.py` 落 PEP 562 惰性门面；⑤`governance/` 6→2、`analytics/` `tasks/` 命名空间包并入相邻领域包。**债清偿两阶段**：⑥**`services → application` 反向依赖清零**（2026-09-30）——改「服务侧端口模块 + PEP 562 `__getattr__` 代理」形态（组合根 = `main.py` lifespan + `tests/conftest.py`），纯工具下沉 `core/`（`core/clock.py` 时钟、`core/runtime_state.py` 写锁 / 运行态），`memory/job_worker` 改 job handler 注册表；唯一豁免 = `agent_service.py` 兼容壳本体（随壳退役消失）。**打桩铁律：一律打实现模块（如 `app.application.world_engine.X`），不打端口**——端口 `__getattr__` 与 monkeypatch 组合会把 getattr 快照永久写进端口字典而遮蔽代理。⑦**巨型文件包化 2/5**：`evaluation/context.py` → `evaluation/context/`、`reflection/evidence.py` → `reflection/evidence/`（`{windows,collectors}`，`__init__` 全量再导出以保消费面零改动）；`planning/observer.py` 审计后判定不拆。方案与逐文件映射见 `docs/refactor/services-reorganization-plan.md`。
16. **ID 体系改用雪花 ID（2026-10-03）**：原 `user_id` 是**凭据的派生值**（邮箱 → `email-<sha256[:16]>`；通道 → `feishu:{open_id}`），导致四类结构性问题：①改绑邮箱即换人（旧行数据成孤儿）；②跨通道无法归一（`channel_identities.internal_user_id` 自身即派生串，映射表退化为自映射，同一人飞书 + 邮箱 = 两套记忆/关系/账本）；③ID 可由邮箱反推，间接泄露「某邮箱已注册」；④业务主键内嵌 `user_id`（`car_profile_{user_id}` / `task_{user_id}_{ms}` / `worlds.id = home:{user_id}`），每次身份口径变化都要全库级联改写（`scripts/migrate_owner_id_to_email.py` 即此代价的实证）。**裁决**：全仓 ID 统一由**雪花 ID** 生成，**禁止自研位运算，采用 `sonyflake` 2.0.3**（`_elapsed_time` 单调只增不减，时钟回拨时 ID 时间不回退、序列耗尽则借位到未来并等待真实时间追上；`aiologic.Lock` 同步/异步通用）。**参数**：epoch `2026-01-01T00:00:00Z`（**一次性决策，有数据后不可改**）、`bits_sequence=12` / `bits_machine_id=10` → `time_bits=41`（库计算）、`time_unit=1ms`；容量 4096 ID/毫秒/机器、1024 机器，**可用至 2095-09-07**。唯一发号入口 = `app/core/ids.py`（`new_id()` / `new_id_async()`），配置域 = `core/settings/ids.py`（`IDS_EPOCH_DATE` / `IDS_MACHINE_ID` / `IDS_HIGH_WATER_*` / `IDS_CLOCK_ROLLBACK_TOLERANCE_MS`）。**时钟回拨防护四层**：L1 进程内 = 库的单调逻辑时钟；L2 跨重启 = 内存水位（由 `decompose().time` 反解**逻辑**时间，非墙钟）每 5s + 关停时写入 Redis（key 按 `machine_id` 隔离），启动 `startup_guard()` 读回，`now < 水位 - tolerance` 则抛 `ClockRollbackError` **拒绝启动**（Redis 不可用时降级跳过 + 告警，不阻塞启动）；L3 部署约定 = 必须启 NTP 且只允许 slew 禁止 `ntpdate` 跳变、禁虚拟机快照回滚、**多实例 `IDS_MACHINE_ID` 必须互异且同一 id 不得同时被两实例使用**、监控「水位 > 墙钟」；L4 兜底 = DB 主键唯一约束，**禁止**冲突时静默重试。**执行分两步，B2 已评估后取消**：**B1（本次已落地）** = 发号模块 + 配置 + 接线 + 单测，并让身份域改用雪花（`user_id` 的 Python/API 类型**保持 `str`**，值为雪花十进制串，故 `users.id` 与 37 张 `user_id` 列仍是 `VARCHAR`）；**B2（2026-10-03 评估后主动取消）** = 列类型翻转 `VARCHAR → BIGINT`——实测收益只剩「DB 类型层强制 ID 为数字」，成本为 584 处测试字面量（180 文件）+ 删库重建，且与 B1 的自愈路径矛盾，故**保留 `VARCHAR`**；需要强约束时改在应用边界校验（详见 §9）。**ID 出 JSON 必须为字符串**（JS 精度，硬约束）。方案、库选型对比（6 个候选实测）与实测证据见 `docs/refactor/identity-and-id-scheme.md`。

---

## 11. Future Evolution Direction

基于当前架构，下一阶段演进方向（均为规划，非现状）：

### 11.1 Agent Runtime

- 在 `profiles.py` Profile Registry 上扩展新 run_kind / 阶段序列，而非新增第二套管线。
- 强化 `agent_state_assembler` 快照装配与 `llm_gateway` 的预算/降级策略，支持更细粒度的 Run 成本与质量观测。
- `agent_metric_snapshots` + `agent_evolution_worker` 已具备指标快照与人格编译骨架，可继续深化 Self Improvement 闭环。

### 11.2 Memory Evolution

- 在 `memory2`（7 类型 + 生命周期 + 混合检索）与 `reflection`/`development` 之上，引入显式 **Episodic Memory**（按时间线组织的情景事件）与 **Semantic Memory**（跨事件抽象的概念/偏好）双通道。
- 复用 `memory_candidates`（四源摄取 + 幂等）、`embeddings`（向量）、`retriever`（混合排序）作为检索底座。

### 11.3 Evaluation System

- 现有 `evaluation_reports` / `services/agent_evaluation.py` / `evaluation_rules/`（persona/emotion/relationship/goal/behavior/action/autonomy/memory/reflection/development 多域规则）+ `chains/evaluation_judge_chain.py` 已构成规则 + LLM Judge 双路评估骨架。
- 方向为：把离线评估（`memory2/offline_metrics`、`relationship_evaluation`、`reflection/evaluation`）与在线评估统一，形成持续回归 + 门槛门控的评估闭环。

---

> **文档结束**。本文档为当前系统架构唯一可信基线；后续任何架构演进请先更新本基线，再进入开发。
