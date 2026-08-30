# Roleplay V8 任务注册表

> **状态（2026-08-31）**：V8-001~014 全部完成（全量 1120+ 绿）；另按实现指令新增 **V8-015 World Consistency 评估规则**（用户新增集成需求）。
> 执行策略：逐 Task 测试 + 全量回归（V1~V7.8 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：World 是旁路——任何 Task 不得改变聊天 / 主动 / 评估链路的既有行为；**空世界时 prompt 字节不变（golden 守门）**；World 对 Character 状态零写回；一切开关与阈值进 `core/settings.py` world_* 组；世界失败只降级。

## Task 列表

### V8-001 World 域模型 + world_* 配置组（P0）

- **目标**：`app/models/world.py` 全套域模型（World / WorldObject / WorldLocation / WorldEnvironment / WorldEvent / TimeContext / LocationContext / WorldContext / StateSnapshot + WorldTimeMode/EntityCategory/EventStatus/ObjectStatus 枚举）+ settings world_* 组（16 项）+ 角色资产 `app/character/asuna/world.py`（home 布局、物品状态机、环境词表、动作词表）。
- **范围**：models/world.py（新增）、core/settings.py、character/asuna/world.py、conftest（override_settings env_map 增 world 键）；不碰任何 service / chain。
- **依赖**：无。
- **实现要点**：world-model.md §2、object-system.md §3（状态机为数据定义）、time-system.md §2（part_of_day 边界表）；有界工具复用 observability 的 bound_extra/bound_text（import 复用，不重写）。
- **验收标准**：模型构造与校验（枚举边界、quantity [0,∞)、事件时间合法性）；配置组默认值加载与 env 覆盖；状态机纯函数（合法迁移/非法返回 None）。
- **测试**：`tests/unit/test_world_models.py`、`tests/unit/test_world_transitions.py`。

### V8-002 World Persistence + World State Manager（P0）

- **目标**：迁移 0017 四表（worlds / world_entities / world_events / world_snapshots）+ `world_repository` + `app/application/world_engine.py`（WorldEngine：ensure_world 幂等创建、快照、事件/实体查询封装）+ `/debug/world` 查询端点。
- **范围**：migrations/0017、world_repository、world_engine、api/v1/world.py（新增 router）、api/v1/router.py（H7）；ensure_world 建默认 home 世界（全空环境/实体/事件）。
- **依赖**：V8-001。
- **实现要点**：persistence.md §2/§5；ensure 幂等（user_id 唯一约束 + 惰性创建）；active 实体/事件上限拒新建。
- **验收标准**：alembic 往返；ensure 幂等；JSON 列读写往返；手动播种端点可用；world_enabled=false 时引擎全短路。
- **测试**：`tests/integration/test_world_repository.py`、`tests/integration/test_world_engine.py`、`tests/e2e/test_debug_world.py`。

### V8-003 Time System（P0）

- **目标**：TimeProvider（real_sync 实现 + simulated/story 分支预留）+ TimeContext 装配 + TimeEvent（到期事件/过期物品）接入世界装配。
- **范围**：services/world/time_provider.py、world_engine 装配集成；**不接管**既有 datetime.now() 消费者（V6/V7 语义不动）。
- **依赖**：V8-002。
- **实现要点**：time-system.md §1~§3；simulated 惰性推进（上次推进戳 + 速率）；part_of_day 边界表驱动。
- **验收标准**：real_sync 下 TimeContext 与真实时钟一致；simulated/story 单测（注入推进）；时段边界矩阵。
- **测试**：`tests/unit/test_world_time.py`、`tests/v8/test_time_simulation.py`。

### V8-004 Location System（P0）

- **目标**：LocationContext 装配（current/path/available_actions/traits）+ worlds.current_location 迁移支持 + 地点约束 note（动作与地点不符时不造事实）。
- **范围**：services/world（location 装配函数）、world_engine、解释器预留迁移入口；资产布局来自 V8-001。
- **依赖**：V8-002（资产来自 001）。
- **实现要点**：location-system.md §2~§4/§6；不读写 scene_state.location；未知目标地点拒绝迁移。
- **验收标准**：层级路径渲染（"家·厨房"）；available_actions 按资产词表；跨层级跳转产生 note；与 scene_state 零耦合（测试断言不触其仓储）。
- **测试**：`tests/unit/test_world_location.py`、`tests/integration/test_world_location_move.py`。

