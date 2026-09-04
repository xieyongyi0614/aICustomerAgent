# Phase 5 Evaluation — Life Loop

> Gate 未全过不得申请开启 `v2_life_loop_enabled`。

## 指标与门槛（Eval Gate）

| ID | 指标 | 测法 | 门槛 |
|---|---|---|---|
| E-LIFE-01 | Trigger 持久化 | kill -9 后 pending trigger 保留且不重复触发 | 100% |
| E-LIFE-02 | 周期完整性 | 任一周期 loop_runs 步骤/时长/LLM 用量完整；引擎零改动 | 100% |
| E-LIFE-03 | 成本合规 | 7 天无消息空跑：Idle 期间 0 LLM；总量 ≤ 日预算；熔断只降后台 | 100% |
| E-LIFE-04 | Outbox 不丢不重 | 同一 Action 重放 N 次 → world_event/candidate 各恒为 1；崩溃续走 | 100% |
| E-LIFE-05 | 主动行为质量 | 触发有依据（trigger 命中记录）；抽样人评引用相关记忆；无消息风暴 | 合理率 ≥0.9；风暴=0 |

## P5 专属场景

- 7 天空转演练（Idle 进出、配额熔断、恢复）。
- 幂等重放：outbox 三段事务各自崩溃点注入。
- 「为什么主动/为什么没动」六问 trace 抽查。

## Regression Gate

见 [regression-checklist.md](regression-checklist.md)。**V7 autonomy checklist 全量重跑是本 Phase 硬门。**
