# Phase 5 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) LIFE-001~006 一一对应，无遗漏。所有 Detail 锚定 Phase 1~4 真实实现（基线：`feat/v2.0.0` @ 67ad389，MEM-001~011、REF-001~007、DEV-001~006、REL-001~004 已全部提交，迁移链至 0027_relationship_narrative_meta），未与 v2.0.0 Architecture / Phase 5 README 冲突，未提前设计 Phase 6 Autonomy 能力。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| LIFE-001 | [LIFE-001.md](LIFE-001.md) | Foundation/持久化 Trigger Registry | P1 MEM-001/009（已交付） | trigger_evaluator.py `_followup_registry` 内存 dict（L26）/ `register_followup`（L30）/ `poll_due_followup`（L52）/ `poll_due_actions`（L73）/ `evaluate_inactivity`（L137）、memory_service.py `_register_followups`（L102）、autonomy_engine.py 信号优先级（L249）/ `mark_action_reported` 回调（L361）、db.py `BackgroundJobRow` 协议先例（L932）、job_worker.py SKIP LOCKED 认领（L89） |
| LIFE-002 | [LIFE-002.md](LIFE-002.md) | Core/Loop Controller | LIFE-001 | main.py lifespan 三循环（L52-67）、autonomy_engine.py `tick`（L378）/ `_snapshot_for`（L113）、world_engine.py `run_maintenance`（L659）/ `collect_facts`（L627）、action_engine.py `_process_due_retries`（L269）/ `_expire_planned`（L291）、state_service.py `load_states` 读即衰减（L98）、goal_service.py 到期规则（L187）、post_process.py 用户写锁（L383）、trace_collector.py TRACE_STEP_NAMES（L13） |
| LIFE-003 | [LIFE-003.md](LIFE-003.md) | Core/Idle 与预算 | LIFE-002 | db.py `LlmCallRecordRow`（L485，无 user_id）、llm_call_repository.py `list_since`（L135）、autonomy_engine.py 日行动上限（L87）、post_process.py `run_budget_observer`（L279，行为预算非 LLM）、settings.py 无 quota/circuit 配置实证、job_worker.py 退避协议（L152） |
| LIFE-004 | [LIFE-004.md](LIFE-004.md) | Core/Outbox 一致性 | LIFE-002, P1 MEM-002（已交付） | action_engine.py `integrate_result` 四通道汇点（L130-156）、action/capabilities/reminder.py 执行期直写 `world_engine.create_event`（L62）、memory_bridge.py `deliver_action_memory` 直写（L74）、relationship_bridge.py `deliver_action_signal`、memory2/ingest.py `ingest_from_action_record`（L167）/ `ingest_from_world_event`（L212）幂等键、post_process.py 四源补扫（L206-229）、models/action.py 六态（L35）、settings.py `action_enabled=False`（L228） |
| LIFE-005 | [LIFE-005.md](LIFE-005.md) | Integration/周期检索与反思检查 | LIFE-002, P1 MEM-006, P2 REF-003/004（已交付） | memory2/retriever.py `retrieve`（L257，Python 侧打分）、db.py `memories.salience`（L125）、reflection/triggers.py `trigger_for_user` 全链（L52）/ 日桶键（L279）、reflector.py handler（L66）、proactive_executor.py `execute`（L103）/ `generate(recent_context="")`（proactive_chain.py L53）、autonomy_engine.py `_snapshot_for` 无记忆输入实证 |
| LIFE-006 | [LIFE-006.md](LIFE-006.md) | Observability/Evaluation | LIFE-002 | trace_collector.py TRACE_STEP_NAMES 48 项（L13）、db.py `runtime_traces`（L684）/ `decision_records`（L516）、models/evaluation.py IssueCode 36 码、evaluation_rules/autonomy.py 仅 TimingViolationRule（L23）、offline_evaluator.py `_aggregate` stats 模式（L170-199）、tests/unit/test_evaluation_models.py 计数断言 |

---

## 与 Phase 1~4 实现 / 既有架构的核对记录（冲突与口径登记，不修改架构）

> 按「发现冲突先记录、给出调整建议、不自行修改架构」的要求逐条登记。各项均为 Task Detail 内已给出落地口径的偏差/缺口，供实施前评审确认。正文引用形如「核对记录 N」。

