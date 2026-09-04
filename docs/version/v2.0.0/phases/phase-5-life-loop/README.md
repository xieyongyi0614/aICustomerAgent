# Phase 5 — Life Loop

> Flag：`v2_life_loop_enabled`（总闸）
> 依赖：Phase 3/4（周期内容）、P1 MEM-009（background_jobs 底座）｜复用：Autonomy/Action/World 全部引擎

## 目标

用户不说话，角色也在「生活」：

```text
Perception → State Update → Goal Evaluation → Memory Retrieval
  → Reflection Check → Decision → Action → World Event → Experience ↺ 下一周期
```

v1 的 60s autonomy tick（trigger→decision→proactive message）是本循环的一个子集。

## 解决的问题

1. Trigger Registry 在内存 dict，重启即丢（v1 审计确认的持久化缺口）。
2. 5 个常驻 asyncio 循环各自为政，无统一预算/优先级/Idle。
3. 「什么时候运行、为什么不运行、成本多少」不可回答。

## 核心能力

1. **统一 Life Loop Controller**：归并 autonomy worker 与 maintenance 循环的调度权（引擎本体不动）；触发源三类——Schedule（低频时钟）、Event（outbox/trigger 表）、Threshold（状态/目标越限）。
2. **持久化 Trigger Registry**：trigger_registry 表替代内存 dict；每条 Trigger 有 due_at、priority、cooldown_until、attempt_count。
3. **四控制**：Priority（周期内步骤排序）、Cooldown（复用 v7 亲密度调制间隔）、Budget（每周期步骤预算 + 全局日 LLM 配额熔断）、Idle（无 due trigger 且无到期 goal 且状态平稳 → 跳过整轮，0 成本）。
4. **Outbox 一致性**：Action→World Event→Memory Candidate 全走 outbox_events（data-flow.md §2.1）。
5. **成本记账**：每周期 loop_runs 记录步骤、时长、LLM 调用、Token——「为什么主动行动/为什么不运行」可答（Goal/Decision Trace 挂接）。

## 成本铁律（任务书 §二十二逐条回答）

| 问题 | 答案 |
|---|---|
| 什么时候运行 | due trigger / 到期 goal / outbox 事件 / 低频健康检查 |
| 为什么运行 | 每次运行有 trigger id 与原因，入 loop_runs |
| 什么时候不运行 | Idle 判定命中（无 due、无到期、状态平稳） |
| 多久运行一次 | 调度粒度 60s 检查 due（纯 SQL，无 LLM），实际周期行为由 due 驱动 |
| 什么唤醒 | 用户消息（前台通知）、World Event、Goal 到期、反思产出（P2） |
| 何时 Idle | 连续无 due trigger 且无到期 goal → 空转模式，仅保留时钟检查 |

## 文档

- [tasks.md](tasks.md)（LIFE-001 ~ LIFE-006）

## 完成标准

1. kill 进程重启后 pending trigger 不丢、不重复执行。
2. 连续 7 天空跑（无用户消息）LLM 总调用 ≤ 日预算；Idle 期间 0 LLM。
3. 每个周期有完整 trace；动作链幂等（outbox 重放不双发）。
4. Flag 关闭时回到 v1 autonomy tick 行为。
