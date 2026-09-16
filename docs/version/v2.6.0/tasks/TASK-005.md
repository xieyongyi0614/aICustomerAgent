# TASK-005 Action Scheduler — Task Detail

> 上游：[../architecture.md](../architecture.md) §8.3、§7.2、§9.3、§9.7 Q2；[../tasks.md](../tasks.md) TASK-005
> 状态：TODO
> 范围红线：**调度能力**——延迟/定时/优先级/队列统一到 Action 级；复用既有 `trigger_registry` / `background_jobs` / `outbox` 三设施；不新建调度循环 / Worker；不实现 cron 解析器。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-005 |
| **Task Name** | Action Scheduler |
| **Priority** | P1 |
| **Dependencies** | TASK-002 |
| **Phase** | Phase 3 增强能力 |
| **建议提交** | `feat: Action Scheduler 延迟/定时/优先级/队列` |

## 1.1 Goal

支持未来主动行为：延迟执行 / 定时执行 / 优先级排序 / 队列管理，统一到 Action 级调度语义（architecture §8.3），复用既有三设施。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**调度层**。它是「飞书机器人主动行为」与「明天早上提醒我学习」这类需求的基础——没有统一的 Action 级调度，主动行为无法落地。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-002（`action_schedules` 表 + 仓储） | 消费 |
| 被依赖 | TASK-007（Integration 的调度消费） | 提供调度能力 |
| 复用 | 既有 `trigger_registry` / `background_jobs` / `outbox` / `life_loop` | 复用，不新建 |

---

# 2. Background

## 2.1 当前系统现状

| 既有设施 | 现状 |
|---|---|
| `trigger_registry`（action_due） | 到期触发（散落） |
| `background_jobs` | 后台任务台账（散落） |
| `outbox_events` | 事务投递（一致性） |
| `life_loop` 维护步骤 | 唯一调度器（`world_simulation` 等步骤） |

**关键事实**：延迟/定时/优先级/队列四类调度语义散落在三处，**无 Action 级统一调度**（architecture §2.1 B4 断层）。「明天早上提醒我学习」这类需求无法以 Action 为单元编排。

## 2.2 为什么需要本任务

architecture §8.3 的核心诉求：把三处散落的调度设施统一到 **Action 级调度语义**下，让「一个 Action 何时执行」有唯一权威（`ActionScheduler`）。同时守住纪律：不新建调度循环（挂既有 `life_loop` 维护步）。

一句话：**调度设施有了（三处散落），统一调度器还没有（ActionScheduler）。**

---

# 3. Scope

## 3.1 In Scope

- 新建 `app/services/action/scheduler.py`：`ActionScheduler` 纯函数 + 轻量编排。
- `schedule(action, *, when, priority) -> ActionSchedule`：三种 `when`（immediate/delay/cron）。
- `sort_queue` / `due_actions` / `next_action` 纯函数。
- 挂载 `life_loop` 维护步骤 `action_schedule`（新增一步，不改既有步骤顺序）。

## 3.2 Out of Scope

- cron 表达式解析器（`cron` 简化为「下一次触发时刻」，复杂 cron 留给 V2.7.0 日历工具）。
- 新建调度循环 / Worker（`main.py` lifespan 零新增）。
- 执行动作（属 TASK-004）。
- 具体外部能力（属 V2.7.0）。

---

# 4. Technical Design

## 4.1 模块设计

```text
app/services/action/scheduler.py（新增）
├── schedule(action, *, when, priority) -> ActionSchedule
├── sort_queue(actions) -> list[Action]          # 纯函数
├── due_actions(now) -> list[Action]             # 纯函数
└── next_action() -> Action | None               # 队列头
        │
        ▼
app/repositories/action_repository.py（TASK-002 扩展的 5 个 schedule 函数）
app/application/life_loop.py（既有，新增 action_schedule 维护步）
app/services/action/registry.py（trigger_registry，既有）
```

## 4.2 `schedule` 三种 `when`

| `when` | `when_type` | `scheduled_at` | 说明 |
|---|---|---|---|
| `None` | `immediate` | now | 立即执行，跳过调度 |
| `delay` | `delay` | now + delta | 延迟执行 |
| `cron` | `cron` | 下一次触发时刻 | 定时执行（简化语义） |

## 4.3 排序纯函数（确定性）

```text
sort_queue(actions)：
  ① priority 降序
  ② scheduled_at 升序
  ③ id 字典序（tiebreak）
```

## 4.4 队列管理

| 函数 | 逻辑 |
|---|---|
| `due_actions(now)` | `scheduled_at <= now` 且 `status ∈ {scheduled, due}` |
| `next_action()` | 队列头（最高优先级最早到期） |

## 4.5 调度语义统一（architecture §8.3，B4 关闭点）

