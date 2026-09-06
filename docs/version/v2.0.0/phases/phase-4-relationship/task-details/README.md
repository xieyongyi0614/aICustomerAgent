# Phase 4 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) REL-001~004 一一对应，无遗漏。所有 Detail 锚定 Phase 1/2/3 真实实现（基线：`feat/v2.0.0` @ 5540f4e，MEM-001~011、REF-001~007、DEV-001~006 已全部提交，迁移链至 0026_development_foundation），未与 v2.0.0 Architecture / Phase 4 README 冲突，未提前设计 Phase 5~6 能力。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| REL-001 | [REL-001.md](REL-001.md) | Core/转写通道 | P1 MEM-002, MEM-005（已交付） | memory2/ingest.py `ingest_from_relationship_event`（L241）/ sources.py `fetch_relationship_events`（L27）、types.py `LEGACY_TYPE_ALIASES`（L21）、post_process.py `_run_memory_ingest_v2`（L216）、state_service.py 直写旁路（L379）与 `_replay_relationship_memories`（L476）、relationship_milestone_repository.py `create_milestone`（L77）、debug.py timeline（L379） |
| REL-002 | [REL-002.md](REL-002.md) | Core/Projection | REL-001 | prompts/builder.py `build_relationship_section`（L137）/ `_safe_recent_milestone_title`（L73）、context_builder.py `_load_context_insights` 先例（L73）、db.py `world_events`（L635）/`worlds.user_id`（L546）、relationship_event_repository.list_events（L54）、trace_collector TRACE_STEP_NAMES（L13） |
| REL-003 | [REL-003.md](REL-003.md) | Integration/接线 | REL-001, P3 DEV-003（已交付） | development/aggregate.py `list_active_modulations`（L217）/`read_overlay`（L274）、db.py development_state（L955）/insights scope CHECK（L867）、autonomy_policy.py `PolicySnapshot`（L38）、autonomy_engine.py 组装点（L142）、prompts/builder.py 调制摘要段先例（L347） |
| REL-004 | [REL-004.md](REL-004.md) | Integration/Evaluation | REL-002, P2 REF-004（已交付） | reflection/lifecycle.py `register_insight_created_listener`（L231）/`notify_insight_created_listeners`（L240）、reflector.py `_persist` commit 后广播（L335）、development/policy.py `register_runtime` 先例（L174）、relationship_milestone.py MILESTONES（L81）、evaluation_rules/relationship.py（L126）、evaluation_rules/development.py 模式（L136）、offline_evaluator.py `_development_stats`（L212）、scripts/replay_development.py 模式、debug.py relationship/rollback 重建路径（L449） |

---

## 与 Phase 1~3 实现 / 既有架构的核对记录（冲突与口径登记，不修改架构）

> 按「发现冲突先记录、给出调整建议、不自行修改架构」的要求逐条登记。各项均为 Task Detail 内已给出落地口径的偏差/缺口，供实施前评审确认。

