# Phase 6 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) AUT-001~005 一一对应，无遗漏。所有 Detail 锚定 Phase 1~5 真实实现（基线：`feat/v2.0.0` @ e817b5f，MEM-001~011、REF-001~007、DEV-001~006、REL-001~004、LIFE-001~006 已全部提交，迁移链至 0030_outbox_events，全量 2079 绿），未与 v2.0.0 Architecture / Phase 6 README 冲突，未新增 V3.0.0 内容。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| AUT-001 | [AUT-001.md](AUT-001.md) | Foundation/Goal 层级与存储扩展 | 无（可提前；启用依赖 P5） | db.py `GoalRow`/character_goals 12 列（L334）、goal_repository.py `_TERMINAL_STATUS`/`finish_goal`、goal_service.py `review`/`select`（零改动对象）、models/goal.py `GOAL_TIER`/`GoalRecord`、migration 0030 head、LIFE-002 核对记录 2 的 due_at 缺口裁决 |
| AUT-002 | [AUT-002.md](AUT-002.md) | Core/Planning 执行器 | AUT-001, P5 LIFE-002 | capabilities/__init__.py `register_builtin`（6 能力）、models/action.py `ACTION_TYPES` 9 类/`ActionIntent`、reflection/reflector.py `_ask_llm_with_retry`（main 档+重试 1 次模式）、memory2/job_worker.py enqueue/register 协议（development_compile 先例）、development/aggregate.py `read_overlay`、relationship_patterns 读取（autonomy_engine `_snapshot_for` L142-149）、world_engine.py `collect_facts`（L627）、memory_repository.py `list_top_salience` |
| AUT-003 | [AUT-003.md](AUT-003.md) | Core/观察与调整 | AUT-002, LIFE-002 | life_loop.py 七步管线/`_collect_work_users`（L79）/`_step_goal_check`（L318）、action_engine.py `run_action_planning` V9 闸门（GateReason 五类）、`save_record_with_outbox`（LIFE-004）、state_service.py `load_states`、trace_collector.py TRACE_STEP_NAMES、models/goal.py 判据白名单（AUT-001 建位共用） |
| AUT-004 | [AUT-004.md](AUT-004.md) | Integration/冲突与生命周期 | AUT-001, P3 DEV-003 | models/goal.py GoalStatus 扩展位、goal_repository.py 状态守卫收口、development/aggregate.py `read_overlay().goal_weights`（调制只读）、relationship_state 只读参数（V8.5 R1 语义对齐）、models/observability.py `DecisionKind`（+goal_lifecycle）、memory_repository.py `list_top_salience`（abandonment 相关性信号） |
| AUT-005 | [AUT-005.md](AUT-005.md) | Observability/Evaluation | AUT-003, AUT-004 | evaluation_rules/autonomy.py 5 规则先例（LIFE-006）、evaluation_context.py `LifeLoopSlice`/`collect_life_loop_slice`、offline_evaluator.py `_life_loop_stats`（L285）、models/evaluation.py IssueCode 40 码+dimension 别名、tests/eval/test_development_growth_loop.py `run_growth_loop` runner 模式（DEV-006）、regression-checklist.md 步骤 1~5 |

---

## 与 Phase 1~5 实现 / 既有架构的核对记录（冲突与口径登记，不修改架构）

> 按「发现冲突先记录、分析原因、给出调整建议、不自行修改架构」的要求逐条登记。各项均为 Task Detail 内已给出落地口径的偏差/缺口，供实施前评审确认。正文引用形如 GAP-AUT-NN；编号与各 Detail 内登记一致。

