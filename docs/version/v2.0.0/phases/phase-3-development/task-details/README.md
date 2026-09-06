# Phase 3 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) DEV-001~006 一一对应，无遗漏。所有 Detail 锚定 Phase 1/2 真实实现（基线：`feat/v2.0.0` @ d6d3f8b，MEM-001~011 与 REF-001~007 已全部提交，迁移链至 0025_reflection_foundation），未与 v2.0.0 Architecture / Phase 3 architecture.md 冲突，未提前设计 Phase 4~6 能力。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| DEV-001 | [DEV-001.md](DEV-001.md) | Foundation | 无（可并行；schema 风格对齐 REF-001） | migrations/versions 0025→0026、core/db.py InsightRow 模式（L834）、reflection/lifecycle.py TRANSITIONS 状态机模式（L36/L51）、settings.py v2_reflection_* 块（L137） |
| DEV-002 | [DEV-002.md](DEV-002.md) | Core/编译器 | DEV-001, REF-004 | reflection/reflector.py `_persist`（L276）、reflection/lifecycle.py 失效事件钩子（L207-228）、memory2/job_worker.py `register_job_type`（L41）、memory2/evaluator.py 结构化链模式 |
| DEV-003 | [DEV-003.md](DEV-003.md) | Integration/接线 | DEV-002 | application/chat_pipeline.py L152/L286、behavior_engine.py `resolve`（L270）/`match_habits`（L197）/`_apply_relationship_modifiers` 先例（L226）、goal_service.py `_effective_tier`（L240）、chains/answer_chain.py L36、context_builder.py `_load_context_insights` 先例（L73） |
| DEV-004 | [DEV-004.md](DEV-004.md) | Integration/回退重放 | DEV-002, REF-005 | reflection/lifecycle.py `register_invalidation_listener`（L210）/`notify_invalidation_listeners`（L219）、memory2/job_worker 协议、scripts/ 既有入口风格 |
| DEV-005 | [DEV-005.md](DEV-005.md) | Observability/Evaluation | DEV-003（覆盖全链） | trace_collector.py TRACE_STEP_NAMES（L13）、api/v1/debug.py 归因端点（L27/L43）、evaluation_rules/reflection.py 三规则模式、reflection/evaluation.py SCENARIOS 三层结构、offline_evaluator.py `_reflection_stats`（L200）、tests/unit/test_evaluation_models.py ISSUE_CODE_COUNT（L25） |
| DEV-006 | [DEV-006.md](DEV-006.md) | Evaluation/长周期 | DEV-003, REF-006, MEM-010 | development/evaluation.py 场景框架（DEV-005 交付）、tests/eval/ 运行器、reflection/evaluation.py 注入式 runner 模式 |

---

## 与 Phase 1/2 实现 / 既有架构的核对记录（冲突与口径登记，不修改架构）

> 按「发现冲突先记录、不自行修改架构」的要求逐条登记。各项均为 Task Detail 内已给出落地口径的偏差/缺口，供实施前评审确认。