1. **development_state 无 scope 列，`patterns(scope=relationship)` 无直接查询结构**。tasks.md REL-003 Scope 与 architecture domain-boundaries 对 Pattern 的 scope 归属无表级承载（P3 交付的 development_state 只有 kind/key/value/strength/source_insight_id/status；pattern 编译按 type 分派、不看 Insight scope，`policy.compile_insight` L43-60）。落地口径：不在 P3 表结构上加列——Relationship 消费侧按 `source_insight_id` join insights 过滤 `scope='relationship'`（依赖矩阵合法方向，insight 行溯源字段已全审计）。建议：若评审认为 Pattern 需要原生 scope 身份（如 P5/P6 多消费方重复 join），属 P3 表结构变更，另行裁决。
2. **REL-003「AutonomyPolicy 参考」的消费边界**。tasks.md Scope 列「注入关系 Context 段与 AutonomyPolicy 参考」但 Non-Scope 禁改 v8.5 闸门结构。落地口径：参考 = `PolicySnapshot` 追加可选字段（默认空，Extend）+ autonomy 决策 trace 附带 keys——闸门输入可见化，R1~R5 规则、阈值、解锁条件零改动；任何阈值/规则调制属 Phase 5（与 Phase 3 核对记录 4 对 `autonomy.time_preference` 的口径一致）。
3. **world_events 无参与者字段，「双人参与项」无直接判定依据**。`world_events` 表（db.py L635-666）只有 source(user_mention/manual/autonomy)/importance/payload，无 participants 约定，payload 亦无参与者键约定（全库 grep 无命中）。落地口径：双人参与 ≡ `status='completed' ∧ source='user_mention' ∧ importance≠'low'`（用户在场提及是唯一用户关联信号，宁漏选不错选，投影对账不受判定口径影响）。建议：若需更严格判定（payload 参与者约定），属 V8 域扩展，另行裁决。
4. **REL-002「可选 SQL 视图（0~1）」取 0**。服务层投影可重算、可测试、幂等语义与 tasks.md State Machine「无（投影可重算）」一致，视图引入 DDL 维护与方言成本且无可观测增益。/tasks.md 允许 0~1，取 0 不属范围变更。
5. **Shared Experience 段在 context-architecture.md §1 分层表中无行**。§1 只列 P1 关系切片（stage+维度+最近里程碑，≤150 字符）。落地口径：作为 P1 关系切片的扩展子段落地（prompts/builder 同一函数族，独立预算 settings，默认 200 字符），不在 800 检索类合并预算内（结构化投影非检索召回）。判定为文档间对齐而非范围扩大（tasks.md REL-002 Scope 明列「Context 新增 shared experience 段」；同 Phase 3 核对记录 8 的处理先例）；若评审认为需修订 context-architecture 分层表，属文档变更，另行裁决。
6. **迁移执行后 v1 memory_replay 回放源自然枯竭**。`state_service._replay_relationship_memories`（L476-530）只筛 `type=='relationship_event'` 记忆在闲置 ≥24h 时补记折扣事件（source=memory_replay）回账本。REL-001 迁移将该类型归一为 relationship_fact 后该路径命中 0 行，memory_replay 事件归零。落地口径：不改回放函数（REL-001 Non-Scope「不改 V8.5 数学」覆盖其输入路径）——v2 下叙事事实不驱动数值、账本即真相，回放枯竭是叙事/数值解耦的预期结果而非回归；迁移 dry-run 报告显式输出受影响行数供灰度评审。建议：若评审要求保留回放行为（扩筛选至 relationship_fact 需先解决与 v2 行的双计去重），属架构裁决，另行处理。
7. **叙事里程碑不随 Insight 失效回滚**。REF-005 失效→Development 回退（DEV-004）的语义不适用于里程碑：里程碑记录「当时达成的经历事实」（只增 HARD），Insight 失效只影响后续触发资格（handler 重读须 active）。这是与 Development 回退语义的刻意分野，已在 REL-004 设计中固定；若评审认为需联动失效，属需求变更。
8. **relationship_milestones 加 nullable meta JSON 列（迁移 0027）**。tasks.md REL-004 Data Changes 只列「行（账本语义不变）」未列列变更，但 E-REL-04「可溯源 Insight」需要持久溯源位（表现无来源列）。落地口径：nullable `meta JSON`，NULL 默认、零 check/索引变更、数值里程碑行（process_milestones 既有调用）零影响——账本语义不变成立，属 version-boundary Extend 点。备选（若评审认为账本表不可扩列）：溯源仅存于转写记忆 source_ref_extra + background_jobs payload，代价是 ledger→insight 审计弱化为经记忆 join 的间接链。
9. **v1 存量记忆不回填 source_ref**。v1 旧行由模板通道产生，无法可靠映射回具体账本行。落地口径：迁移脚本只动 type 列；存量行审计口径登记为「v1 模板通道产物」（dry-run 报告单列行数）；E-REL-01「互相溯源 100%」的口径适用于 Flag ON 起点之后的新产行，存量在报告中显式声明。
10. **`v2_relationship_evolved_enabled` 当前不存在**。全库无任何 `v2_relationship*` Flag。四份 Detail 均按「REL-001 新增该 settings（默认 False）」处理；Enablement 串行链位置在 `v2_development_enabled` 之后（dependency-graph §1），`v2_memory_enabled` 为其事实前置（转写通道在 run_memory_extract 门内）——启动校验器加一条告警（对齐 `validate_rel_config` 模式）。
11. **E-REL-03 重放工具的交付归属**。tasks.md REL-001/REL-004 Outputs 均未列工具，但 regression-checklist 执行步骤 1 明列「evolve() 重放字节级对比（replay 工具）」且 M3 硬门依赖它。落地口径：`scripts/replay_relationship.py` 由 REL-004（评估闭环）交付；REL-001 的 M1 回归用既有 v8.5 重放测试（tests/v8.5/test_relationship_replay.py）+ 在线 `LEDGER_RECONCILIATION` 规则承担，M3 终验用工具。交付序在 Phase Milestone 框架内自洽，无范围扩大。
12. **IssueCode 计数常量 34→36**。REL-004 追加 `RELATIONSHIP_NARRATIVE_ORPHAN` / `RELATIONSHIP_MILESTONE_UNPROVENANCED` 两码后须同步 `tests/unit/test_evaluation_models.py` 计数断言（REF-006 27→30、DEV-005 30→34 后第三次同款收口）。

