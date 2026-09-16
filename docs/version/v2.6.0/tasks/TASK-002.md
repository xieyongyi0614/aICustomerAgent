# TASK-002 Action Persistence Layer — Task Detail

> 上游：[../architecture.md](../architecture.md) §9（§9.1 ~ §9.4）、§0 前提裁决；[../tasks.md](../tasks.md) TASK-002
> 状态：TODO
> 范围红线：**复用 `action_records` 表，不新建 `actions` / `action_results` 表**；唯一新表 `action_schedules`；唯一加列 `action_records.priority`。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-002 |
| **Task Name** | Action Persistence Layer |
| **Priority** | P0 |
| **Dependencies** | TASK-001 |
| **Phase** | Phase 1 领域地基 |
| **建议提交** | `feat: action_schedules 调度表与 priority 加列` |

## 1.1 Goal

交付 Action 数据存储三件套：**Schema**（复用 `action_records` + 新增 `action_schedules`）、**Migration**（线性链接、可逆放）、**Repository**（复用既有 11 个仓储函数 + 新增 5 个 schedule 函数）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**持久化底座**。TASK-003（Manager）的 `create`/`query`/`cancel`/`retry` 全部依赖本任务的仓储；TASK-005（Scheduler）依赖本任务的 `action_schedules` 表；TASK-006（Result）依赖本任务 `result` JSON 列的往返一致。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-001 | 消费 `Action` 字段集（`priority` 等） |
| 被依赖 | TASK-003 / TASK-005 / TASK-006 | 提供仓储与表 |
| 复用 | 既有 `action_repository.py` / `app/core/db.py` | 复用 + 扩展，不新建仓储模块 |

---

# 2. Background

## 2.1 当前系统现状

| 既有资产 | 现状 |
|---|---|
| `ActionRecordRow`（`app/core/db.py`） | 已含 `id` / `user_id` / `character_id` / `session_id` / `source` / `action_type` / `intent` / `goal_id` / `target_record_id` / `dedupe_key` / `params` / `status` / `gate_reason` / `steps` / `result` / `attempt` / `next_retry_at` / `scheduled_at` / `created_at` / `updated_at` / `executed_at` |
| `action_repository.py` | 已含 11 个函数：`new_record_id` / `save_record` / `get_record` / `list_records` / `list_by_status` / `list_retryable` / `list_planned` / `list_by_dedupe` / `count_active` / `recent_records` / `retain_cleanup` / `save_record_with_outbox` |
| 迁移链头 | V2.5.0 为 0046（实现期以实际链头为准） |

**关键事实**：`ActionRecord` 模型**缺 `priority` 字段**（`scheduled_at` 已有）；`result` / `steps` 已是 JSON 列，可承接结果与执行步骤。

## 2.2 为什么需要本任务

architecture §2.1 与 §9.3 的核心裁决：**调度语义（延迟/定时/优先级/队列）无法用 `action_records` 单表承载**——`action_records` 是执行台账，不是调度队列。因此需要唯一一张新表 `action_schedules`。同时，`ActionRecord` 缺 `priority` 字段，调度排序无法落地。

一句话：**执行台账有了（action_records），调度队列还没有（action_schedules），且执行记录缺优先级字段。**

---

# 3. Scope

## 3.1 In Scope

- 复用 `action_records` 表（零结构改动，除 `priority` 加列）。
- 新增 `action_schedules` 表（唯一新表）。
- `ActionRecord` 模型新增 `priority: int = 100` 字段；`ActionRecordRow` 对应加列。
- Migration：线性 down_revision 链接既有链头；建表 + 加列；可逆放。
- Repository 扩展：新增 5 个 schedule 函数；`save_record` 更新字段列表扩 `priority`。

## 3.2 Out of Scope

- 新建 `actions` / `action_results` 表（复用 `action_records`，见 §0 前提裁决）。
- `result` JSON 列的 schema 统一（属 TASK-006 Result System）。
- 调度逻辑（属 TASK-005 Scheduler）。
- Repository 业务逻辑（Manager 六能力属 TASK-003）。

---

# 4. Technical Design

## 4.1 表设计

### 4.1.1 `action_records`（复用，加一列）

| 字段 | 类型 | 变更 | 说明 |
|---|---|---|---|
| 既有 22 列 | — | ❌ 零改动 | 见 §2.1 |
| `priority` | int | ✅ **新增** | 默认 100，调度排序用 |

### 4.1.2 `action_schedules`（新增，架构 §9.3）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar PK | |
| `action_id` | varchar FK | → `action_records.id` |
| `when_type` | varchar | `immediate` / `delay` / `cron` |
| `scheduled_at` | timestamptz | 计划执行时刻（`cron` 时为下一次） |
| `priority` | int | 默认 100 |
| `status` | varchar | `scheduled` / `due` / `executed` / `cancelled` |
| `created_at` / `updated_at` | timestamptz | |

## 4.2 索引设计

| 表 | 索引/约束 | 说明 |
|---|---|---|
| `action_schedules` | `uq_action_schedules_action (action_id)` | 一 Action 一调度（唯一） |
| `action_schedules` | `idx_action_schedules_due (status, scheduled_at, priority)` | 到期扫描 |

## 4.3 Migration

- 线性 down_revision 链接既有链头（实现期确认，V2.5.0 为 0046）。
- 建 `action_schedules` 表 + `action_records` 加 `priority` 列。
- SQLite 不支持的约束变更沿用 `batch_alter_table` 模式（既有惯例）。
- 逆放可执行（`alembic downgrade` 后 `action_schedules` 消失、`priority` 移除）。

