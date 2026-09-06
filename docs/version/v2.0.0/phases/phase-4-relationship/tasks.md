# Phase 4 Tasks — Long-term Relationship

> Schema 与分层约定同 [phase-1](../phase-1-memory/tasks.md)。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Core:        REL-001 真相源统一 / REL-002 Shared Experience 投影
Integration: REL-003 Patterns 接入 / REL-004 叙事里程碑与评估
并行声明: REL-001~002 仅依赖 P1；可与 P3/P5 开发并行
红线: V8.5 数值数学（D1/D2/D3/D5/限速/迟滞）零改动（version-boundary Preserve）
```

## REL-001 关系事实真相源统一（Core / 转写通道）

- **Priority**: P0
- **Objective**: 消除关系事实双真相源（Memory relationship_event 类型 vs relationship_events 账本）
- **Problem**: 双真相源靠口头约定维系（v1 审计问题 4），任何一边变更都会产生「角色又记错关系」体验
- **Scope**: 里程碑/冲突解决/重要关系事件 → 经 P1 ingest 通道转写为 relationship_fact 记忆（source_ref 回指账本行）；v1 遗留 relationship_event 类型记忆迁移映射；查询路径在 Relationship 域内收敛
- **Non-Scope**: 账本仍是数值唯一真相；Relationship 域禁止直写 memories（走 ingest）；不改 V8.5 数学
- **Inputs**: relationship_events/milestones/conflicts 状态变更
- **Outputs**: relationship_fact 记忆 + 迁移脚本
- **Dependencies**: P1 MEM-002, MEM-005
- **Architecture References**: [../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §4；[../../architecture/data-flow.md](../../architecture/data-flow.md) §4
- **Domain Boundary**: Relationship（读账本）→ Memory Ingest（写）；跨域写入走 Ingest 不直写
- **Data Changes**: 无新表；memories 新类型行；迁移脚本（dry-run+幂等重跑）
- **Runtime Flow**: 账本变更 → Ingest 转写 → candidate → 转正 → trace
- **LLM Usage**: NONE
- **State Machine**: 同 MEM-005
- **Idempotency**: source_ref=(relationship_events.id) 幂等；迁移可重跑
- **Feature Flag**: `v2_relationship_evolved_enabled`，OFF=不转写（旧双轨维持 v1 现状）
- **Error/Failure**: 转写失败→事件留待重扫；迁移遗漏→dry-run 报告+双读校验窗口
- **Observability**: memory_ingest trace 源=relationship_event；真相源审计（任一事实可答「存在哪/为什么存在」）
- **Testing**: Integration=转写幂等；迁移前后检索对比；双写一致性
- **Acceptance Criteria**: 给定任一重要关系事件，当查询审计，那么账本行与记忆行可互相溯源且数值归账本、叙事归记忆；给定 v1 旧类型记忆，当迁移，那么检索语义不变
- **Regression**: V8.5 regression-checklist 重跑（数值零改动证明）
- **Evaluation**: [evaluation.md](evaluation.md) E-REL-01
- **Risk**: 迁移遗漏→dry-run+双读校验
- **Inconsistency 裁决记录**: 「迁移脚本」原无独立 Task——审计后并入本 Scope（粒度足够，不独立成 Task，见 TASKS-AUDIT §2）

## REL-002 Shared Experience 投影（Core / Projection）

- **Priority**: P0
- **Objective**: 「共同经历」可查询、可注入 Context
- **Problem**: v1 知道关系数值多高，但说不出「我们一起经历过什么」；这是关系从数值变历史的核心缺口
- **Scope**: 只读投影服务（Memory experience/relationship_fact + relationship_events + 完结 world_events 双人参与项，时间序）；Context 新增 shared experience 段（Freshness 排序、预算内）
- **Non-Scope**: 零新表（视图/服务投影可重算）；不改 World 域模型
- **Inputs**: memories、relationship_events、world_events
- **Outputs**: 共同经历列表 + Context 段
- **Dependencies**: REL-001
- **Architecture References**: [../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §2 Shared Experience 行；[../../architecture/context-architecture.md](../../architecture/context-architecture.md) §1
- **Domain Boundary**: Relationship（跨表只读投影；写路径为零）
- **Data Changes**: 可选 SQL 视图（0~1）
- **Runtime Flow**: 装配期 → 投影查询 → 排序/预算截断 → Context 段 → trace
- **LLM Usage**: NONE
- **State Machine**: 无（投影可重算）
- **Idempotency**: 同数据同投影
- **Feature Flag**: `v2_relationship_evolved_enabled`，OFF=无该段
- **Error/Failure**: 查询慢→索引+短缓存；空→段为空
- **Observability**: relationship_shared trace（入选/排序依据）
- **Testing**: Unit=投影对账；Integration=注入端到端；Performance=P95
- **Acceptance Criteria**: 给定 3 次共同事件，当投影，那么按时间序返回且与源数据对账一致；给定 Flag OFF，那么 Context 无该段且 golden 不变
- **Regression**: V8 checklist + golden
- **Evaluation**: [evaluation.md](evaluation.md) E-REL-02
- **Risk**: 投影查询慢→索引+短缓存

## REL-003 Relationship Patterns 接入（Integration）

- **Priority**: P1
- **Objective**: Development 产出的关系模式影响关系行为（只读调制）
- **Problem**: Patterns 是 P3 产出在关系域的消费点；不接则「关系模式」无行为意义
- **Scope**: 读取 development patterns(scope=relationship) → 注入关系 Context 段与 AutonomyPolicy 参考
- **Non-Scope**: 不写数值；不改 v8.5 闸门结构；不产生新 Pattern
- **Inputs**: development_state（scope=relationship）
- **Outputs**: Context 关系段扩展 + 闸门参考
- **Dependencies**: REL-001, P3 DEV-003
- **Architecture References**: [../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1；[../../architecture/character-runtime.md](../../architecture/character-runtime.md) §3
- **Domain Boundary**: Relationship 只读 Development（依赖矩阵合法方向）
- **Data Changes**: 无
- **Runtime Flow**: 装配/闸门期 → 读 Pattern → strength 过滤 → 注入/参考 → trace
- **LLM Usage**: NONE
- **State Machine**: 无
- **Idempotency**: 同数据同注入
- **Feature Flag**: `v2_relationship_evolved_enabled` ∩ `v2_development_enabled`（双闸）
- **Error/Failure**: 读取失败→无注入（fail-safe）
- **Observability**: relationship_pattern trace
- **Testing**: Integration=端到端注入；Unit=strength 过滤
- **Acceptance Criteria**: 给定 strength≥阈值的 Pattern，当装配，那么 Context 关系段可见；给定任一 Flag OFF，那么无注入且 golden 不变
- **Regression**: V8.5 checklist
- **Evaluation**: [evaluation.md](evaluation.md) E-REL-02
- **Risk**: Pattern 噪声→strength 门槛

## REL-004 叙事里程碑与关系评估（Integration / Evaluation）

- **Priority**: P1
- **Objective**: Insight 驱动的叙事里程碑 + 关系域评估闭环
- **Problem**: V8.5 数值里程碑无法表达「第一次一起熬夜赶工」类叙事；无评估则真相源统一无法验收
- **Scope**: 高置信 relationship 类 Insight 达叙事里程碑条件 → milestone 落账本 + 转写记忆（走 REL-001 通道）；Evaluation 新增 relationship 一致性规则（账本重放对账+真相源审计）
- **Non-Scope**: 数值里程碑判定逻辑不动；叙事里程碑只增不改；白名单+频控防泛滥
- **Inputs**: insights（scope=relationship）、milestones
- **Outputs**: 新里程碑 + 评估报告
- **Dependencies**: REL-002, P2 REF-004
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Relationship 行
- **Domain Boundary**: 里程碑写入走账本（V8.5 通道）；记忆转写走 Ingest
- **Data Changes**: relationship_events/milestones 行（账本语义不变）
- **Runtime Flow**: Insight 达标 → 白名单+频控 → milestone 落账本 → Ingest 转写 → trace
- **LLM Usage**: NONE（判定全规则）
- **State Machine**: 里程碑只增（HARD）
- **Idempotency**: 同 Insight 只触发一次
- **Feature Flag**: `v2_relationship_evolved_enabled`
- **Error/Failure**: 触发异常→跳过+trace，不阻塞反思链
- **Observability**: relationship_milestone trace（触发 Insight/判定依据）
- **Testing**: Integration=触发与频控；Regression=V8.5 数值字节级
- **Acceptance Criteria**: 给定数值回归，当 evolve() 执行，那么输出与 v1 字节级一致；给定叙事里程碑触发两次，那么只落一条
- **Regression**: V8.5 regression-checklist 全量重跑
- **Evaluation**: E-REL-01/02 汇总
- **Risk**: 里程碑泛滥→白名单+频控

---

## 实现状态（2026-09-06 完成）

```text
REL-001 已实现（v2_relationship_evolved_enabled 总闸 settings 化；Flag ON 关停
state_service v1 直写旁路（冲突/里程碑/快照子系统不动）；里程碑转写通道
ingest_from_relationship_milestone（milestone_event 类型 + salience 三档映射 +
source_ref 回指 + meta.insight_id 透传）+ post_process 接线；迁移脚本
scripts/migrate_relationship_memory_types.py（dry-run 默认/--apply 分批幂等/
verification 别名三项校验/回放源影响面报告）；debug timeline 每行附
narrative_memory_ids 账本↔记忆互溯 + 14 测试绿；V8.5 回归 170 绿）。
REL-002 已实现（relationship_shared 三源只读投影：账本 conversation/system 非
none 行 + memories(experience/relationship_fact) source_ref 去重合并 + 完结
world_events 双人参与项（completed ∧ user_mention ∧ 非 low）；时间序 +
Freshness 选材 limit=3 + 独立预算 200 字符【共同经历】Context 段（dev overlay
之后）；relationship_shared trace + 15 测试绿；golden 与 world/context 回归全绿）。
REL-003 已实现（relationship_patterns 消费侧 join insights 过滤
scope=relationship + strength≥0.6 门槛 + top-2 + 逐条落选原因；【关系模式】段
（共同经历段之前，预算 120）；PolicySnapshot.relationship_patterns 参考注入 +
决策 trace 附带（R1~R5 零改动，interval 不变性断言）；双闸 Flag 矩阵 +
13 测试绿；v8.5 autonomy 全量回归原样通过）。
REL-004 已实现（relationship_narrative：insight_created listener → job
（幂等键 relationship_narrative:{insight_id}）→ 白名单关键词全规则匹配 +
单日 cap → create_milestone（V8.5 唯一写点：零 bonus/零 unlocks/meta 溯源）；
迁移 0027 milestones.meta nullable JSON（数值行零影响）；评估规则 +2
（RELATIONSHIP_NARRATIVE_ORPHAN / RELATIONSHIP_MILESTONE_UNPROVENANCED，
IssueCode 34→36 收口）；NarrativeSlice 只读切片；relationship_evaluation 场景集
E-REL-01/02/04 Gate 全过 + 报告归档 reports/rel-20260906.json；
scripts/replay_relationship.py 快照锚点+账本重放只读对账（偏差分可解释
comfort_drift/milestone_bonus 与不可解释两栏）+ 18 测试绿；eval 全量 11 绿）。
REL-001~004 全部实现并逐 Task 提交（ec72294 → 006148f）。离线 Eval Gate
（E-REL-01/02/04）在 tests/eval/test_relationship_eval_gate.py 确定性执行并全部
通过（报告归档 tests/eval/reports/rel-20260906.json）；E-REL-03 由
scripts/replay_relationship.py 与 tests/v8.5/test_relationship_replay.py 承担。
v2_relationship_evolved_enabled 保持 default=false：Enablement 串行链位于
v2_development 之后，灰度推进与真实模型人工回归待执行（regression-checklist.md，
V8.5 checklist 全量重跑是硬门）。
全量回归：**1992 passed / 16 skipped / 0 failed**（xdist 19.8s 与串行 82.4s
双模式一致）。V8.5 unit 计数断言 test_rules_registered 4→6 收口（REL-004
新增 2 规则，同 ISSUE_CODE_COUNT 收口惯例）。
```

---

## Phase 4 Milestone（交付序）

```text
M1 Core:        REL-001 → REL-002（仅依赖 P1，可提前）
M2 Integration: REL-003（等 P3）/ REL-004（等 P2）
M3 Acceptance:  Eval Gate + Regression Gate（含 V8.5 字节级证明）→ 申请开启 v2_relationship_evolved_enabled
```