1. **层级 goal 供给链缺失（GAP-AUT-01，本 Phase 最重要缺口）**。tasks.md 五个 Task 无人承接「层级 goal 由谁创建」：AUT-001 只做存储、AUT-002 的 Runtime Flow 以「目标创建」为输入、AUT-004 以「目标集合变更」为输入；而 Phase 6 README §核心能力 1 定义了三类来源（personal 源自 Belief/Pattern、relationship 源自 Relationship Patterns、world 源自 World 事件）。**原因分析**：创建与规划在同一条 Runtime Flow（创建后必须立即规划），分离到其他 Task 会制造跨 Task 事务边界，故注册表把它隐含在 AUT-002 输入侧而未实体化。**调整建议（Detail 采用，不新增 Task、不改架构）**：供给装配器并入 AUT-002 作为 Runtime Flow 第一环（纯规则模板、0 LLM、创建走 AUT-001 唯一入口）；备选方案（归 AUT-004 集合变更入口）与**风险声明**（两者皆不采纳则生产路径层级 goal 永不产生、完成标准第 1 条不可达）见 AUT-002 冲突登记。
2. **World/Action 事实进 Goal 域的依赖矩阵冲突（GAP-AUT-02）**。tasks.md AUT-002 Inputs 含「World/Development 约束」、AUT-003 Scope 含「观察读 Action/World 投影」，但 domain-boundaries §3 矩阵 Goal→World/Action 均为 ✗。**裁决**：编排投影传参——Life Loop 周期步骤（编排域可调用一切）采集 facts 后经 payload/参数传入 Goal 域纯函数，Goal 域内零 action/world 表查询。与 LIFE-002 perception→decision 传参模式同构，矩阵零修改（AUT-002 设计 3、AUT-003 设计 1 引用本条）。
3. **goal 表实名为 `character_goals`（GAP-AUT-03）**。tasks.md 写「goals 扩 4 列 / goal_plans 表」；实现中 V6 既有命名即 `character_goals`。Detail 全部按实名书写，tasks.md 不回改（上游契约，实现名差异在此登记）。
4. **v1 select 消费点的层级过滤（GAP-AUT-04）**。`list_active` 不过滤层级字段——层级 goal 会混入 v1 轮内动机集合，`select()` 对其行为未定义。**裁决**：v1 `select()` 本体零改动（golden），在调用点（chat_pipeline `_select_goal` / autonomy_engine `_snapshot_for`）入参侧过滤 `layer IS NOT NULL` 行；层级 goal 的行动表达走 AUT-003 Sub-Goal 执行通道，主动消息动机仍由 v1 4 类承担（P6 不扩 `PROACTIVE_INTENTION_MAP`——AutonomyPolicy 红线继承；层级 goal 直接驱动 proactive 登记 3.0 演进项）。
5. **冲突判定的操作性口径（GAP-AUT-05）**。tasks.md「同域冲突取高优先级 active 另一 suspended 留痕」未定义「冲突」判定；evaluation.md 场景「personal 与 relationship 目标同域冲突」字面矛盾。**裁决**：冲突域 = (layer, domain) 分组内互斥（同组 ≥2 顶层 active 即冲突组），最保守确定性口径；跨域只按 score 排执行序不 suspended；行动面资源冲突检测（同 capability+params 相交）登记 3.0 演进项。
6. **time-based goal 到期不引入 due_at 列**。LIFE-002 核对记录 2 曾登记「time-based 到期依赖 P6 AUT-001 存储扩展」；本 Phase 裁决**不新增列**（tasks.md Data Changes 固定 4 列）：long_term 恒 persistent（v1 turn 过期规则天然不触及）、short_term 复用 `expires_at_turn`、「单 goal 最长执行周期」由 AUT-003 以 plan active 起始时刻现算（`goal_plans.updated_at`，无新列）。若真实回归暴露绝对时间到期需求，另行存储扩展裁决。
7. **plan 状态机补充 superseded 归档态**。tasks.md AUT-002 状态机 `draft→validated→active|rejected` 覆盖单版本生命周期；重规划新版本 active 时旧 active 版本需归档——引入 `superseded`（仅由新版本激活触发）。属状态机补充非变更，登记备评审。
8. **规划 attempt 计数口径**。「Planning LLM ≤3 次/goal 生命周期」的计数载体为 `goal_plans` 行数（含 rejected，无新列）；LLM 解析失败重试 1 次属同一次请求的内部恢复，不重复计数；验收断言（第 4 次请求被拒）按行数核对，口径自洽（AUT-002 设计 5）。
9. **Sub-Goal 执行接线归属**。tasks.md 未显式列「Sub-Goal 如何变成 Action」：AUT-002 明文「规划不直接执行任何 Action」，AUT-003 只列观察/调整。**裁决**：按 character-runtime.md §3 闭环表「Goal → Action：Life Loop 每周期检查到期 Goal → Decision → Action」归入 AUT-003 周期管线（goal_advance 步骤内「执行尝试」段：规则构建 ActionIntent → V9 既有闸门原样生效，引擎零改动）。
10. **层级追求行动不走 AutonomyPolicy 八步**。八步裁决的是「要不要主动找用户说话」；Sub-Goal 执行是能力行动（9 类 ACTION_TYPES，无 send_message），由 V9 闸门 + goal 级执行冷却 + P5 预算闸约束；静音时段仅屏蔽 user-facing 能力（编排层规则，policy 纯函数零改动）。层级 goal 驱动主动消息的调制语义（LIFE-005 核对记录 17 备案的红线解锁形状）如需实施，与 P6 闸门调制一并在 3.0 裁决。
11. **goal 状态列无 CheckConstraint，状态扩展零 DDL**。`character_goals.status` 为自由 String（db.py L345 无约束）；failed/suspended/abandoned 由服务层转换表（`GOAL_TRANSITIONS`，AUT-004 单点守卫）承载，迁移 0032 仅加 `arbitration_state` JSON 列。v1 既有 finish_goal/expire/cancel 内部收口到同一守卫，允许集对 v1 路径与现状等价（等价重构，V6 回归证明）。
12. **Priority 调制复用 P3 goal_weights 字典，domain 键缺省为 0**。P3 规则表按 v1 type 键产出 `goal.user_care.weight`；AUT-004 按 domain 取值、缺失即 0 调制——零 DEV 代码改动；若需 domain 键调制规则，属 DEV-002 settings JSON 增配（另行灰度），不属于 P6。
13. **v1 行不参与仲裁与层级出口**。仲裁分组按 layer/domain 非空过滤，v1 行（NULL）天然不入组；转换表对 layer=NULL 行开放 v1 既有出口（expired/cancelled），对层级行关闭（Persistence：只有显式完成/放弃/失败才终结）。
14. **供给/观察步骤与 LIFE-003 预算闸的衔接**。goal_supply（AUT-002）与 goal_advance（AUT-003）均为 0 LLM 步骤，不占周期 LLM 预算（`_cycle_llm_budget_exhausted` 统计 LLM capable 步骤）；日配额 degraded → 供给 skip + 重规划 job 不入队（已入队 job 照常消费，规划为低频 main 档一次性成本，handler 不做二次熔断——登记为可接受口径，评审材料）。
15. **suspended 期间工作发现收敛**。suspended goal 的 plan 不进 `has_goal_work`（挂起即不追求）——LIFE-003 Idle 判定「无到期 goal」口径在 P6 的自然延伸，LIFE-003 无需回改（其判定消费本 Phase 供给的集合视图）。abandoned 同理（终态不进任何扫描）。
16. **完成语义的 experience 转写走 Ingest 通道**。README §核心能力 2「Completion → 产出 experience 转写记忆」的落点：AUT-003 goal completed 时经 P1 ingest 任务入 Candidate（**Goal 域不直写 memories**，dependency-graph §5 红线）；转写失败仅 trace，不影响完成状态。