---

## 一致性终检结论（生成时点）

- tasks.md REL-001~004 每个 Task 均有 Detail，Task ID 完整一致；M1→M3 交付序与各 Detail 依赖声明吻合（REL-001 仅依赖已交付的 P1 → REL-002 → REL-003（等 P3，已就绪）/ REL-004（等 P2，已就绪）→ Eval Gate（E-REL-01/02/04 场景集 + E-REL-03 重放工具）+ Regression Gate（V8.5 checklist 全量）→ 申请开启 `v2_relationship_evolved_enabled`）。
- 全部 Detail 与 v2.0.0 README/architecture（domain-boundaries/data-flow/context-architecture/evaluation/character-runtime/dependency-graph）及 Phase 4 README 的边界裁决一致：**Relationship→Memory 单向（只经 ingest，永不直写）**、数值归账本/叙事归记忆/快照为投影、Shared Experience 与查询收敛为只读投影（零写路径）、Development 只读消费（消费侧过滤，P3 表结构零改动）、V8.5 数学与 12 项数值里程碑判定零改动（evolve() 字节级 + 限速/迟滞不动）、里程碑写入走账本唯一写点、评估只产报告不写业务状态、四 Task 全部 LLM Usage = NONE、Flag OFF 逐字节回 v1。
- 「互动事件 → Memory → Reflection → Relationship Evaluation → 关系状态变化」的可追踪/可解释/可回溯落点：事件→候选→记忆全程 trace + source_ref（REL-001）；Insight→里程碑 meta 溯源（REL-004）；投影逐条 source_ref 对账（REL-002）；模式注入逐条落选原因 trace（REL-003）；运维面迁移 dry-run 报告与重放工具（REL-001/REL-004）。
- 全部 Detail 基于已提交实现设计，未假设不存在的接口；对既有交付面的唯一结构扩展（milestones 表 nullable meta 列）与全部行为性口径偏差已在核对记录 1~12 显式登记并给出最小落地口径与备选方案。
- 未提前设计 Phase 5~6：Detail 中出现的 Life Loop 关系闸门调制、Autonomy 阈值消费、Goal 层级化、解锁资产扩展（unlocks 恒空）均仅以「后续消费方/不在本 Phase」身份出现，无任何前置实现设计。