| 需求 | 既有设施 | 本版本统一 |
|---|---|---|
| 延迟执行 | `trigger_registry`（action_due） | `schedule(when=delay)` |
| 定时执行 | `background_jobs` / `outbox` | `schedule(when=cron)` |
| 优先级排序 | 散落 | `sort_queue`（纯函数） |
| 队列管理 | 散落 | `due_actions` / `next_action` |

## 4.6 挂载（life_loop）

- 新增 `life_loop._step_action_schedule` 维护步（与 `world_simulation` 并列，不改既有步骤序列顺序，只新增一步）。
- 到期 Action 经 `trigger_registry`（`action_due`）→ `action_engine.run_action_planning`。

## 4.7 示例链路（architecture §8.3）

```text
用户："明天早上提醒我学习"
  ↓ Plan（V2.5.0）
Action{type: create_reminder, target: user, params: {content:"学习", due_at: 明早 8:00}}
  ↓ Schedule（本任务）
schedule(action, when=明早 8:00, priority=100)
  ↓ 到期（life_loop action_schedule 步）
ActionManager.execute → ActionResult{status: succeeded}
  ↓ 反馈
世界事件（提醒到期）+ 记忆候选 + 决策面更新
```

## 4.8 状态变化

`action_schedules.status`：`scheduled → due → executed` / `scheduled → cancelled`。

## 4.9 异常处理

| 场景 | 处理 |
|---|---|
| `cron` 复杂表达式 | 拒绝（本版本仅「下一次触发时刻」） |
| 调度丢失 | `uq_action_schedules_action` 幂等重建 |
| 重复执行 | `dedupe_key` 去重 |

---

# 5. Implementation Plan

## Step 1 — 建 scheduler 模块骨架

1. 新建 `app/services/action/scheduler.py`，声明四函数签名。

## Step 2 — 实现 schedule

1. `schedule`：按 `when` 计算 `scheduled_at`，落 `action_schedules`（`save_schedule`）。

## Step 3 — 实现排序与队列纯函数

1. `sort_queue` / `due_actions` / `next_action`（确定性排序）。

## Step 4 — 挂载 life_loop 维护步

1. 新增 `_step_action_schedule`：扫 `due_actions` → 经 `trigger_registry`（action_due）投递。

## Step 5 — 断言用例

1. 调度断言、排序断言、队列断言、挂载断言、示例链路断言、复用断言、cron 简化断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- `schedule` 三种 `when` 各有用例；`scheduled_at` 计算正确。
- `sort_queue` 确定性（同输入同输出）；优先级降序 + 时刻升序 + id 字典序。

## 6.2 数据正确性

- `due_actions(now)` 只返回到期且未执行 Action；`next_action` 返回队列头；`uq_action_schedules_action` 保证一 Action 一调度。

## 6.3 异常场景

- 复杂 cron 表达式被拒（本版本简化语义）。

## 6.4 挂载正确性

- `life_loop` 维护步骤序列新增 `action_schedule` 一步，既有步骤顺序不变（形状快照对照）；到期 Action 经 `trigger_registry` 投递。

## 6.5 与已有系统兼容性

- 不新建调度循环 / Worker（`main.py` lifespan 零新增）；复用既有三设施。
- Flag 全 off 时 `action_schedules` 不参与调度，行为与 V2.5.0 逐字节一致。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | `schedule` immediate/delay/cron | `scheduled_at` 正确 |
| U2 | `sort_queue` | 确定性排序 |
| U3 | `due_actions` | 只返回到期 |
| U4 | `next_action` | 返回队列头 |
| U5 | cron 简化 | 复杂表达式被拒 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | 维护步挂载 | 步骤序列 + 形状快照 |
| I2 | 到期投递 | `trigger_registry`（action_due） |
| I3 | 复用三设施 | 不新建调度循环 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 「明天早上提醒我学习」端到端 | Plan → Action → Schedule → 到期执行 → 反馈 |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-002（`action_schedules` 表 + `save_schedule` 等仓储函数）。

## 8.2 后续依赖模块

- TASK-007（Integration 的调度消费）、TASK-009（Testing 的调度链路）。

## 8.3 需要修改的已有代码

- 新增 `app/services/action/scheduler.py`。
- `app/application/life_loop.py`（新增 `_step_action_schedule` 维护步）。
- 既有 `trigger_registry` / `background_jobs` / `outbox` 零改动（只复用）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 调度与执行双源不一致 | 数据风险 | `uq_action_schedules_action` + 幂等重建（architecture R3） |
| R2 | 维护步拖慢 life_loop | 技术风险 | 到期扫描有界（limit）+ 节流 |
| R3 | cron 语义范围膨胀 | 架构风险 | 简化到「下一次触发时刻」，复杂留给 V2.7.0 |
| R4 | 排序不确定性 | 技术风险 | id 字典序 tiebreak 兜底 |
