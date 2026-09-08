# Roleplay V9 任务注册表

> **状态（2026-09-01）**：V9-001~010 全部完成并推送（tests/v9 全绿，场景套件/性能护栏收口于 V9-010）；人工回归清单待真模型执行。
> 执行策略：逐 Task 测试 + 全量回归（V1~V8.5 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：行动是旁路——任何 Task 不得改变聊天 / 主动 / 评估链路的既有行为；**`action_enabled=false` 时全链路逐字节回到 V8.5（golden 守门）**，开启时非行动消息也逐字节不变；V9 对 Character 状态零直写（关系只经 RelationshipEvent 通道）；一切阈值与开关进 `core/settings.py` action_* 组；行动失败只降级（回复照常）；检出与决策零新增 LLM 调用。

## Task 列表

### V9-001 Action Domain Model（P0）

- **目标**：`app/models/action.py` 全套域模型（ActionIntent / ActionPlan / ActionStep / ActionResult / ActionEffect / ActionRecord / CapabilityResult / ActionSchema + ActionType/ActionSource/ActionStatus/GateReason/FailureKind 枚举 + `transition_action` 六态迁移纯函数 + dedupe_key 规范化）+ settings action_* 组 19 项（含 autonomy_action_* 2 项）+ 角色资产 `app/character/asuna/action.py` 骨架（ACTION_TRIGGER_LEXICON 触发词表、REQUIRED_PARAMS 表、ACTION_CAPABILITY_MAP、ACTION_MEMORY_TEMPLATES、ACTION_RELATIONSHIP_MAP、完成时宣称模式表）。
- **范围**：models/action.py（新增）、core/settings.py、character/asuna/action.py、conftest（override_settings env_map 增 action 键）；不碰任何 service / chain / pipeline。
- **依赖**：无。
- **实现要点**：action-model.md §1~§3、architecture.md §6；状态机非法迁移返回 None（V8 物品状态机同款）；`*_json` 配置 + model_validator 校验（settings 既有惯例）；词表为数据定义（检出逻辑属 002）。
- **验收标准**：模型构造与校验（枚举边界、effects/status 合法值）；迁移表全格断言（合法/非法）；配置组默认值加载与 env 覆盖；dedupe_key 规范化等价类（语序无关、内容敏感）。
- **测试**：`tests/unit/test_action_models.py`。

### V9-002 Action Planner（P0）

- **目标**：`app/services/action/detector.py`（ActionIntentDetector：词表检出 + 祈使主语/问句守卫/单轮单意图 + 参数抽取）+ `app/services/action/time_parse.py`（时间短语 → due_at，扩展 V8 interpreter 既有"明天/后天/今晚"解析）+ `app/services/action/planner.py`（六闸门 evaluate_gates + assemble_plan 装配）+ chat_pipeline 检出挂载（H-A1：四链并行后 +3 行，进 turn_meta）。
- **范围**：services/action/detector.py、time_parse.py、planner.py（新增）、application/chat_pipeline.py（H-A1）、character/asuna/action.py（词表填充）；G3 闸门以注入的 registry 接口判定（测试用 fake registry，真实现属 003）。
- **依赖**：V9-001。
- **实现要点**：planner.md §1~§4；检出纯函数门控 `action_enabled and action_detector_enabled`、异常降级 None；检出**不进本轮 prompt**（只入 turn_meta）；trace 增 `action_detect` 记录（TRACE_STEP_NAMES 属 005，此处先按名记录）。
- **验收标准**：词表矩阵逐条（命中/不命中/问句/转述）；"提醒我晚上买牛奶"→confident 且 due 解析正确；"提醒我开会"→ambiguous + missing_params；六闸门正反例（fake registry）；action_enabled=false 时 chat_pipeline 输出与 V8.5 逐字节一致（turn_meta 增键需序列化守门）；非行动消息全链路字节不变。
- **测试**：`tests/unit/test_action_detector.py`、`tests/unit/test_action_time_parse.py`、`tests/unit/test_action_planner.py`、`tests/integration/test_action_detect_mount.py`。

### V9-003 Capability Registry（P0）

