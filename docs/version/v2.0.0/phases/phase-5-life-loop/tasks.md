# Phase 5 Tasks — Life Loop

## LIFE-001 持久化 Trigger Registry

- **Priority**: P0
- **Goal**: 消灭内存 dict 持久化缺口
- **Scope**: trigger_registry 表（due_at/priority/cooldown_until/attempt_count/payload）；TriggerEvaluator 读写迁移；迁移期双写（内存 + 表）一个版本后切只读表
- **Dependencies**: P1 MEM-001（background_jobs 先行落地）
- **Input**: v1 触发信号（inactivity/followup/action_due）
- **Output**: 持久化 Trigger
- **Implementation Boundary**: 触发判定逻辑（AutonomyPolicy 纯函数）不动
- **Acceptance Criteria**: 重启后 due trigger 完整保留且不重复触发
- **Testing**: kill -9 演练 + 幂等测试
- **Risk**: 双写期不一致 → 以表为准的对账任务

## LIFE-002 Life Loop Controller

- **Priority**: P0
- **Goal**: 统一周期编排
- **Scope**: loop_runs 表；归并 autonomy tick / world maintenance / action retry 的调度入口（引擎函数原样复用）；Perception→…→Action 步骤管线
- **Dependencies**: LIFE-001
- **Input**: due triggers / 到期 goals / outbox
- **Output**: 周期执行 + loop_runs 记录
- **Implementation Boundary**: 编排层只调度；业务逻辑留在各域服务
- **Acceptance Criteria**: 单周期每步可跳过（Flag/条件）；trace 完整覆盖各步
- **Testing**: 步骤编排单测 + 空转演练
- **Risk**: 归并引入回归 → 引擎零改动红线 + v7 regression-checklist 重跑

## LIFE-003 Idle 与预算控制

- **Priority**: P0
- **Goal**: 成本封顶与空转
- **Scope**: Idle 判定（纯规则）；每周期步骤预算；全局日 LLM 配额熔断（llm-orchestration §3）；loop_runs 记账
- **Dependencies**: LIFE-002
- **Input**: 状态/goal/trigger 快照
- **Output**: Idle/预算决策 + 记账
- **Implementation Boundary**: 前台路径永不熔断；熔断只降级后台
- **Acceptance Criteria**: 7 天无消息场景 LLM 调用 0（Idle）；预算超限后周期任务降级且留痕
- **Testing**: 空转长跑 + 配额熔断注入
- **Risk**: Idle 判定过激（漏掉该动的时刻）→ due 驱动兜底 + 观测调参

## LIFE-004 Outbox 一致性

- **Priority**: P0
- **Goal**: Action→World→Memory 链路不丢不重
- **Scope**: outbox_events 表；ActionExecutor 同事务写 outbox；消费器（World→Event→Candidate）幂等；失败重放
- **Dependencies**: LIFE-002, P1 MEM-002
- **Input**: Action 结果
- **Output**: World Event + MemoryCandidate（幂等）
- **Implementation Boundary**: v9 action_enabled 默认开为该 Task 前置（评审项）；World 消费逻辑复用既有引擎
- **Acceptance Criteria**: 重放不产生第二个 world_event/候选；失败链路可追（outbox 状态）
- **Testing**: 幂等重放 + 故障注入
- **Risk**: v9 能力默认开启带来行为变化 → 独立子闸 `v2_action_outbox_enabled` 灰度

## LIFE-005 周期记忆检索与反思检查

- **Priority**: P1
- **Goal**: 生活时刻「想得起、会反思」
- **Scope**: 周期内 Memory Retrieval（高显著度快查）+ Reflection Check（P2 触发器复用）
- **Dependencies**: LIFE-002, P1 MEM-006, P2 REF-003
- **Input**: 当前状态 + trigger
- **Output**: 检索结果进 Decision 输入；反思任务按额度入队
- **Implementation Boundary**: 检索仅 top 高显著度（成本约束）；不写任何域
- **Acceptance Criteria**: 主动消息内容引用了相关记忆（抽样人评）；反思不超日额度
- **Testing**: 主动行为质量抽样评估
- **Risk**: 周期检索成本 → 显著度门槛 + 缓存

## LIFE-006 Goal Trace 与评估

- **Priority**: P1
- **Goal**: 「为什么角色主动行动」可答
- **Scope**: trigger→decision→action 全链 trace 步骤；Evaluation 新增 autonomy/life-loop 规则（触发合理性、成本合规）
- **Dependencies**: LIFE-002
- **Input**: 周期事件
- **Output**: trace + 评估报告
- **Implementation Boundary**: 只读旁路
- **Acceptance Criteria**: 任一主动行为可回溯完整 trigger 链
- **Testing**: trace 完整性测试
- **Risk**: 无