### V8-005 Object State System（P0，核心）

- **目标**：world_entities 全生命周期（Created/Moved/Used/Changed/Destroyed）+ 状态机应用 + 数量演化 + expiry 时间演化 + 仓储查询（按位置/按最近动作）。
- **范围**：services/world/transitions.py（纯函数）、world_engine 实体操作、world_repository 实体查询；解释器接口先行（消费方 006）。
- **依赖**：V8-002、V8-004（位置）。
- **实现要点**：object-system.md §2~§6；quantity 两位小数、下限 0；destroyed 保留行；due 检查驱动 expire 幂等；last_action_at 审计。
- **验收标准**：西瓜全链状态迁移正确；非法迁移拒绝；数量扣减规则来自资产（default_portions）；过期由时间触发且单次。
- **测试**：`tests/unit/test_world_transitions.py`（补充数量）、`tests/integration/test_world_objects.py`。

### V8-006 World Update Interpreter + post_process 第 8 步（P0）

- **目标**：确定性规则解释器（用户消息 + 世界现状 → 迁移/事件/环境/地点变更）+ `run_world_update` 成为 post_process 第 8 步 + notes 短期回写（本轮说、下轮知道）。
- **范围**：services/world/interpreter.py（动词模式 + 实体匹配 + 事件时间提取规则）、services/world/memory_bridge.py 骨架（P1 填充）、post_process.py（STEP_HANDLERS 追加，官方扩展点）、world_engine 编排；**LLM 辅助链仅留接口与配置，默认关**。
- **依赖**：V8-005、V8-004。
- **实现要点**：world-model.md §4 白名单与"宁缺毋滥"；确定性优先，模糊输入零迁移；due 检查顺带执行（事件触发 + 物品过期）；迁移与 note 有界；失败只 log 不冒泡。
- **验收标准**：既定场景消息（拿/切/吃/买/放回/明天面试/外面下雨）产出正确迁移；无匹配消息零迁移；第 8 步异常不影响既有 7 步（负向注入）；STEP_HANDLERS 追加不破坏既有断言（涉及处逐条列明）。
- **测试**：`tests/unit/test_world_interpreter.py`、`tests/integration/test_world_update_step.py`。

### V8-007 World Context Builder + Prompt 挂载（P0 收口）

- **目标**：WorldContextSelector（切片规则 + 预算）+ `render_world_section` 纯函数 + chat_pipeline H1 挂载 + PromptBuilder/answer_chain 可选 world_ctx 参数（H2/H3）+ trace step `world_context`。
- **范围**：services/world/context_selector.py、prompts/builder.py（build 增 world_ctx=None）、answer_chain（透传）、chat_pipeline（+1 行装配）、trace_collector TRACE_STEP_NAMES 增名；**golden 字节不变是硬闸**。
- **依赖**：V8-003 ~ V8-006。
- **实现要点**：context-builder.md §2~§4；世界段独立预算不参与 _fit_variable_parts；world_ctx=None 与空切片同渲染 None；选择器/渲染纯函数表驱动。
- **验收标准**：空世界时全部 golden 字节不变；有世界数据时【当前世界】段 ≤ 预算且内容正确；切片排除矩阵（非邻近物品/低重要度完结事件不进）；装配异常降级为 None 不影响回答；**全量回归零失败（P0 收口）**。
- **测试**：`tests/unit/test_world_context_selector.py`、`tests/unit/test_world_render.py`、`tests/v8/test_context_builder.py`、`tests/e2e/test_world_chat.py`。

### V8-008 Event System（P1）

