# Phase 5 Tasks — Life Loop

> Schema 与分层约定同 [phase-1](../phase-1-memory/tasks.md)。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Foundation:   LIFE-001 持久化 Trigger Registry
Core:         LIFE-002 Loop Controller / LIFE-003 Idle 与预算 / LIFE-004 Outbox
Integration:  LIFE-005 周期检索与反思检查
Observability+Evaluation: LIFE-006
红线: AutonomyPolicy 触发判定纯函数与 Action/World 引擎本体零改动（version-boundary Extend→Replace 仅限执行器编排）
```

## LIFE-001 持久化 Trigger Registry（Foundation）

- **Priority**: P0
- **Objective**: trigger_registry 表替代内存 dict，消灭重启丢失缺口
- **Problem**: v1 Trigger Registry 在内存 dict（v1 审计问题 6 实证），重启即丢 followup/action_due，角色「答应的事」凭空消失
- **Scope**: trigger_registry 表（due_at/priority/cooldown_until/attempt_count/payload）；TriggerEvaluator 读写迁移；迁移期双写（内存+表）一个版本后切只读表
- **Non-Scope**: 触发判定逻辑（AutonomyPolicy 纯函数）不动；不改前台通知路径
- **Inputs**: v1 触发信号（inactivity/followup/action_due）
- **Outputs**: 持久化 Trigger
- **Dependencies**: P1 MEM-001（background_jobs 先行）
- **Architecture References**: [../../architecture/overview.md](../../architecture/overview.md) §4；[../../architecture/risk.md](../../architecture/risk.md) R14
- **Domain Boundary**: Autonomy/Life Loop 编排域（表为本域；判定逻辑留在 AutonomyPolicy）
- **Data Changes**: 新表 trigger_registry；唯一键防重复触发
- **Runtime Flow**: 触发信号 → 判定（纯函数） → upsert registry → due 扫描消费
- **LLM Usage**: NONE
- **State Machine**: pending→due→fired→done|cancelled；attempt_count 防无限重试
- **Idempotency**: trigger_key(user+type+entity) 唯一；重复登记被拦截；重启后 due trigger 完整保留
- **Feature Flag**: `v2_life_loop_enabled`，OFF=走 v1 内存 dict 路径
- **Error/Failure**: DB 失败→回退内存路径（双写期）；表损坏→对账任务修复
- **Observability**: trigger trace（登记/触发/跳过原因）
- **Testing**: Unit=状态机；Integration=kill -9 演练；Idempotency=重复登记
- **Acceptance Criteria**: 给定 pending followup trigger，当进程 kill -9 后重启，那么 trigger 保留且到期正常触发不重复
- **Regression**: V7 autonomy checklist
- **Evaluation**: [evaluation.md](evaluation.md) E-LIFE-01
- **Risk**: 双写期不一致→以表为准对账任务

## LIFE-002 Life Loop Controller（Core）

- **Priority**: P0
- **Objective**: 统一周期编排：Perception→State Update→Goal Check→Memory Retrieval→Reflection Check→Decision→Action→World Event
- **Problem**: 5 个常驻 asyncio 循环各自为政（v1 审计问题 6），无统一预算/优先级/Idle，「角色持续存在」只是 60s tick
- **Scope**: loop_runs 表；归并 autonomy tick / world maintenance / action retry 调度入口（引擎函数原样复用）；步骤管线（每步可 Flag/条件跳过）
- **Non-Scope**: 编排层只调度；业务逻辑留各域服务；不新增 LLM 链；不持有业务状态
- **Inputs**: due triggers / 到期 goals / outbox 事件
- **Outputs**: 周期执行 + loop_runs 记录
- **Dependencies**: LIFE-001
- **Architecture References**: [../../architecture/character-runtime.md](../../architecture/character-runtime.md) §2.2；[../../architecture/overview.md](../../architecture/overview.md) §1 LL 节点
- **Domain Boundary**: 编排域（调用一切，不被业务域调用；不写业务域表）
- **Data Changes**: 新表 loop_runs
- **Runtime Flow**: due 扫描（纯 SQL） → Idle 判定 → 按序执行步骤（每步前置条件） → loop_runs 落账
- **LLM Usage**: 周期内 LLM 仅出现于步骤内部既有链（Decision 命中时 proactive）；Controller 本身 0 LLM
- **State Machine**: loop_run: started→perception→…→done|aborted(预算/失败)；步骤级 skip 合法
- **Idempotency**: run_id 幂等；同 trigger 不重复入 run（registry 状态保证）
- **Feature Flag**: `v2_life_loop_enabled`，OFF=v1 autonomy tick 原样
- **Error/Failure**: 步骤异常→记 run aborted+原因，下轮恢复；单步失败不阻塞其他 trigger
- **Observability**: loop_runs 记步骤/时长/LLM 调用/Token；「为什么运行/为什么没运行」可答
- **Testing**: Unit=步骤编排与跳过；Integration=空转演练；Regression=V7 checklist 重跑（引擎零改动证明）
- **Acceptance Criteria**: 给定 due trigger+到期 goal，当周期执行，那么两步均完成且 loop_runs 完整；给定引擎函数，那么与 v1 输出一致（零改动）
- **Regression**: V7 autonomy regression-checklist 全量
- **Evaluation**: [evaluation.md](evaluation.md) E-LIFE-02
- **Risk**: 归并引入回归→引擎零改动红线+V7 checklist 兜底

## LIFE-003 Idle 与预算控制（Core）

- **Priority**: P0
- **Objective**: 成本封顶与空转——明确「角色什么时候什么都不做」
- **Problem**: 任务书 §二十二禁 `while true: call LLM()`；无 Idle/Budget 则 Life Loop 是成本无底洞（R9）
- **Scope**: Idle 判定（纯规则：无 due trigger 且无到期 goal 且状态平稳→跳过整轮）；每周期步骤预算；全局日 LLM 配额熔断；loop_runs 记账
- **Non-Scope**: 前台路径永不熔断；熔断只降级后台；不做智能预测
- **Inputs**: 状态/goal/trigger 快照、llm_call_records 用量
- **Outputs**: Idle/预算决策 + 记账
- **Dependencies**: LIFE-002
- **Architecture References**: [../../architecture/llm-orchestration.md](../../architecture/llm-orchestration.md) §3 预算熔断；[../../architecture/risk.md](../../architecture/risk.md) R9
- **Domain Boundary**: 编排域（配额为横切基础设施读写）
- **Data Changes**: loop_runs 记账字段
- **Runtime Flow**: 周期开始 → Idle 判定 → [Idle→空转仅时钟检查, 0 LLM | 运行→步骤预算扣减→超限降级为只记 Candidate]
- **LLM Usage**: 不直接调用；预算约束其他步骤的 LLM
- **State Machine**: loop: running→idle(空转模式)|active；预算: ok→degraded(后台降级)→恢复
- **Idempotency**: 记账幂等（run 内聚合）
- **Feature Flag**: `v2_life_loop_enabled`
- **Error/Failure**: 用量查询失败→保守按预算 80% 运行；判定异常→默认 Idle 兜底（宁可不跑）
- **Observability**: loop_budget trace（当前用量/限额/决策）——「为什么降级/为什么 Idle」可答
- **Testing**: Integration=7 天空转长跑+熔断注入；Unit=判定规则
- **Acceptance Criteria**: 给定 7 天无用户消息，当 Life Loop 运行，那么 Idle 期间 LLM 调用为 0 且总量在日预算内；给定配额超限，那么后台降级且前台不受影响
- **Regression**: Flag OFF 无行为
- **Evaluation**: [evaluation.md](evaluation.md) E-LIFE-03
- **Risk**: Idle 判定过激漏掉该动时刻→due 驱动兜底+观测调参

## LIFE-004 Outbox 一致性（Core）

- **Priority**: P0
- **Objective**: Action→World→Event→Memory 链路不丢不重（§九闭环的落点）
- **Problem**: v1 事件落库后经验沉淀通道断裂；无 outbox 则跨域写入无事务保障、失败无恢复
- **Scope**: outbox_events 表；ActionExecutor 同事务写 outbox；消费器（World→Event→Candidate）幂等；失败重放；`v2_action_outbox_enabled` 子闸
- **Non-Scope**: World 消费逻辑复用既有引擎；不新增能力；v9 action 默认启用为本 Task 前置（评审项，非本 Task 改动）
- **Inputs**: Action 执行结果
- **Outputs**: world_events + MemoryCandidate（幂等）
- **Dependencies**: LIFE-002, P1 MEM-002
- **Architecture References**: [../../architecture/data-flow.md](../../architecture/data-flow.md) §2.1/§3；[../../dependency-graph.md](../../dependency-graph.md) §5
- **Domain Boundary**: Action 写 outbox（同事务）；World 消费 outbox（独立事务）；Ingest 消费 world_events——三段各自事务，禁止跨域直写
- **Data Changes**: 新表 outbox_events（event_type/payload/idempotency_key/status）
- **Runtime Flow**: Action 成功 → 同事务(records+outbox) → WorldEngine 消费 → world_events → Ingest → candidate → 标记 done
- **LLM Usage**: NONE
- **State Machine**: outbox: pending→consumed|failed；failed 按幂等键重放
- **Idempotency**: 幂等键=action_id；重放不产生第二个 world_event/候选
- **Feature Flag**: `v2_action_outbox_enabled`（总闸 `v2_life_loop_enabled` 子闸），OFF=走 v1 直写路径
- **Error/Failure**: 消费失败→重试（指数退避 max5）→死信 failed+reason；进程重启→pending 重放
- **Observability**: outbox 状态可查；链路 trace 贯穿 action→world→ingest
- **Testing**: Integration=幂等重放+故障注入；Unit=状态机
- **Acceptance Criteria**: 给定同一 Action 结果重放三次，那么 world_event 与 candidate 各恒为 1；给定消费中途崩溃，那么重启后链路续走且最终一致
- **Regression**: Flag OFF golden；v9 checklist（启用后）
- **Evaluation**: [evaluation.md](evaluation.md) E-LIFE-04
- **Risk**: v9 默认开启行为变化→独立子闸灰度

## LIFE-005 周期记忆检索与反思检查（Integration）

- **Priority**: P1
- **Objective**: 生活时刻「想得起、会反思」——Life Loop 周期内接入 Memory 检索与 Reflection Check
- **Problem**: §九/§十三要求 Life Loop 内含 Memory Retrieval 与 Reflection Check 两步；缺失则用户不说话时角色失忆且不反思，闭环断裂
- **Scope**: 周期内 Memory Retrieval（高显著度快查，top 显著度）；Reflection Check（复用 P2 REF-003 触发器与额度）
- **Non-Scope**: 检索仅读；反思不超日额度；不写任何域
- **Inputs**: 当前状态、trigger、memories
- **Outputs**: 检索结果进 Decision 输入；反思任务按额度入队
- **Dependencies**: LIFE-002, P1 MEM-006, P2 REF-003
- **Architecture References**: [../../architecture/character-runtime.md](../../architecture/character-runtime.md) §2.2
- **Domain Boundary**: 编排域调用 Memory/Reflection 只读接口
- **Data Changes**: 无
- **Runtime Flow**: 周期 → 显著度快查 → Decision 输入组装 → Reflection Check → [达标→REF 入队 | 不足→跳过]
- **LLM Usage**: 检索 NONE；反思经 REF-003 既有额度
- **State Machine**: 无
- **Idempotency**: 同周期不重复入队
- **Feature Flag**: `v2_life_loop_enabled`
- **Error/Failure**: 检索失败→Decision 输入降级（无记忆上下文）；反思额度满→跳过
- **Observability**: loop_memory trace（检索条数/反思检查结果）
- **Testing**: Integration=端到端；抽样人评=主动消息引用相关记忆
- **Acceptance Criteria**: 给定高显著度记忆存在，当周期运行，那么主动决策输入含该记忆且 trace 可见；给定反思额度已满，那么不再入队
- **Regression**: Flag OFF 无行为
- **Evaluation**: [evaluation.md](evaluation.md) E-LIFE-05
- **Risk**: 周期检索成本→显著度门槛+缓存

## LIFE-006 Goal/Decision Trace 与评估（Observability / Evaluation）

- **Priority**: P1
- **Objective**: 「为什么角色主动行动/为什么没行动」可答；autonomy/life-loop 可测
- **Problem**: 主动行为不可归因则无法验收「主动性合理性」，也无法排查消息风暴
- **Scope**: trigger→decision→action 全链 trace 步骤；Evaluation 新增 autonomy/life-loop 规则（触发合理性、成本合规）
- **Non-Scope**: 只读旁路
- **Inputs**: 周期事件
- **Outputs**: trace + 评估报告
- **Dependencies**: LIFE-002
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Autonomy/Life Loop 行
- **Domain Boundary**: 横切质量平面
- **Data Changes**: 无
- **Runtime Flow**: 周期事件 → trace；离线 → 指标
- **LLM Usage**: Judge 采样
- **State Machine**: 无
- **Idempotency**: 可重复执行
- **Feature Flag**: 无
- **Error/Failure**: Judge 失败→skipped 重跑
- **Observability**: 即本 Task
- **Testing**: Integration=trace 完整性
- **Acceptance Criteria**: 给定任一主动行为，当查询 trace，那么可回溯完整 trigger→decision→action 链；给定触发场景集，那么无消息风暴且成本合规
- **Regression**: 无 golden 影响
- **Evaluation**: E-LIFE-01~05 汇总
- **Risk**: 无

---

## Phase 5 Milestone（交付序）

```text
M1 Foundation:  LIFE-001（等 P1 MEM-001/009）
M2 Core:        LIFE-002 → {LIFE-003, LIFE-004}
M3 Integration: LIFE-005（等 P1+P2）
M4 Acceptance:  LIFE-006 → Eval Gate + Regression Gate（含 V7 checklist 与 7 天空跑演练）→ 申请开启 v2_life_loop_enabled
```


---

## 实现状态（2026-09-07 起，逐 Task 回写）

```text
LIFE-001 已实现（迁移 0028 trigger_registry 五态状态机 + trigger_key 唯一 +
priority 编码 v1 信号优先级 + (status,due_at)/(user_id,status) 双索引；
trigger_registry_repository：register upsert 幂等（终态复活）/register_and_claim
重检型单事务领取/claim_due_followups 原子交接（状态守卫防双领）/mark_fired/
complete/fail_for_retry 指数退避+死信/cancel/has_due（include_types 供 Idle 排除
inactivity）/recover_stale 对账；trigger_evaluator Flag ON 表通道优先 + 内存路径
兜底迁移窗口 drain：register_followup 双写+消费同步 pop、poll_due_followup 一次性
消费（对齐 v1 pop 语义）、evaluate_inactivity/poll_due_actions register_and_claim
领取门、mark_action_reported 补 done；两处 v1 NameError 缺陷已随 fix c7f5768 修复；
18 测试绿 + V7/V9 回归 51 例绿）。
```