- **目标**：`app/services/action/registry.py`（Capability 协议 + CapabilityRegistry：注册/查询/schema 校验/describe）+ 四个真实现能力 `app/services/action/capabilities/`：reminder（→ world_engine.create_event/cancel_events_by_type，due_at 落 WorldEvent）、memory（→ 既有 memory_policy 校验 + memory_repository.create_memory，source=user_stated）、world_action（→ create_object/move_object/apply_object_action）、environment_query（→ TimeContext + WorldEnvironment 只读切片）+ search / notification 两个 unavailable 占位能力。
- **范围**：services/action/registry.py、capabilities/*.py（新增）；能力实现只调既有仓储/引擎 API，**world_engine / memory 仓储零修改**。
- **依赖**：V9-001（模型）；V8 既有引擎（ensure_world 兜底）。
- **实现要点**：capability-system.md §2~§4；ExecutionContext 只含 user_id/character_id/record_id/now/settings（对话与 prompt 不进能力）；execute 先写后返、返回 payload 只带 ID 与摘要；世界数据缺失时依赖世界的能力返回 unavailable。
- **验收标准**：注册表语义（重名拒绝/has/describe）；reminder→WorldEvent(scheduled, due_at 正确, source=autonomy)；memory→R1~R8 校验路径 + source 白名单内；world_action 三动作副作用正确；environment_query 零写断言；占位能力返回 unavailable。
- **测试**：`tests/unit/test_capability_registry.py`、`tests/unit/test_capabilities.py`。

### V9-004 Capability Executor + Persistence（P0）

- **目标**：`app/services/action/executor.py`（CapabilityExecutor：超时包裹 wait_for、异常归一、usage 统计）+ `app/application/action_engine.py`（create_record / execute_plan / integrate_result 骨架：四通道桥接位留空、效果登记先行）+ 迁移 0018 `action_records` 表 + `app/repositories/action_repository.py`（save/get/list_by_status/list_by_dedupe/count_active/retain_cleanup）。
- **范围**：services/action/executor.py、application/action_engine.py（新增）、migrations/0018、repositories/action_repository.py、conftest（迁移夹具）；integrate 四通道仅注册桥接接口（world/memory/relationship/note 桥实现在 005~008），本 Task 内效果清单登记与 note 桥最小实现。
- **依赖**：V9-002、V9-003。
- **实现要点**：execution-engine.md §1~§4；失败分类四态（transient/timeout 重试退避、permanent/unavailable 终态）；重试复用同 Record（attempt 递增）；per-user 写锁语义预留（锁在 005 接线时真正持有）。
- **验收标准**：执行全链（plan→executing→succeeded/failed）状态正确；超时→timeout 归一；退避曲线 backoff×2^n；permanent 不重试；alembic 往返；JSON 列（intent/steps/result）读写往返；保留清理。
- **测试**：`tests/unit/test_capability_executor.py`、`tests/integration/test_action_repository.py`。

### V9-005 Action Lifecycle（P0，收口）

- **目标**：post_process 第 9 步 `run_action_planning` 接线（STEP_HANDLERS 追加，锁内全链：create→gates→plan→execute→integrate）+ lifespan 重试/过期维护循环（run_action_retry_loop）+ 取消路径（cancel 记录 + /debug/actions POST）+ trace 步骤名（TRACE_STEP_NAMES 增 action_detect/action_execute，H-A4）+ `/debug/actions` 端点（列表/详情/手动重试/取消，H-A7）+ **Action Evaluation**（EvaluationDimension 扩 action 维、IssueCode 扩 action_overclaim/action_failed_unreported/action_plan_mismatch 三值、evaluation_rules/action.py 三规则、EvaluationContext 增 action 切片 `_collect_action`（H-A8）、权重表 action 行、evaluation_action_enabled 开关）。
- **范围**：application/post_process.py（第 9 步）、application/action_engine.py（编排收口）、main.py（lifespan 循环，action_enabled 门控）、services/trace_collector.py、services/evaluation_context.py、services/evaluation_rules/action.py（新增）、models/evaluation.py（扩值）、api/v1/action.py + router.py（H-A7）、core/settings.py（evaluation_action_*）；**STEP_HANDLERS 追加不破坏既有断言（涉及处逐条列明）**。
- **依赖**：V9-002、V9-003、V9-004。
- **实现要点**：action-model.md §3、execution-engine.md §1/§5、tool-integration.md §5；第 9 步在 per-user 写锁内（get_user_write_lock）；评估规则异常逐条隔离（run_rules 既有机制）；维度开关 getattr 默认 True 惯例。
- **验收标准**：全链生命周期（含否决 cancelled + gate_reason 落库）；维护循环重试与过期；三评估规则正反例（overclaim 用宣称模式表 × 无 succeeded 记录矩阵）；action 切片缺失时规则全跳过；/debug/actions 四端点；**全量回归零失败（P0 收口）**——action_enabled=false 下 golden 字节不变。
- **测试**：`tests/integration/test_action_lifecycle.py`、`tests/unit/test_evaluation_action.py`、`tests/e2e/test_debug_actions.py`。

### V9-006 World Integration（P1）

- **目标**：G6 闸门接真实世界快照（get_world/list_objects/list_events 注入 evaluate_gates，effect_already_satisfied / target_not_found 生效）+ 行动上下文段全链（services/action/context.py 装配 + render_action_section 纯函数 + PromptBuilder 可选 action_ctx + answer_chain 透传，H-A3，world_ctx 同构三连）+ 第 8→9 步双命中矩阵固化 + effect 宿主存在性校验（快照回滚后降级"已失效"）。
- **范围**：services/action/context.py（新增）、services/action/planner.py（快照装配）、prompts/builder.py（build 增 action_ctx=None）、chains/answer_chain.py（透传）、application/chat_pipeline.py（+1 行装配）；**golden 字节不变是硬闸**（无行动记录时 action_ctx=None）。
- **依赖**：V9-005；V8 既有世界引擎。
- **实现要点**：world-integration.md §2~§6、tool-integration.md §4；行动段独立预算不参与既有裁剪；cancelled（闸门否决）不进 prompt；选择规则表驱动（非终态 ≤3 + 最近终态 ≤2）。
- **验收标准**：双命中矩阵五格全对（叙事优先/委托补位/G6 兜底）；牛奶全链（委托→create_object→行动段→"喝掉"→use_object）；有行动数据时【行动】段 ≤ 预算且内容正确；无行动数据时全部 golden 字节不变；restore 后 effect 降级渲染；装配异常降级 None。
- **测试**：`tests/unit/test_action_context.py`、`tests/integration/test_action_world_bridge.py`、`tests/v9/test_action_world_update.py`（初版）。

### V9-007 Memory Integration（P1）

- **目标**：Action Memory Policy 完整落地（`action_memory_policy_json` 边界表 + to_memory_candidates 纯函数）+ `app/services/action/memory_bridge.py` 投递（既有 memory_policy R1~R8 校验 → memory_repository.create_memory，H-A9）+ remember_fact 双写合一查重 + effects 幂等 + 失败委托沉淀 + ACTION_MEMORY_TEMPLATES 模板填充。
- **范围**：services/action/memory_bridge.py（新增）、core/settings.py（边界表默认值）；**不改 memory_service / extractor / 既有 policy 规则**。
- **依赖**：V9-005。
- **实现要点**：memory-policy.md §2~§4；source 只用 user_stated / user_derived（R1 兼容）；单行动 ≤1 条候选；投递失败只 log 不回滚行动；importance 取值对齐 R5/R6 阈值。
- **验收标准**：边界表逐格断言（沉淀/不沉淀/importance/source）；ai_inferred 零出现（专项断言）；重复投递跳过（effects 判重）；"记住我生日"→ user_fact(0.8, user_stated) 单条；查询/使用类零沉淀；V4 记忆测试零回归。
- **测试**：`tests/unit/test_action_memory_bridge.py`、`tests/integration/test_action_memory_materialization.py`。

### V9-008 Relationship Integration（P1）

- **目标**：`app/services/action/relationship_bridge.py`（重要委托 succeeded → RelationshipEvent(user_help, normal)，autonomy 来源 → user_care weak；action_relationship_enabled 门控默认 false）+ 防双计规则（同 turn 对话 user_help 共存时行动信号让位，纯函数）+ 走既有三层钳制验证（event/turn/day cap）。
- **范围**：services/action/relationship_bridge.py（新增）、character/asuna/action.py（ACTION_RELATIONSHIP_MAP 填充）；**零直写 RelationshipState**（专项断言）；V8.5 兼容（无实现依赖，见 relationship-impact.md §6）。
- **依赖**：V9-005。
- **实现要点**：relationship-impact.md §2~§5；cause 固定模板 ≤50 字；投递在锁内、与第 2 步 state_update 互斥；默认 false 时零路径（调用计数断言）。
- **验收标准**：开关开启时信号映射逐格正确且经 commit_relationship_update 落库、钳制生效；同 turn 双计让位；关闭时关系状态与 V8.5 逐位一致；V5 全部关系测试零回归。
- **测试**：`tests/unit/test_action_relationship_bridge.py`、`tests/integration/test_action_relationship_pipeline.py`。

### V9-009 Autonomy Integration（P1）

- **目标**：`action_engine.collect_facts`（有界 action_facts 事实包）+ PolicySnapshot.action_facts（H-A5，默认空 dict）+ policy A1/A2 修饰规则（纯函数，只追加 reason 不拆闸门）+ `trigger_evaluator.poll_due_actions`（H-A6：active 的 reminder/appointment due → TriggerSignal(action_due)，优先级在 poll_due_followup 前）+ WorldEvent.payload.reported_by_autonomy 幂等标志 + PROACTIVE_ACTION_MAP 与自治产行动分支接口（autonomy_action_enabled 默认 false，仅接口与额度配置）。
- **范围**：application/action_engine.py（collect_facts）、application/autonomy_engine.py（_snapshot_for）、services/autonomy_policy.py（可选参数 + A 规则）、services/trigger_evaluator.py、core/settings.py（autonomy_action_*）；**八步裁决闸门零修改、proactive_executor 零修改**。
- **依赖**：V9-005、V9-006（due 事件来自 V8 世界）。
- **实现要点**：autonomy-integration.md §2~§5；facts 失败→空包；poll 幂等（payload 置位后不重报）；静音/冷却照旧不豁免。
- **验收标准**：不传 action_facts 时 policy 输出与 V8 逐位一致；A1/A2 正反例；提醒到期全链（succeeded→active→触发器一次→闸门→主动消息）；到期前取消/完成不再触发；autonomy_action_enabled=false 零路径；V7 全部测试零回归。
- **测试**：`tests/unit/test_autonomy_policy_action.py`、`tests/integration/test_action_autonomy_facts.py`、`tests/v9/test_autonomy_action.py`（初版）。

### V9-010 Testing 收口 + 人工回归清单（P2）

- **目标**：tests/v9/ 七套件归位补齐（planning / capability_system / execution_engine / action_world_update / action_memory_policy / autonomy_action / failure_recovery）+ 声明式场景（scenarios/*.json：牛奶全链 / 提醒全链 / 失败补救链，各含正反例）+ `test_performance.py` 性能护栏常驻断言（检出 <1ms、第 9 步 <50ms、渲染 <5ms、关闭路径调用计数=0）+ `docs/version/v1.0.0/v9/regression-checklist.md`（开关矩阵 + 三条真实模型演练：委托提醒 / 显式记忆 / 失败补救；行动段与宣称一致性抽查；/debug/actions 审计演练）。
- **范围**：tests/v9/（新增）、docs/version/v1.0.0/v9/regression-checklist.md（仅文档部分）。
- **依赖**：V9-001 ~ V9-009。
- **实现要点**：testing.md 全篇；时间敏感全部注入 FakeTimeProvider；全部确定性（无真实 LLM）；命名全局唯一（xdist）。
- **验收标准**：单命令可跑全绿；三主线场景期望终态断言通过；性能预算断言常驻守门；**全量回归零失败（V2~V8.5 专项抽测 + 全量）**；清单可人工执行。
- **测试**：即本 Task。

## 依赖图

```text
001 域模型+配置+资产 ──┬─ 002 Planner（检出+闸门+H-A1）──┐
                      └─ 003 Registry+能力 ── 004 Executor+持久化 ──┴─ 005 Lifecycle+评估（P0 收口）
                                                                       │
                                            ┌──────────────┬──────────┼─────────────┐
                                            006 世界集成     007 记忆桥   008 关系信号     009 自治集成（←006）
                                            （action_ctx）              （默认关）
                                            └──────────────┴──────────┴─────────────┘
                                                                     010 场景套件+性能+人工回归清单
```

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V9-XXX <中文描述>`。
- V9-005 是 P0 收口点：合并前必须全量回归零失败（既有 1120+ 测试 + 新增），`action_enabled=false` 下 golden 字节不变。
- P0 链（001→005）完成后系统即具备"检出→闸门→执行→留痕→评估"的完整最小闭环（默认关闭）；P1 四项补齐上下文可见性与双向集成；010 收口并交付人工回归清单。
- 与 V8.5 排期相互独立（V9-008 与 V8.5 无实现依赖）；若 V8.5 先落地，V9-008 验收追加"V8.5 全部测试零回归"。
