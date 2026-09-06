# Phase 3 Tasks — Character Development

> Schema 与分层约定同 [phase-1](../phase-1-memory/tasks.md)。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Foundation:   DEV-001（Development 存储）
Core:         DEV-002 DevPolicy 编译器
Integration:  DEV-003 行为接线 / DEV-004 回退与重放
Observability+Evaluation: DEV-005 / DEV-006 成长闭环验证
并行声明: DEV-001 可与 P1/P2 并行；DEV-002~004 开发可提前（启用依赖 REF-004/005）
```

## DEV-001 Development Aggregate 存储（Foundation）

- **Priority**: P0
- **Objective**: development_state/development_changes 两表 + 读写服务
- **Problem**: Belief/Preference/Pattern 是角色「因经历而变」的唯一载体；无独立存储则 Development 与 Memory/Reflection 混淆（任务书 §十七红线）
- **Scope**: alembic 迁移；aggregate.py 读写；status 语义（active/superseded/retired）
- **Non-Scope**: 不接消费方；不做编译（DEV-002）；直读 memories 禁止
- **Inputs**: [architecture.md](architecture.md) §1
- **Outputs**: 两表 + 服务
- **Dependencies**: P2 REF-001（结构风格对齐，可并行开发）
- **Architecture References**: architecture.md §1/§4；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Development 行
- **Domain Boundary**: Development（只写本域两表）
- **Data Changes**: 新表 2 张；changes.before/after jsonb 审计；downgrade 干净
- **Runtime Flow**: 无运行时行为
- **LLM Usage**: NONE
- **State Machine**: active→superseded(同 key 更优)|retired；终态不复活
- **Idempotency**: 迁移幂等；写服务以 (user,key) 为粒度
- **Feature Flag**: `v2_development_enabled` 定义 default=false
- **Error/Failure**: 迁移往返测试兜底
- **Observability**: 审计字段
- **Testing**: Unit=状态语义；Integration=迁移往返
- **Acceptance Criteria**: 给定任何变更，当写入，那么 changes 行含 before/after 且可定位 insight_id；给定 downgrade，那么 v1 零影响
- **Regression**: 无行为面
- **Evaluation**: 无（供 DEV-005 依赖）
- **Risk**: 无

## DEV-002 DevPolicy 编译器（Core）

- **Priority**: P0
- **Objective**: Insight→行为参数调制的确定性编译（纯函数，0 LLM）
- **Problem**: 任务书 §十七：Development 必须与 Memory/Reflection 分层；用 LLM 做调制则不可重放、不可归因，角色行为漂移不可控
- **Scope**: 三类 Insight 的调制规则表（preference→ResponseStyle/belief→BehaviorPolicy 关心话题与 habit 候选/pattern→AutonomyPolicy 时间偏好与 goal 权重）；强度封顶；参数注入叠加层；矛盾仲裁（confidence 高者生效，败者 superseded 留痕）
- **Non-Scope**: 纯函数 0 LLM；不改 BehaviorEngine/V8.5/V5 公式本体；不新增 habit（只置候选）；不直读 memories
- **Inputs**: active insights（经 REF-004 产出）
- **Outputs**: development_state 变更 + 调制参数
- **Dependencies**: DEV-001, P2 REF-004
- **Architecture References**: architecture.md §3 规则表；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §3 单向约束 2
- **Domain Boundary**: Development（只写本域；调制输出为只读参数被行为域消费）
- **Data Changes**: development_state + changes
- **Runtime Flow**: 新 active Insight 事件 → 编译规则匹配 → 强度折算封顶 → 同 key 仲裁 → 写 state+changes → 发布调制参数
- **LLM Usage**: NONE
- **State Machine**: 同 DEV-001；同一输入多次编译输出幂等
- **Idempotency**: 编译幂等（同 Insight 重放结果一致）
- **Feature Flag**: `v2_development_enabled`，OFF=不订阅 Insight 事件
- **Error/Failure**: 编译异常→该 Insight 挂起+trace，不阻塞其他；DB 失败→回滚
- **Observability**: development_compile trace（规则命中/折算/仲裁）——「行为为什么变了」可答
- **Testing**: Unit=规则表驱动+封顶+仲裁；Integration=幂等测试；FailureInjection=矛盾 Insight 并发
- **Acceptance Criteria**: 给定同一 Insight 重复编译，那么输出逐字节一致；给定矛盾 Insight 对，那么只有一个 active 且败者 superseded 可溯
- **Regression**: 无 golden 影响
- **Evaluation**: [evaluation.md](evaluation.md) E-DEV-01
- **Risk**: 调制幅度失衡→封顶进 settings+离线校准

## DEV-003 行为接线（Integration / Behavior · ResponseStyle · Goal）

- **Priority**: P0
- **Objective**: 调制参数被运行时真实消费——行为可见变化
- **Problem**: 不接线则 Development 只是表数据；「角色因经历而改变」必须体现在 BehaviorPolicy/ResponseStyle/Goal 权重上
- **Scope**: BehaviorEngine/ResponseStyleController/goal_service 读取叠加层（读取时叠加，不改静态资产）；Flag 门控；变化全程 trace
- **Non-Scope**: 只加读取层；golden 行为在无 development 数据时不变；不写行为域任何表
- **Inputs**: development_state（调制参数）
- **Outputs**: 行为可见变化 + before/after trace
- **Dependencies**: DEV-002
- **Architecture References**: architecture.md §2 数据流；[../../version-boundary.md](../../version-boundary.md) §1 BehaviorPolicy 行（Extend）
- **Domain Boundary**: Development 提供只读参数；行为域只读消费（被调用方，不回调 Development）
- **Data Changes**: 无
- **Runtime Flow**: 行为域取参 → 叠加层合并（development 覆盖层 > v6.5 基线）→ 行为执行 → trace 记 before/after
- **LLM Usage**: NONE
- **State Machine**: 无
- **Idempotency**: 同参数同行为
- **Feature Flag**: `v2_development_enabled`，OFF=叠加层为空（行为与 v1 一致）
- **Error/Failure**: 读取失败→回退基线参数（fail-safe 到 v1 行为）
- **Observability**: development_apply trace（key/before/after/insight 溯源）
- **Testing**: Unit=叠加合并；Integration=端到端行为对比；Regression=空数据 golden
- **Acceptance Criteria**: 给定「用户偏好简短回复」Insight 生效，当回答生成，那么 ResponseStyle 长度预算下降且 trace 可见 before/after+insight_id；给定 Flag OFF，那么行为与 v1 字节级一致
- **Regression**: V6.5 行为 checklist + golden
- **Evaluation**: [evaluation.md](evaluation.md) E-DEV-02
- **Risk**: 叠加层拖慢读取→内存缓存+变更失效

## DEV-004 回退与重放（Integration）

- **Priority**: P1
- **Objective**: Insight 失效后调制自动回退；全量可重放
- **Problem**: 无回退则被反驳的认知永久影响行为（§十七「矛盾处理」缺口）；无重放则审计不可验证
- **Scope**: 订阅 REF-005 失效事件；按 key 重放调制历史；audit.py 重放工具（删 changes 后按 Insight 时间序重编译）
- **Non-Scope**: 重放不改原始审计行；不产生新 Insight
- **Inputs**: Insight 状态变更事件、development_changes
- **Outputs**: 回退后的 development_state
- **Dependencies**: DEV-002, P2 REF-005
- **Architecture References**: architecture.md §3 规则要点；[../../architecture/data-flow.md](../../architecture/data-flow.md) §2.3
- **Domain Boundary**: Development（只写本域）
- **Data Changes**: development_state/changes
- **Runtime Flow**: 失效事件 → 定位受影响 key → 重放该 key 调制历史 → 回退到次优或无调制 → trace
- **LLM Usage**: NONE
- **State Machine**: 生效参数→回退参数（同 key 历史）
- **Idempotency**: 重放结果与在线结果一致；重复事件不重复回退
- **Feature Flag**: `v2_development_enabled`
- **Error/Failure**: 重放异常→保留当前态+告警（不静默清空）
- **Observability**: development_rollback trace（受影响 key/回退目标）
- **Testing**: Unit=重放一致性；Integration=反驳→回退端到端
- **Acceptance Criteria**: 给定用户反驳 Insight，当失效事件到达，那么行为参数回到失效前基线且重放工具输出与在线一致
- **Regression**: 无 golden 影响
- **Evaluation**: [evaluation.md](evaluation.md) E-DEV-03
- **Risk**: 无

## DEV-005 Trace 与评估接入（Observability / Evaluation）

- **Priority**: P1
- **Objective**: Development 一致性与归因可测
- **Problem**: 「调制是否过度、是否可归因」必须量化，否则角色漂移不可发现
- **Scope**: development_* trace 步骤；Evaluation 新增 development 规则集（归因完整率/一致性）
- **Non-Scope**: 只读旁路
- **Inputs**: 变更事件
- **Outputs**: trace + 评估报告
- **Dependencies**: DEV-003
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Development 行
- **Domain Boundary**: 横切质量平面
- **Data Changes**: 无
- **Runtime Flow**: 事件 → trace；离线 → 指标
- **LLM Usage**: Judge 采样
- **State Machine**: 无
- **Idempotency**: 可重复执行
- **Feature Flag**: 无
- **Error/Failure**: Judge 失败→skipped 重跑
- **Observability**: 即本 Task
- **Testing**: 即测试本身
- **Acceptance Criteria**: 给定全部 development_changes，当评估，那么 100% 可追溯 insight_id；给定矛盾场景集，那么无并存生效
- **Regression**: 无 golden 影响
- **Evaluation**: E-DEV-01~03 汇总
- **Risk**: 无

## DEV-006 成长闭环验证（Evaluation / 长周期）

- **Priority**: P2
- **Objective**: 验证 §十完整闭环成立：Insight→调制→重复行为→新经历→再反思（角色真的在成长，而非每次请求动态改参数）
- **Problem**: 调制若不反馈为新经历，Development 就退化成「每次请求动态修改参数」（任务书 §十明令防止）；该闭环跨 P1/P2/P3，必须显式验证
- **Scope**: 离线长剧情场景：注入压力类证据 → Insight → 调制 → 角色行为变化 → 新对话被 P1 摄取 → 第二次反思强化/修正 Insight → 调制演进；校验全程归因链
- **Non-Scope**: 不新增代码能力（验证性 Task，产出为场景集与报告）
- **Inputs**: P1+P2+P3 全链、剧情场景集
- **Outputs**: 闭环验证报告 + 长期场景集入 offline_evaluator
- **Dependencies**: DEV-003, P2 REF-006, P1 MEM-010
- **Architecture References**: [../../dependency-graph.md](../../dependency-graph.md) §4 数据流（BP→新对话→C 分支）；[../../architecture/character-runtime.md](../../architecture/character-runtime.md) §3
- **Domain Boundary**: 横切质量平面
- **Data Changes**: 无
- **Runtime Flow**: 剧情注入 → 多周期模拟 → 归因链审计 → 报告
- **LLM Usage**: 剧情模拟使用既有链路；Judge 评估
- **State Machine**: 无
- **Idempotency**: 可重复执行
- **Feature Flag**: 全链 Flag ON 状态执行
- **Error/Failure**: 场景失败→定位环节（memory/reflection/dev）归因
- **Observability**: 报告即产物
- **Testing**: 即测试本身
- **Acceptance Criteria**: 给定「连续加班」剧情，当三周期模拟，那么第二次反思产出强化/修正的 Insight 且调制幅度变化可归因到新证据；给定中断任一环节 Flag，那么闭环在该环节停止且无越级影响
- **Regression**: 全程在 Flag ON 影子环境
- **Evaluation**: E-DEV-04（闭环归因完整率）
- **Risk**: 长剧情模拟成本→离线批量+采样

---

## Phase 3 Milestone（交付序）

```text
M1 Foundation:  DEV-001（可提前并行）
M2 Core:        DEV-002（等 REF-004 可用）
M3 Integration: DEV-003 / DEV-004
M4 Acceptance:  DEV-005 + DEV-006 → Eval Gate + Regression Gate → 申请开启 v2_development_enabled
```

## 实现状态（2026-09-06 完成）

```text
DEV-001 已实现（迁移 0026_development_foundation + aggregate 读写服务 + 14 测试绿；
upsert 仲裁比较器入参注入，DEV-002 注入同 strength 取新 Insight 的完整比较器）。
DEV-002 已实现（policy.py 纯函数编译 + 规则表 settings 化 + 创建事件钩子接线
reflection/lifecycle+reflector + development_compile job + 15 测试绿；P2 回归 69 绿）。
DEV-003 已实现（read_overlay 叠加层 + 三消费点接线：behavior_engine 追加式修饰/
goal_service 有界 tier 调制/answer_chain 按轮长度偏移 + Context 调制摘要段 +
development_apply trace + 11 测试绿；行为/goal/golden 回归串行全绿。
注：xdist 并行在本机存在与 Phase3 无关的既有 flake——基线 d6d3f8b 复现同组失败
+ INTERNALERROR worker crash，串行 -n0 全绿为准）。
DEV-004 已实现（audit.py 回退=先撤后晋：失效 Insight 的调制 retire、次优胜者
promoted（ignore_seen 绕过同源 noop）+ development_rollback job + verify_replay
只读校验/rebuild 重建 + scripts/replay_development.py + 11 测试绿；P2/P3 回归 84 绿）。
DEV-005 已实现（trace 名单 +4 步骤、IssueCode+4 与 DEVELOPMENT 评估维、规则集 4 条
入注册表、DevelopmentSlice 只读切片、debug 归因端点 2 个、离线场景集 E-DEV-01~03
Gate 全过、build_db_report 入 offline_evaluator、ISSUE_CODE_COUNT 30→34 + 12 测试绿）。
DEV-006 已实现（run_growth_loop 三周期闭环 runner：调制→新经历经 P1 ingest→再反思
强化→调制演进→反驳回退，逐周期归因链审计 + Flag 中断矩阵三变体 + 负向演进；
tests/eval/test_development_growth_loop.py E-DEV-01~04 全量 Gate 通过 + 报告归档
reports/ + 6 测试绿。全部 P3 验收达成本目录 evaluation.md 门槛）。
注：tests/integration/test_evaluation_pipeline.py 在本机因真实 LLM 端点网络退化而
缓慢/挂起——基线 d6d3f8b 复现同现象（60s 仅 5 例），属既有环境问题与 Phase3 无关。
DEV-001~006 全部实现并逐 Task 提交（8482705 → 1fb191d）。离线 Eval Gate
（E-DEV-01~04）在 tests/eval/test_development_growth_loop.py 确定性执行并全部通过
（报告归档 tests/eval/reports/dev-growth-20260906.json）。
v2_development_enabled 保持 default=false：灰度推进与真实模型人工回归待执行
（regression-checklist.md）。
全量回归口径：unit/v2/eval/golden 1258 绿 + integration 314 绿；xdist 并行在本机
存在与 Phase3 无关的既有 flake（localhost-HTTP/LLM 网络类用例，基线 d6d3f8b 复现
同组失败 + worker crash），串行 -n0 为准。
```