- **目标**：world_events 全生命周期（Create/Schedule/Trigger/Complete/Cancel/Expire）+ due 检查（turn 内 + lifespan 循环）+ EventTimeline 查询视图 + /debug/world 事件端点。
- **范围**：world_engine 事件编排、main.py lifespan（world_enabled 门控，H6）、interpreter 事件规则接线（来自 006）；宽限期 auto-expired。
- **依赖**：V8-006。
- **实现要点**：event-system.md §2~§5；触发幂等（单次）；活跃上限；**不触碰 V7 trigger_evaluator / proactive_actions**。
- **验收标准**：面试全链（陈述→scheduled→due 触发→active→"面完了"→completed）正确；跨宕机补触发一次且幂等；V7 全部测试零回归。
- **测试**：`tests/integration/test_world_events.py`、`tests/v8/test_event_trigger.py`。

### V8-009 Environment System（P1）

- **目标**：environment JSON 读写（manual 端点 + interpreter 确定性陈述 + lighting 随时段建议）+ 环境词表与效果提示进选择器/渲染。
- **范围**：world_engine 环境操作、资产 ENVIRONMENT_EFFECT_LEXICON、/debug/world 环境端点；**不实现真实天气 API**（接口注释级预留）。
- **依赖**：V8-006、V8-007。
- **实现要点**：environment-system.md §2~§3；全空环境不渲染；建议值可被 manual 覆盖。
- **验收标准**："外面下雨了" → weather=rain 下一轮可见；manual 设置即时可见；情绪系统零写回（专项断言）。
- **测试**：`tests/integration/test_world_environment.py`。

### V8-010 Memory Integration（P1）

- **目标**：memory_bridge 完整实现（completed + importance≥normal → 记忆候选 → 既有 memory 仓储）+ 边界表固化 + materialized 幂等标志。
- **范围**：services/world/memory_bridge.py（to_memory_candidates 纯函数 + 投递）、world_engine 第 8 步收尾接线；**不改 memory_service/extractor**。
- **依赖**：V8-008。
- **实现要点**：memory-integration.md §2~§3；importance 映射进 world_memory_importance_json；单事件 1 条候选。
- **验收标准**：面试完结后 memories 出现 source=world_event 记录；物品变化/取消事件零沉淀；重复投递跳过；V4 记忆测试零回归。
- **测试**：`tests/unit/test_world_memory_bridge.py`、`tests/integration/test_world_memory_materialization.py`。

### V8-011 Autonomy Integration（P1）

- **目标**：collect_facts 只读事实包 + PolicySnapshot.world_facts（默认空）+ policy 追加 world 修饰规则（W1 提议增强 / W2 克制 / W3 不可拆闸门，纯函数）。
- **范围**：world_engine.collect_facts、autonomy_engine._snapshot_for（H5）、autonomy_policy（可选参数 + 追加纯函数）；**不新增触发类型、不动 proactive 文本生成**。
- **依赖**：V8-008。
- **实现要点**：autonomy-integration.md §1~§3；facts 装配失败 → 空包；八步裁决闸门不变。
- **验收标准**：不传 world_facts 时 policy 输出与 V7 完全一致（既有测试零回归）；雨天/面试场景 reason 附加且闸门未被解除；V7.5 autonomy 维照常审计。
- **测试**：`tests/unit/test_autonomy_policy_world.py`、`tests/integration/test_world_autonomy_facts.py`。

### V8-012 tests/v8/ 场景套件 + 性能护栏（P1）