1. **`llm_call_records` 无 user_id 列，per-user 日配额无数据承载**（db.py L485-513，仅 request_id/turn_id/call_site 等维度）。tasks.md LIFE-003 只要求「全局日 LLM 配额熔断」，与架构 llm-orchestration.md §3「全局每日配额」一致——落地取全局口径，聚合走时间索引 COUNT+SUM。建议：若灰度后需要 per-user 配额（多租户公平性），属 schema 扩展另行裁决。
2. **Goal 到期是 turn 基准，无时间列**（`character_goals.expires_at_turn`，db.py L361；唯一过期调用点 goal_service.py:187-190，由 post_process `run_goal_review` 每轮驱动）。tasks.md LIFE-002 Inputs 的「到期 goals」在生活时刻（turn 不前进）落为**补扫语义**：检查上次对话结束时已应到期而未处理的 goal。time-based 到期（due_at）依赖 P6 AUT-001 的存储扩展，本 Phase 不提前设计。
3. **能力执行期直写 world 与 outbox 语义的冲突（本 Phase 最重要边界认定）**。v1 铁律「世界写失败 = 行动失败」（reminder.py 文件头）由能力执行期直写实现（reminder.py L62 / world_action.py 各 op）；data-flow.md §2.1 要求 world 写移到 outbox 消费侧。落地口径：Flag ON 时能力内**跨域写调用点**改为返回 world_ops 描述符、消费器调同名引擎函数落库——认定为「执行器编排的 Extend→Replace」（tasks.md 红线括注），六态状态机/六闸门/CapabilityExecutor/world_engine 函数体零改动。**语义变化**：世界侧失败从「行动 failed」变为「outbox 重试×5 → 死信 failed+trace」的最终一致（行动检定/校验失败语义不变）。建议：实施前评审确认该边界认定；若评审认为能力函数体不可触碰，备选方案是保留执行期直写、outbox 只覆盖 memory/relationship 通道（弱一致性，不满足 E-LIFE-04 全链断言，需改验收口径）。
4. **action memory 双通道并存且 v1 直写无 v2 门控**。`memory_bridge.deliver_action_memory`（action_engine.py:153 调用，仅受 `action_memory_policy_enabled` 门控）与 P1 `ingest_from_action_record` 补扫（post_process.py:206-208，`v2_memory_enabled` 门控）并存，靠 evaluator `duplicate_exact` 对同模板内容兜底避免双记忆。落地口径：outbox 模式下消费器不调 v1 直写（单通道收口）；建议：v1 直写在 `v2_memory_enabled` 下的全局去留（对齐 REL-001 旁路关停先例）属独立收口决策，另行 Task/评审。
5. **salience 无 SQL 排序与索引**（retriever 打分全在 Python 侧，memory_repository 仅 created_at 排序）。LIFE-005 新增 `list_top_salience` 仓储函数（过滤后小集合排序，P0 规模无索引）；建议：用户/记忆规模上来后补 `(user_id, character_id, status, salience)` 索引，实施时在 Detail 交付记录确认规模假设。
6. **两处潜在 NameError 缺陷**：①trigger_evaluator.py L109/L134 在 except 中调 `logger.exception` 但模块未定义 logger——异常路径二次 NameError；②autonomy_engine.py:50-51 `reset_seen_keys` 引用从未定义的 `_seen_dedupe_keys`（当前无调用方，死代码）。落地口径：①随 LIFE-001 修复（两行，零行为变化）；②不动，建议另行清理确认。
7. **「5 个常驻循环」的归并范围口径**。tasks.md Problem 称 5 循环；main.py lifespan 实为 6 个 task（memory reclaim / v2 job worker / autonomy / observability retention / world maintenance / action retry）。Scope 只列归并 autonomy/world/action 三者——memory reclaim 与 observability retention 属基础设施循环、v2 job worker 是 P1 底座，均不归并（归并它们只会在 Controller 上叠基础设施职责）。落地口径与 Scope 一致，Problem 的计数偏差在此登记。
8. **trigger 状态机的重试内边**。tasks.md State Machine 列 `pending→due→fired→done|cancelled`，但「处理失败防无限重试」必须存在 fired→pending（attempt+1+cooldown）的回归边。落地口径：状态机表补充该内边（重试不是新状态），tasks.md 的 attempt_count 防护语义由此实现；终态仍是 done|cancelled。
9. **loop_runs 记账列在 LIFE-002 建表时一次到位**（llm_call_count/token_total/budget_state 随迁移 0029 创建），LIFE-003 零 DDL。tasks.md LIFE-003 Data Changes 列「loop_runs 记账字段」——以建表包含替代二次迁移，Field 归属声明在此登记（两 Task 的 Data Changes 合并满足，交付序不变）。
10. **维护时间戳为进程内存态；多进程下维护可能重复执行**。world/action/outbox/reconcile 的「上次执行时刻」不落表（幂等扫表使丢态无害）；P0 单进程假设成立（R14）。多进程部署时维护步骤会按进程各自触发（幂等无害，成本冗余），trigger claim 与 outbox 消费的 SKIP LOCKED 已保证正确性。建议：Worker 抽离（R14 阈值触发）时升级为表列协调，届时另行设计。
11. **全局熔断的执行面范围**。llm-orchestration.md §3 的熔断裁决覆盖「后台任务降级为只记 Candidate 不评估」，横跨 P1 评估兜底与 P2 反思执行面；但 P1/P2 已有独立限额（fallback rate cap / 反思日额度）且改动需触碰已交付灰度域。落地口径：LIFE-003 熔断执行面 = Life Loop 周期步骤（decision/proactive）；`check_daily_budget` 作为公共基础件交付，P1/P2 接线留作灰度观察后决策。建议：若评审要求本 Phase 全量接线，属 P1/P2 域内改动，另行 Task。
12. **Idle 判定「状态平稳」条件的落地口径**。tasks.md Scope 列「无 due trigger 且无到期 goal 且状态平稳→跳过整轮」；落地取三 work 项（due trigger / goal 补扫 / 维护与 outbox）联合承载「状态平稳」——不引入独立的状态波动检测（无依据触发源，R8 风险）。此为对 Scope 措辞的收窄解释，非范围削减（行为面等价：状态需要关注的用户必有 trigger/goal 承载）。
13. **Idle 轮不落 loop_runs 行**。E-LIFE-03「Idle 期间 0 LLM」与写放大防护（每 60s 一行空 run 是纯噪音）裁决为：Idle 短路不建 run，「为什么没运行」由「无 loop_runs 行 + has_due=false + 无维护到期」组合回答，trace 面以六问断言覆盖。若评审要求空转也留痕（审计偏好），可加采样留痕开关，另行确认。
14. **Reflection 触发器不合并入 trigger_registry**。REF-003 是「证据门槛驱动的反思调度」（日桶幂等 + 独立额度），trigger_registry 是「交互类触发信号的生命周期账本」——两者触发源、幂等口径、消费方均不同，合并只会让 registry 承载反思业务语义（违反编排域不持有业务语义裁决）。落地口径：两套触发语义并存，LIFE-005 经 REF-003 公共入口调用。若评审认为应统一触发面，属 P2 域重构，另行裁决。
15. **v9 action 默认关闭是 outbox 端到端灰度的前置缺口**（`action_enabled: bool = False`，settings.py:228；tasks.md LIFE-004 Non-Scope 已列「v9 action 默认启用为本 Task 前置（评审项，非本 Task 改动）」）。落地口径：本 Task 不改默认值，测试以显式开启 action 的环境执行；灰度推进依赖该评审项结论，M4 验收时必须显式确认。
16. **proactive 消息队列不在 outbox 范围**。`proactive_actions` 表（深度 1 队列 + dedupe）已是持久化队列且有自身状态机（七态），outbox 只覆盖 v9 Action 结果链（Action→World→Event→Memory）。tasks.md LIFE-004 Scope 的「ActionExecutor 同事务写 outbox」口径即此；主动消息投递的可靠性由既有队列语义承载，不重复建设。
17. **周期检索结果不进 AutonomyPolicy 闸门**。tasks.md LIFE-005 Scope「检索结果进 Decision 输入」的落地口径=trace 可见面 + proactive 生成上下文（recent_context）；不做 PolicySnapshot 扩展（红线：AutonomyPolicy 纯函数本体零改动，新增闸门条件即改判定）。建议：若评审认为记忆显著度应参与「是否主动」判定（如「未兑现嘱托加权」），属架构变更（红线解除裁决），另行处理。
18. **digest 注入的载体取舍（contextvar vs 参数传递）**。`autonomy_engine.tick` 本体零改动导致 Controller 无法向其内部的 `proactive_executor.execute` 传参。落地口径：contextvar 采集（V7.8 trace 采集同款模式），`proactive_executor.execute` 内读取（编排层 Extend），默认 None 空串回退保证前台零漂移。备选：给 execute/tick 加穿透参数（改两处签名，触碰 autonomy_engine 文件）——若评审认为 contextvar 隐式传递不可接受，切换备选并接受引擎文件的一处签名 Extend。
19. **周期快查不触 reinforce 写回**。对话路径 retriever 命中会投 `record_reinforce`（内存缓冲批量 flush，P1 语义）；Life Loop 周期快查是调度面读，不是「角色想起」的对话事件，投 reinforce 会让闲置期记忆自我强化（衰减机制失真）。落地口径：快查零写（含 reinforce 缓冲）；若评审认为「生活时刻想起」也应计强化，属 P1 语义扩展，另行裁决。
20. **memory digest 不进 Context Architect 预算体系**。digest 是 proactive 生成的 recent_context（proactive_chain 既有形参位），不是对话 Context 段，不占/不挤 800 检索类合并预算（R2 防护以 digest 自身 600 字符硬顶 + Context 体系互不挤占落地）。与 REL-002/003「结构化投影不进检索合并预算」同一归类逻辑。