1. **ResponseStyleController 在代码中不存在**。tasks.md DEV-003 Scope 与 architecture §2 数据流的 `RS[ResponseStyleController]` 无对应模块（全库 grep `response_style` 零命中；现存的风格承载 = 行为指令/语气行 `prompts/behavior.py` + 全局 `answer_max_tokens`）。落地口径：不新建模块、不扩大需求——长度调制 = DEV-003 在 `answer_chain` 既有 `bind(max_tokens=...)` 处按轮注入 overlay 偏移（clamp 下限保护）；语气调制 = `BehaviorDirective` 追加可选 `development_style` 字段由 `prompts/behavior.py` 渲染。两者均为 version-boundary Extend 点，E-DEV-02 的 before/after trace 在两处均可观测。建议：若评审认为需要独立 ResponseStyleController 模块，属需求变更，另行裁决。
2. **「新 active Insight 事件」P2 未交付**。REF-004 `_persist`（L276）commit 后仅向 `notify_invalidation_listeners` 广播 superseded 半边；创建事件无广播。DEV-002 需要该事件作为编译触发（tasks.md Runtime Flow 首环）。落地口径：`reflection/lifecycle.py` 镜像失效钩子三函数新增 `register_insight_created_listener` / `notify_insight_created_listeners`（同一注册模式、P2 语义零改动、无注册方零行为），`_persist` 增加一行 commit 后广播；编排层（`main.py` lifespan，`v2_development_enabled` 门控）注册消费方 → enqueue `development_compile` job（MEM-009 协议）。这是对 Phase 2 交付面的最小扩展而非架构变更（事件钩子模式是 REF-005 已裁决的跨域订阅方式）。
3. **「BehaviorPolicy 关心话题权重」在 v1/v6.5 代码中无对应结构**。`BEHAVIOR_POLICY` 资产（`character/asuna/behavior_policy.py`）只有 stage_params/mood_modifiers；`INTENTION_STRATEGY_MAP` 是意图→策略映射。落地口径：care_topics 调制以「goal 层 user_care tier 有界 delta（goal_service `_effective_tier` 读取侧）+ care 提示 prompt 行（behavior 段追加渲染）」承载，不修改 BEHAVIOR_POLICY 资产结构（version-boundary Preserve）；topic 识别走 settings 关键词规则表（确定性，与 Phase 3「纯函数编译」约束一致）。E-DEV-02 的「关心话题权重↑」验收以此口径执行。
4. **AutonomyPolicy 时间偏好参数本 Phase 只编译落库、不接线**。architecture §2 数据流只有 D→BP/RS/G/CTX 四条消费箭头（无 D→Autonomy）；tasks.md DEV-003 Scope 亦只列 BehaviorEngine/ResponseStyle/goal_service。落地口径：`autonomy.time_preference` 槽位由 DEV-002 编译进 development_state（可审计、可回退），运行时消费属 P5 Life Loop（dependency-graph P3→P5）。Phase 3 内任何 Detail 不设计 autonomy 接线。
5. **development_state 同 (user,key) active 唯一的实现口径**。服务层条件 UPDATE（带 `status='active'`，0 行即 no-op）+ per-user 写锁串行化为主；部分唯一索引 `(user_id,key) WHERE status='active'` 为兜底（PG 生产与 SQLite≥3.8 测试均支持 dialect-where）。实施前复核两库行为，若 SQLite 兜底库版本不支持则降级为纯服务层保证（一致性由 E-DEV-03 评估兜底）。
6. **strength 语义 = 源 Insight confidence 直接映射，不设计叠加累积公式**。「同主题 10 条强化 Insight 幅度仍封顶」由「幅度 = strength × 预设最大幅度、confidence 终值 REF-004 已封顶 0.95」天然成立；叠加公式（计数/时间加权）会破坏「时间序重放确定性」与 E-DEV-01 幂等验收。强化语义由 REF-004 侧表达：新证据 → 新 Insight（confidence 演进）→ 仲裁自然胜出。
7. **重放「删 changes 后按 Insight 时间序重编译」（data-flow §2.3）与 tasks.md Non-Scope「重放不改原始审计行」的表面张力**。落地口径：重放工具默认**校验模式**——单事务内重建 state+changes 并与在线态比对，事务回滚（原始审计行零改动，输出比对报告，满足「重放=在线」验收）；`--rebuild` 显式模式才 commit 重建（仅审计行损坏修复、停写窗口执行）。两处文档语义各自成立，无架构修改。
8. **Context 调制摘要段的归属**。context-architecture.md §1 将 P2 Development 段（≤100 字符）划给 DEV-003（「DEV-003 调制摘要，P3 后」），architecture §2 数据流含 D→CTX 箭头，但 tasks.md DEV-003 Scope 文本未列 Context 消费。落地口径：按 architecture 处理——DEV-003 附带交付该段（Flag 门控、≤100 字符、内容为调制结论摘要、与 REF-007 insight 段内容正交不重复、空则字符串不出现）。判定为文档间对齐而非范围扩大；若评审认为应移出 Phase 3，仅删 DEV-003 设计 3 一节即可，不影响其余交付。
9. **迁移号为 0026**（0025_reflection_foundation 已占用，Phase 1 类型扩列曾致 0024 顺延，沿 Phase 2 task-details README 同款登记）。DEV-001 Detail 全文按 0026 书写。
10. **trace 步骤名注册时点**。`TurnTraceSession.record` 不校验 TRACE_STEP_NAMES 名单，DEV-001~004 以 record 直写不影响运行；DEV-005 统一补注册 4 个 development_* 步骤名并锁定 payload 规范——与 P2「REF-006 集中收口 trace」的交付节奏一致。
11. **IssueCode 计数常量 30→34**。DEV-005 追加 4 码后须同步 `tests/unit/test_evaluation_models.py` ISSUE_CODE_COUNT（REF-006 曾 27→30，同款收口动作）。

---

## 一致性终检结论（生成时点）

- tasks.md DEV-001~006 每个 Task 均有 Detail，Task ID 完整一致；M1→M4 交付序与各 Detail 依赖声明吻合（DEV-001 可并行 → DEV-002 等 REF-004 → DEV-003/DEV-004 → DEV-005/DEV-006 → Eval Gate + Regression Gate → 申请开启 `v2_development_enabled`）。
- 全部 Detail 与 v2.0.0 README/architecture（domain-boundaries/data-flow/context-architecture/evaluation/character-runtime/version-boundary）及 Phase 3 architecture.md 的边界裁决一致：Development 只写本域两表、只读经 Reflection 验证的 Insight（禁止直读 memories）、调制为参数注入不改公式与静态资产、变更全审计可重放、0 新增 LLM（DevPolicy 纯函数，Judge 采样仅评估面）、Flag OFF 冻结且行为与 v1 字节级一致。
- 全部 Detail 基于 Phase 1/2 已提交实现（基线 d6d3f8b，MEM-001~011 + REF-001~007 齐、迁移链至 0025）设计，未假设不存在的接口；对 REF-004/REF-005 交付面的唯一扩展（Insight 创建事件钩子）已在核对记录 2 显式登记并给出最小落地口径。
- 未提前设计 Phase 4~6：Detail 中出现的 Relationship Patterns（REL-003）、Life Loop/Autonomy 接线、Goal 层级化（P6）均仅以「后续消费方/不在本 Phase」身份出现，无任何前置实现设计；DEV-006 的 goal 调制仅限 DEV-002 已定义槽位。