- **目标**：声明式场景（scenarios/*.json：西瓜全链 / 面试全链 / 雨天自治，各含正反例）+ `test_world_state/object_lifecycle/time_simulation/event_trigger/context_builder` 五套件归位 + `test_performance.py`（装配 <10ms·轮 / 热路径无解释器写 / world_facts 降级零影响）。
- **范围**：tests/v8/（新增）。
- **依赖**：V8-001 ~ V8-011。
- **实现要点**：testing.md §2/§4；时间冻结注入 FakeTimeProvider；全部确定性（无真实 LLM）。
- **验收标准**：单命令可跑全绿；三主线场景期望终态/渲染片段断言通过；性能预算断言常驻守门。
- **测试**：即本 Task。

### V8-013 快照回滚 + 历史查询（P2）

- **目标**：save_snapshot 自动采样（显著迁移限频）+ restore（恢复前自动留存"恢复前"快照）+ /debug/world/snapshots 端点（列表/详情/恢复）。
- **范围**：world_engine 快照/恢复、api/v1/world.py；Character 状态不回滚（文档化语义）。
- **依赖**：V8-002、V8-008。
- **实现要点**：persistence.md §3；每世界 ≤20 份限频；恢复动作幂等可审计。
- **测试**：`tests/integration/test_world_snapshots.py`、`tests/e2e/test_debug_world_snapshots.py`。

### V8-014 真实模型人工回归清单（P2，仅文档）

- **目标**：`docs/roleplay-v8/regression-checklist.md`——开关矩阵、西瓜/面试/雨天三条真实模型演练、世界段 prompt 抽查、快照恢复演练、体积观察项。
- **范围**：仅文档；组织方式沿用 V4/V7/V7.5/V7.8 回归清单。
- **依赖**：V8-001 ~ V8-013。
- **测试**：无（人工执行）。

## 依赖图

```text
001 域模型+配置 ─ 002 持久化+引擎 ─┬─ 003 时间 ──┐
                                  ├─ 004 地点 ──┼─ 005 物品 ── 006 解释器+第8步 ── 007 Context Builder（P0 收口）
                                  └─────────────┘                    │
                                        008 事件（←006）──────────────┤
                                        009 环境（←006+007）           │
                                        010 记忆桥（←008）             │
                                        011 自治事实（←008）           │
                                        012 场景套件+性能（←全部）      │
                                        013 快照回滚（←002+008）       │
                                        014 人工回归清单（←全部）
```

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V8-XXX <中文描述>`。
- V8-007 是 P0 收口点：合并前必须全量回归零失败（既有 1050+ 测试 + 新增），golden 字节不变。
- P0 链（001→007）完成后系统即具备"世界存在且进入上下文"的能力；P1 五项补齐演化与集成；014 最后执行。

## 完成状态回写（2026-08-31，实现阶段）

| Task | 提交 | 备注 |
|---|---|---|
| V8-001 | 819d8a3 | 域模型 + 17 项 world_* 配置 + home 布局/状态机/词表角色资产 |
| V8-002 | baf727f + 8d53eb4 | 迁移 0017 四表 + 仓储 + WorldEngine + /debug/world |
| V8-003 | 4fcccc1 | TimeProvider 三模式（story/simulated 显式 advance，rate 缩放） |
| V8-004 | 295fbb1 | 地点装配/别名解析 + scene_state 零耦合断言 |
| V8-005 | f6eb52c + 后续 fix | 物品全生命周期；food 状态机支持连续食用 |
| V8-006 | eb6a6d1 | 确定性解释器 + post_process 第 8 步 + 指代回退（单实体）/问句守卫 |
| V8-007 | e2e2dec | P0 收口：selector/render + world_ctx 可选参数链 + golden 不变 |
| V8-008 | 079c2eb | 事件全生命周期 + lifespan 维护循环 + 保留清理 |
| V8-009 | 6228a79 | 环境写回（interpreter/system/manual 三源）+ 情绪零写回断言 |
| V8-010 | 9fe3680 | memory_bridge 单向投递 + materialized 幂等 |
| V8-011 | b416110 | world_facts 进 PolicySnapshot + W1/W2/W3 修饰规则 |
| V8-012 | ed51f4d | tests/v8/ 声明式三主线场景 + 五套件 + 性能护栏 |
| V8-013 | ed793d1 | restore 整包回滚（恢复前自动留存）+ 历史查询端点 |
| V8-014 | 本次提交 | regression-checklist.md 文档 |
| V8-015 | bc7fa9c | 实现指令新增：World Consistency 评估规则（info 级，问句豁免） |

实现期口径补充（与设计的差异）：
- worlds.id 采用 `home:{user_id}`（设计文档的 id="home"+unique(user_id) 无法满足 PK 唯一）。
- 解释器含"最近单实体指代回退 + 问句守卫"（口语代词省略的确定性解法）。
- 记忆沉淀 source 落 user_derived（V4 仓储 source 白名单不含 world_event）。
- V7.8 性能守门测试在 world_enabled=false 下运行（世界段含实时时间，避免字节对比抖动）。