---

## 一致性终检结论（生成时点）

- tasks.md LIFE-001~006 每个 Task 均有 Detail，Task ID 完整一致；M1→M4 交付序与各 Detail 依赖声明吻合（LIFE-001 → LIFE-002 → {LIFE-003, LIFE-004} → LIFE-005（消费 002 步骤位 + P1/P2 已交付能力）→ LIFE-006 收口 → Eval Gate（E-LIFE-01~05）+ Regression Gate（V7 checklist 全量 + kill -9 演练 + 7 天空跑 + 幂等重放）→ 申请开启 `v2_life_loop_enabled`）。
- 全部 Detail 与 v2.0.0 架构裁决一致：**Life Loop 是编排域**（调用一切不被调用、不持有业务语义、唯一写面=自己域的三张表 trigger_registry/loop_runs/outbox_events）；**红线全量遵守**（AutonomyPolicy 纯函数、Action/World 引擎本体零改动，Flag 分叉仅限执行器编排并在核对记录 3 显式登记边界认定）；**闭环数据流沿 data-flow.md §2.1 三段事务**（Action→Outbox→World→Event→Ingest→Candidate，跨域零直写）；**成本铁律逐条回答**（Idle 零调用、周期 LLM 仅 Decision 命中、全局日配额熔断、前台永不熔断）；Flag OFF 逐字节回 v1。
- 「角色状态→当前目标→关系状态→历史记忆→Reflection 判断→产生行为→记录结果」的管线落点：状态衰减（state_update 步骤，state_service.load_states 既有纯规则）→ 目标（goal_check 补扫 + goal_service.select 经 development_weights 调制）→ 关系（PolicySnapshot 既有 R1~R5 + patterns 参考）→ 记忆（memory_retrieval 显著度快查进生成上下文与 trace）→ 反思（reflection_check 复用 REF-003 门槛与额度）→ 行为（autonomy_engine.tick 原样决策与执行）→ 记录（loop_runs/trigger_registry/decision_records/outbox 全链账本，六问可答）——每一步有原因（记账）、可解释（trace）、可追踪（三点连线）、影响后续状态（trigger 生命周期/记忆沉淀/goal 补扫反馈下轮）。
- 全部 Detail 基于已提交实现设计，未假设不存在的接口；三张新表（迁移 0028/0029/0030）与全部行为性口径偏差已在核对记录 1~20 显式登记并给出最小落地口径与备选方案。
- 未提前设计 Phase 6：goal 不新增 due_at/层级/Planning/Sub-Goal 判据（AUT-001/002/003），预算不做差异化配额，评估不做 goal consistency——Detail 中出现的 P6 相关面仅以「后续消费方/另行裁决」身份出现。