## 4.4 Repository 扩展

| 函数 | 形态 | 说明 |
|---|---|---|
| 既有 11 个函数 | 复用 | **零改动**（差异对照为空） |
| `save_schedule(schedule)` | 新增 | 落 `action_schedules` |
| `get_schedule(action_id)` | 新增 | 读单条 |
| `list_due_schedules(now, limit)` | 新增 | 到期集（`status=scheduled` 且 `scheduled_at <= now`） |
| `mark_schedule_executed(action_id)` | 新增 | `status → executed` |
| `mark_schedule_cancelled(action_id)` | 新增 | `status → cancelled` |

**`save_record` 更新字段列表**：扩 `priority`（与 `scheduled_at` / `executed_at` 并列）。

## 4.5 状态变化

`action_schedules.status` 四态：`scheduled → due → executed` / `scheduled → cancelled`。迁移由 TASK-005（Scheduler）驱动，本任务只提供仓储写面。

## 4.6 异常处理

| 场景 | 处理 |
|---|---|
| 重复 `action_id` 落 `action_schedules` | `uq_action_schedules_action` 唯一约束拒绝（`IntegrityError`） |
| `save_record_with_outbox` 幂等重放 | 既有 `IntegrityError` 吞掉逻辑不变 |

---

# 5. Implementation Plan

## Step 1 — 确认迁移链头

1. 读 `apps/backend/migrations/versions/` 确认当前链头（V2.5.0 为 0046）。
2. 定新迁移编号（链头 + 1）。

## Step 2 — 扩展 ActionRecord 模型

1. `models/action.py::ActionRecord` 新增 `priority: int = 100`。
2. `action_repository.py::_to_record` / `save_record` / `save_record_with_outbox` 补 `priority` 映射与更新。

## Step 3 — 建 ActionRecordRow 加列 + action_schedules 表

1. `app/core/db.py` 新增 `ActionScheduleRow` 映射；`ActionRecordRow` 加 `priority` 列。
2. 写 migration 脚本（建表 + 加列 + 唯一约束 + 索引；SQLite batch mode）。

## Step 4 — 新增 5 个 schedule 仓储函数

1. `save_schedule` / `get_schedule` / `list_due_schedules` / `mark_schedule_executed` / `mark_schedule_cancelled`。

## Step 5 — 测试

1. 复用断言（既有 11 函数零改动）、新表断言、迁移断言、仓储往返断言、加列落库断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- `action_records` 表结构与既有列语义未动（除 `priority` 加列）；`ActionRecordRow` 差异对照仅 `priority` 一列。
- `action_schedules` 表结构与 §4.1.2 逐条一致；`uq_action_schedules_action` 唯一约束生效；`idx_action_schedules_due` 存在。

## 6.2 数据正确性

- `priority` 字段经 `save_record` 持久化后读回一致（默认 100）。
- `result` JSON 列写入 `ActionResult` 值对象后读回字段无丢失。

## 6.3 异常场景

- 重复 `action_id` 落 `action_schedules` 被唯一约束拒绝。
- `save_record_with_outbox` 幂等重放不报错。

## 6.4 迁移正确性

- 迁移链头 = 既有链头 + 1；down_revision 线性；逆放可执行；SQLite 兼容（batch mode）。

## 6.5 与已有系统兼容性

- 既有 11 个仓储函数零改动；Flag 全 off 时既有 `action_repository` 测试零修改通过。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | `save_schedule` → `get_schedule` | 往返一致 |
| U2 | `list_due_schedules(now)` | 只返回到期且 `scheduled` |
| U3 | `mark_schedule_executed` / `mark_schedule_cancelled` | 状态迁移正确 |
| U4 | `priority` 默认值 | 未显式设置时 100 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | 迁移 up/down | `action_schedules` 建/删；`priority` 加/删 |
| I2 | 唯一约束 | 重复 `action_id` 拒绝 |
| I3 | `result` JSON 往返 | `ActionResult` 落库读回无丢失 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 「明天提醒我学习」Action 落库 + 调度落库 | `action_records` 有记录，`action_schedules` 有调度 |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-001（`Action` 字段集，含 `priority` 定义）。

## 8.2 后续依赖模块

- TASK-003（Manager 依赖仓储）、TASK-005（Scheduler 依赖 `action_schedules`）、TASK-006（Result 依赖 `result` JSON 列）。

## 8.3 需要修改的已有代码

- `app/models/action.py`（`ActionRecord` 加 `priority`）。
- `app/core/db.py`（`ActionRecordRow` 加列 + 新增 `ActionScheduleRow`）。
- `app/repositories/action_repository.py`（补 `priority` 映射 + 新增 5 个 schedule 函数）。
- `apps/backend/migrations/versions/`（新增迁移脚本）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 新表 `action_schedules` 打破「零迁移」惯例 | 架构风险 | 唯一新表 + 明确裁决（architecture §9.3、R6）；其余全部复用 |
| R2 | `priority` 加列影响既有 `save_record` 的 SQLite 兼容 | 技术风险 | batch mode + 逆放验证 |
| R3 | `action_schedules` 与 `trigger_registry` 双源不一致 | 数据风险 | `uq_action_schedules_action` 唯一约束 + 幂等重建（architecture R3） |
| R4 | `result` JSON 列 schema 漂移 | 数据风险 | TASK-006 统一契约；本任务只保证往返一致 |