---

## 一致性终检结论（生成时点）

- tasks.md AUT-001~005 每个 Task 均有 Detail，Task ID 完整一致；M1→M4 交付序与各 Detail 依赖声明吻合（AUT-001 存储基座（可提前）→ AUT-002 规划+供给 → AUT-003 观察/调整/执行 → AUT-004 仲裁/生命周期 → AUT-005 Eval Gate（E-AUT-01~04）+ Regression Gate（V6/V7 checklist + 跨会话剧情 ON/OFF 双态）→ 申请开启 `v2_autonomy_advanced_enabled` → v2.0.0 全量）。
- **「随机触发→随机生成消息」被结构性排除**：本 Phase 全部新增行为面均为确定性裁决链——目标生成（供给装配：调制/pattern/salient 事实阈值规则，0 LLM）→ 意图评估（Sub-Goal 执行窗 + V9 闸门 + 主动路径 AutonomyPolicy 八步原样）→ 行为选择（active plan 当前序 + goal_service.select 既有动机）→ 执行（ActionIntent → run_action_planning 既有检定/审计）→ 反馈分析（判据白名单求值 + 失败计数，0 LLM）→ 状态更新（转换表守卫 + trace/decision_records 双留痕）。唯一 LLM（Planning）三重封顶：触发三类枚举、attempt ≤3/goal、校验闸后置入库。
- 全部 Detail 与 v2.0.0 架构裁决一致：Goal 域写面仅 character_goals/goal_plans（+background_jobs 公共底座），不写 Scene/World、不被 Memory 反向写（Memory 经 Ingest 单向）；World/Action 事实经编排投影进域（核对记录 2）；AutonomyPolicy/Action/World 引擎本体零改动；预算硬顶五项（深度≤2/数量≤5/LLM≤3/goal、失败阈值转 failed、执行周期封顶）全部 settings 化且前置闸先行；Flag OFF 逐字节回 v1（goal 层级字段 NULL=走 v1 路径）。
- 「角色状态→目标生成→意图评估→行为选择→执行→反馈分析→状态更新」闭环落点齐备且可解释/可追踪/可回溯/影响未来：每环节有 trace（goal_supply 记账、goal_planning、goal_observation、goal_arbitration）与状态载体（goal_plans 版本/sub_goals JSON/character_goals 状态机），「为什么这么拆/为什么推进/为什么失败/为什么暂停/为什么放弃」五问可答；执行结果经观察改变 Sub-Goal 推进、经失败计数改变计划、经封顶/放弃改变 goal 生命周期——反馈真实收敛回未来状态。
- 未新增 V3.0.0 内容：层级 goal 直接驱动 proactive、行动面资源冲突检测、goal 用户管理面、per-user 规划配额等均仅以「演进项/另行裁决」身份登记；Detail 中出现的既有引擎消费全部为已提交实现的真实接口（含签名与行号锚点）。
- 实现状态：AUT-001~005 均**待实施**（本目录为设计交付）；Flag `v2_autonomy_advanced_enabled` default=false，启用依赖 M4 Gate。
