# Phase 2 Tasks — Reflection

> Schema 与分层约定同 [phase-1](../phase-1-memory/tasks.md)。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Foundation:   REF-001（Insight 存储）
Core:         REF-002 Evidence Window / REF-003 触发器 / REF-004 Reflector
Integration:  REF-005 反驳通道 / REF-007 Context 注入段
Observability+Evaluation: REF-006
并行声明: REF-001 可与 P1 全程并行（仅 schema 对齐评审）；REF-002/003/004 开发可提前，启用依赖 P1
```

## REF-001 Insight 存储与生命周期（Foundation）

- **Priority**: P0
- **Objective**: insights/reflection_runs/evidence_links 三表 + 生命周期状态机
- **Problem**: Insight 是 P3/P4/P6 的唯一上游，无存储则整个认知链无落点；生命周期缺失则幻觉 Insight 无法回收（R6）
- **Scope**: alembic 迁移三表；supersede/invalidated 转换服务；invalidated_reason 必填约束
- **Non-Scope**: 不接任何消费方（P3 才接）；不做反思执行；不写 Memory/State/Relationship
- **Inputs**: [architecture.md](architecture.md) §1 表结构
- **Outputs**: 三表 + lifecycle 服务（状态迁移 API）
- **Dependencies**: 无（可与 P1 并行开发；启用依赖 P1）
- **Architecture References**: architecture.md §1；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Reflection 行
- **Domain Boundary**: Reflection（只写本域三表）
- **Data Changes**: 新表 3 张；insights.status∈active|superseded|invalidated；downgrade 干净
- **Runtime Flow**: 无运行时行为（纯存储层）
- **LLM Usage**: NONE
- **State Machine**: active→superseded(新结论更强)|invalidated(被反驳/证伪)；superseded/invalidated 为终态不复活；非法转换拒绝
- **Idempotency**: 状态迁移 API 幂等（同状态重复迁移无操作）
- **Feature Flag**: `v2_reflection_enabled` 定义 default=false
- **Error/Failure**: 迁移往返测试兜底
- **Observability**: 表级审计字段足够（P2 前无 trace 消费方）
- **Testing**: Unit=状态机全路径+非法转换；Integration=迁移往返
- **Acceptance Criteria**: 给定 active Insight 被反驳，当调用 invalidate，那么状态变更、reason 必填、原行不删除；给定 downgrade，那么三表删除且 v1 零影响
- **Regression**: 无行为面
- **Evaluation**: 无（供 REF-006 依赖）
- **Risk**: 无

## REF-002 Evidence Window 聚合（Core）

- **Priority**: P0
- **Objective**: 从 Memory 检索聚合出合格证据组（数量/跨度/来源多样性/印证度）
- **Problem**: 反思质量的上限由证据质量决定；无聚合规则则 LLM 拿零星记忆编结论 = 幻觉温床（README §9 依赖 P1→P2 的原因）
- **Scope**: 按主题聚类分组（同 embedding 邻域+关键词混合）；窗口默认 30 天；组统计输出；门槛前置判定
- **Non-Scope**: 纯规则 0 LLM；单条记忆不得成组；不产出 Insight
- **Inputs**: memories（active，非 hypothetical）+ MEM-006 检索能力
- **Outputs**: Evidence 候选组（组统计 + 成员引用）
- **Dependencies**: P1 MEM-006；REF-001
- **Architecture References**: architecture.md §2 数据流；[../../architecture/character-runtime.md](../../architecture/character-runtime.md) §2.2 Reflection Check
- **Domain Boundary**: Reflection（只读 memories；不写任何域）
- **Data Changes**: 无
- **Runtime Flow**: 主题向量 → 分组 → 窗口过滤 → 统计 → 门槛判定 → 组/跳过
- **LLM Usage**: NONE
- **State Machine**: 无
- **Idempotency**: 同数据同分组
- **Feature Flag**: `v2_reflection_enabled`，OFF=不聚合
- **Error/Failure**: 聚类异常→返回空组+trace
- **Observability**: reflection_evidence trace（组统计/门槛判定）——「用了哪些 Memory/几条/跨度多久」可答
- **Testing**: Unit=分组与统计；Integration=构造「5 次说累」场景
- **Acceptance Criteria**: 给定 10 天内 5 条同主题记忆，当聚合，那么聚为一组且跨度/来源合规；给定孤立单条记忆，那么不成组
- **Regression**: 只读不影响 golden
- **Evaluation**: [evaluation.md](evaluation.md) E-REF-01/02
- **Risk**: 聚类阈值敏感→阈值进 settings+离线校准

## REF-003 反思触发器（Core）

- **Priority**: P0
- **Objective**: 周期+事件双触发，门槛前置，额度控制
- **Problem**: 反思是无 LLM 不做的事，必须保证「绝大多数日子 0 调用」否则成本失控（R9 前置防线）
- **Scope**: 每日调度（background_jobs）；同主题 reinforce 计数达阈值事件触发；当日额度 ≤1 次/用户；门槛检查在入队前
- **Non-Scope**: 不做反思执行；不修改 MEM-005 的 reinforce 逻辑（只订阅信号）
- **Inputs**: 时钟、reinforce 事件流、REF-002 门槛
- **Outputs**: 反思任务入队（或 0 入队）
- **Dependencies**: REF-001, REF-002, P1 MEM-009
- **Architecture References**: architecture.md §5 成本控制；[../../architecture/llm-orchestration.md](../../architecture/llm-orchestration.md) §1 Reflection 行
- **Domain Boundary**: Reflection（写 reflection_runs 记录；调用 background_jobs）
- **Data Changes**: reflection_runs 行
- **Runtime Flow**: 触发源 → 证据门槛预检 → [不足→跳过+trace, 0 LLM | 足够→额度检查→入队]
- **LLM Usage**: NONE（触发器本身不调用）
- **State Machine**: reflection_runs: queued→running→done|skipped(门槛拦截)
- **Idempotency**: 每用户每日一条 reflection 任务（job_key=reflect+user+日桶）
- **Feature Flag**: `v2_reflection_enabled`，OFF=不注册调度
- **Error/Failure**: 调度异常→下一日桶恢复；事件风暴→计数器带冷却窗口
- **Observability**: reflection_trigger trace（触发源/门槛结果/额度状态）——「为什么反思/为什么没反思」可答
- **Testing**: Unit=额度与冷却；Integration=调度触发；FailureInjection=事件风暴
- **Acceptance Criteria**: 给定无证据日，当调度触发，那么 0 LLM 调用且 runs 记 skipped；给定证据爆发日+事件触发，那么当日 LLM 反思最多 1 次
- **Regression**: 无 golden 影响
- **Evaluation**: [evaluation.md](evaluation.md) E-REF-03
- **Risk**: 无

## REF-004 反思执行器（Core / Reflector）

- **Priority**: P0
- **Objective**: LLM Reasoning 调用与产出校准——LLM 只产候选，代码决定终值
- **Problem**: 任务书 §二十红线：LLM 随便生成结论直写真相 = AI 自嗨；必须把「结论生成」与「入库判定」分离
- **Scope**: 反思 Prompt（证据组+类型约束+反例字段强制）；结构化输出解析；confidence 代码校准（按证据强度折算）；三闸复检；单事务写 insights+evidence_links+reflection_runs
- **Non-Scope**: LLM 无权定 confidence 终值；不写 Memory/State/Relationship/Development；不修改证据
- **Inputs**: 合格 Evidence 组
- **Outputs**: insights 行 + evidence_links + reflection_runs
- **Dependencies**: REF-002, REF-003
- **Architecture References**: architecture.md §3 Prompt 结构；[../../architecture/risk.md](../../architecture/risk.md) R6；[../../architecture/data-flow.md](../../architecture/data-flow.md) §2.3
- **Domain Boundary**: Reflection（只写本域三表）
- **Data Changes**: 三表写入（单事务）
- **Runtime Flow**: 入队任务 → 取证据组 → LLM 结构化推理 → 代码校准 confidence → 三闸复检 → [通过→入库 | 拒绝→丢弃+trace]
- **LLM Usage**: main 档；触发=REF-003 入队；≤1 次/任务；重试 1 次（解析失败）；fallback=任务记 failed 不产 Insight；禁止前台
- **State Machine**: insight 状态见 REF-001；runs: queued→running→done|failed
- **Idempotency**: run_id 幂等；同 run 重复执行不产第二条 insight
- **Feature Flag**: `v2_reflection_enabled`，OFF=任务不执行
- **Error/Failure**: LLM 失败→run failed+重试 1 次；输出不合规（缺反例/超范围）→丢弃+trace；DB 失败→回滚
- **Observability**: reflection_run trace（证据引用/原始输出/confidence 折算过程）——「Insight 从哪来/为什么 confidence 是这个值」可答
- **Testing**: Unit=confidence 折算与三闸；Integration=Prompt 回归集；FailureInjection=幻觉注入（证据篡改必须降级或拒绝）
- **Acceptance Criteria**: 给定合规证据组，当反思，那么产出 100% 带 ≥门槛数证据引用且 confidence 与证据强度单调一致；给定被篡改证据，那么结论降级或拒绝
- **Regression**: 无 golden 影响（后台）
- **Evaluation**: [evaluation.md](evaluation.md) E-REF-01/02
- **Risk**: LLM 过度概括→反例字段强制 + Judge 抽查

## REF-005 反驳与失效通道（Integration）

- **Priority**: P1
- **Objective**: 用户可推翻 Insight；新证据可 supersede 旧 Insight
- **Problem**: 不可反驳的认知会永久污染行为（R6 的回收通道）；任务书 §二十要求 invalidated/superseded 支持
- **Scope**: 澄清类话语识别（复用记忆冲突通道风格）→ invalidated；新反思结论与旧冲突→superseded；下游失效事件广播（DEV-004 订阅）
- **Non-Scope**: 不删除行（审计保留）；不直接改 Development/Goal（只发事件）
- **Inputs**: 用户话语 / 新 Insight
- **Outputs**: 状态迁移 + trace + 失效事件
- **Dependencies**: REF-001, REF-004
- **Architecture References**: architecture.md §1 生命周期；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §3 单向约束
- **Domain Boundary**: Reflection（只写本域；事件由消费方订阅，禁止直写他域）
- **Data Changes**: insights.status/invalidated_reason/superseded_by
- **Runtime Flow**: 澄清话语/新结论 → 匹配旧 Insight → [高匹配→invalidated/superseded | 低匹配→忽略] → trace+事件
- **LLM Usage**: 复用 REF-004 通道内调用（不新增独立链）
- **State Machine**: active→invalidated|superseded（终态）
- **Idempotency**: 同一话语重复触发不二次迁移
- **Feature Flag**: `v2_reflection_enabled`
- **Error/Failure**: 匹配歧义→保守不失效（需高匹配度+保守阈值）
- **Observability**: reflection_invalidate trace（匹配依据/触发者）
- **Testing**: Unit=匹配阈值；Integration=反驳表述变体集
- **Acceptance Criteria**: 给定「其实我最近不累」，当匹配到对应 Insight，那么其 invalidated 且当轮退出 Context 且 DEV 收到失效事件；给定模糊澄清，那么不失效任何 Insight
- **Regression**: 无 golden 影响
- **Evaluation**: [evaluation.md](evaluation.md) E-REF-04
- **Risk**: 误失效正确 Insight→保守阈值+误失效率指标

## REF-006 Reflection Trace 与评估接入（Observability / Evaluation）

- **Priority**: P1
- **Objective**: 「为什么形成这个 Reflection」可答；反思质量可测
- **Problem**: REF-002~005 各环节无统一 trace 则无法验收，误报率无法量化
- **Scope**: reflection_* trace 步骤；Evaluation 新增 reflection 规则集+Judge 维度；离线误报率场景
- **Non-Scope**: 只读旁路；不新建存储
- **Inputs**: 反思全链路事件
- **Outputs**: trace + 评估报告
- **Dependencies**: REF-004
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Reflection 行
- **Domain Boundary**: 横切质量平面
- **Data Changes**: 无
- **Runtime Flow**: 链路事件 → trace；离线场景集 → 指标
- **LLM Usage**: Judge 采样（离线/在线采样复用既有）
- **State Machine**: 无
- **Idempotency**: 场景可重复执行
- **Feature Flag**: 无
- **Error/Failure**: Judge 失败→skipped 重跑
- **Observability**: 即本 Task
- **Testing**: 即测试本身
- **Acceptance Criteria**: 给定噪声记忆场景集，当离线评估，那么误报率 0；给定任一 Insight，那么可回溯完整证据链（每条 evidence 可查原文）
- **Regression**: 无 golden 影响
- **Evaluation**: E-REF-01~04 汇总
- **Risk**: 无

## REF-007 Insight→Context 注入段（Integration）

- **Priority**: P2
- **Objective**: 高置信 active Insight 以只读摘要进入 Context（限额段）
- **Problem**: domain-boundaries 裁决「Context（高置信 Insight 可入选）」，但原 Task 集无承接方——Design→Task 断层（TASKS-AUDIT §2）；不补则 P2 交付后 Insight 对行为零影响，闭环断裂
- **Scope**: 只读查询接口（active+confidence≥阈值+scope 匹配）；Context 新增 insight 段（并入检索类合并预算 800，Freshness 排序）；invalidated 即时退出
- **Non-Scope**: 不做行为调制（P3 DevPolicy 才是行为通道）；不做摘要压缩 LLM；全量注入禁止
- **Inputs**: insights（active）
- **Outputs**: Context insight 段（≤预算）+ trace
- **Dependencies**: REF-001, REF-005
- **Architecture References**: [../../architecture/context-architecture.md](../../architecture/context-architecture.md) §1/§2 Freshness；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Reflection「被谁调用」列
- **Domain Boundary**: Reflection 只读接口；装配在编排层（Context Architect）
- **Data Changes**: 无
- **Runtime Flow**: 装配期 → 查询高置信 Insight → 预算/新鲜度过滤 → 注入 → trace
- **LLM Usage**: NONE
- **State Machine**: 无
- **Idempotency**: 同数据同注入
- **Feature Flag**: `v2_reflection_enabled`，OFF=无该段（golden 不变）
- **Error/Failure**: 查询失败→段为空
- **Observability**: context_insight trace（入选/落选原因）
- **Testing**: Unit=过滤与预算；Integration=端到端注入；Regression=Flag OFF golden
- **Acceptance Criteria**: 给定 confidence≥阈值的 active Insight，当装配 Context，那么出现在 insight 段且预算内；给定其被 invalidated，那么下一轮起 0 出现
- **Regression**: V7.5 prompt 相关 checklist
- **Evaluation**: [evaluation.md](evaluation.md) E-CTX-01
- **Risk**: 注入质量差影响回答→只取 top 置信 + 消融测试

---

## Phase 2 Milestone（交付序）

```text
M1 Foundation:  REF-001（可提前与 P1 并行）
M2 Core:        REF-002→REF-003→REF-004
M3 Integration: REF-005 / REF-007
M4 Acceptance:  REF-006 → Eval Gate + Regression Gate → 申请开启 v2_reflection_enabled
```

## 实现状态（2026-09-06）

```text
REF-001~007 已全部实现并逐 Task 提交（Foundation 2f795e4 → REF-007 fedb190）。
迁移落地为 0025_reflection_foundation（Task Detail 原定 0024，因 Phase 1 收口类型扩列已占用 0024，详见 task-details README 口径）。
离线 Eval Gate（E-REF-01~04）在 tests/v2/test_ref006_trace_evaluation.py 内确定性执行并全部通过。
v2_reflection_enabled 保持 default=false：灰度推进与真实模型人工回归待执行（regression-checklist.md）。
```

