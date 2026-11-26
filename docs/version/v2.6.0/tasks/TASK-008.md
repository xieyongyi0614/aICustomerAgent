# TASK-008 API / Interface Layer — Task Detail

> 上游：[../architecture.md](../architecture.md) §8（模块接口）、§12（Observability）、§9.7 Q5；[../tasks.md](../tasks.md) TASK-008
> 状态：TODO
> 范围红线：**内部接口层**——Action API / Executor API / Result API 三组接口契约冻结；可观测面（日志 + 指标 + 调试端点）；不暴露对外 REST API；不新建指标表。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-008 |
| **Task Name** | API / Interface Layer |
| **Priority** | P1 |
| **Dependencies** | TASK-003, TASK-004 |
| **Phase** | Phase 5 接口层 |
| **建议提交** | `feat: Action 内部接口契约与可观测面` |

## 1.1 Goal

提供内部调用接口：Action API（`ActionManager` 六能力）、Executor API（`ActionExecutor` 四能力）、Result API（`ActionResult` 契约）三组接口契约冻结 + 可观测面（日志/指标/调试端点）（architecture §12）。

## 1.2 本任务在 Action Execution System 中的作用

本任务是 Action 的**契约冻结与可观测层**。它让 Coding Agent 后续执行时有明确的接口边界，让运维有可观测的日志/指标/调试端点。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-003（Manager）、TASK-004（Executor） | 冻结其签名 |
| 被依赖 | TASK-009（Testing） | 提供验收对象 |
| 复用 | 既有 `loop_runs.steps` / `app/api/v1/debug.py` | 可观测通道 |

---

# 2. Background

## 2.1 当前系统现状

| 既有资产 | 现状 |
|---|---|
| `loop_runs.steps` | 既有可观测通道 |
| `app/api/v1/debug.py` | 既有调试端点（world 面板 / tools 面板同构） |
| `llm_call_records` / `decision_records` | 既有台账 |

**关键事实**：Action 执行**缺统一日志事件与指标**——`Action Created / Started / Completed / Failed` 等事件未统一落 `loop_runs.steps`；执行次数/成功率/平均耗时等指标无统一投影。

## 2.2 为什么需要本任务

architecture §12 的核心诉求：Action 执行需要**可观测**——七个日志事件 + 五项指标，且全部投影自既有表（不新建指标表）。同时冻结三组接口契约，供 Coding Agent 执行时对照。

一句话：**执行能力有了（TASK-003/004），接口契约与可观测面还没有（TASK-008）。**

---

# 3. Scope

## 3.1 In Scope

- 冻结三组接口契约：Action API / Executor API / Result API。
- 日志：七个事件（Created/Scheduled/Started/Completed/Failed/Cancelled/Retried）落 `loop_runs.steps`。
- 指标：五项（执行次数/成功率/平均耗时/重试率/取消率）投影自 `action_records`。
- 调试端点：Action 清单 / 详情 / 调度队列 / 指标聚合。

## 3.2 Out of Scope

- 对外 REST API（V2.6.0 是内部执行层，外部 API 留给 V2.7.0）。
- `apps/frontend/` 前端（architecture §13 Future Extension）。
- 新建指标表（投影自既有表）。

---

# 4. Technical Design

## 4.1 三组接口契约

### 4.1.1 Action API（`ActionManager` 六能力，TASK-003）

| 接口 | 输入 | 输出 |
|---|---|---|
| `create` | `intent \| plan_step` + `source` | `Action` |
| `update` | `action_id` + 受控字段 | `Action` |
| `query` | `action_id \| filters` | `Action \| list[Action]` |
| `cancel` | `action_id` + `reason` | `bool` |
| `retry` | `action_id` | `ActionResult \| None` |
| `get_status` | `action_id` | `ActionStatus` |

### 4.1.2 Executor API（`ActionExecutor` 四能力，TASK-004）

| 接口 | 输入 | 输出 |
|---|---|---|
| `dispatch` | `action` | `ExecutionKind` |
| `run` | `action` + `ctx` | `ActionResult` |
| `execute_internal` | `action` + `ctx` | `ActionResult` |
| `execute_tool` | `action` + `ctx` | `ActionResult` |
| `execute_external` | `action` + `ctx` | `ActionResult` |

### 4.1.3 Result API（`ActionResult` 契约，TASK-006）

| 字段 | 类型 |
|---|---|
| `id` / `action_id` | str |
| `status` | succeeded/failed/partial/timeout |
| `output` / `metadata` / `observations` | dict |
| `effects` | list[ActionEffect] |
| `error` | str \| None |
| `created_at` | datetime |

## 4.2 日志事件（architecture §12.1）

| 事件 | 字段 |
|---|---|
| Action Created | action_id, type, source, priority |
| Action Scheduled | action_id, scheduled_at, when_type |
| Action Started | action_id, execution_kind, started_at |
| Action Completed | action_id, status, duration_ms |
| Action Failed | action_id, failure_kind, error, attempt |
| Action Cancelled | action_id, reason |
| Action Retried | action_id, attempt, next_retry_at |

全部落 `loop_runs.steps`（不新建）。

## 4.3 指标（architecture §12.2）

| 指标 | 计算 | 分组 |
|---|---|---|
| 执行次数 | count(action_records) | type / source |
| 成功率 | success / total | type / tool_id |
| 平均耗时 | avg(duration_ms) | execution_kind |
| 重试率 | retry / total | — |
| 取消率 | cancelled / total | — |

投影自 `action_records`（不新建指标表）。

## 4.4 调试端点

| 端点 | 内容 | 门控 |
|---|---|---|
| Action 清单 | `action_records` 列表 | 总闸 + 调试子闸 |
| Action 详情 | steps + result + schedule | 同上 |
| 调度队列 | `action_schedules` 视图 | 同上 |
| 指标聚合 | 五项指标 | 同上 |

## 4.5 异常处理

| 场景 | 处理 |
|---|---|
| 未知 action_id | 404 / 空 |
| Flag off | 端点不可见 |
| 指标聚合无数据 | 空结果，不报错 |

---

# 5. Implementation Plan

## Step 1 — 冻结接口契约

1. 写三组接口契约对照（§4.1），作为 Coding Agent 的接口边界。

## Step 2 — 日志事件

1. 七个日志事件落 `loop_runs.steps`（复用既有可观测通道）。

## Step 3 — 指标投影

1. 五项指标投影自 `action_records`（聚合查询）。

## Step 4 — 调试端点

1. 扩 `app/api/v1/debug.py`：Action 清单 / 详情 / 调度队列 / 指标聚合，受总闸 + 调试子闸门控。

## Step 5 — 断言用例

1. 契约冻结断言、日志断言、指标断言、调试端点断言、零新建表断言、不暴露外部 API 断言（见 §6）。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- 三组接口签名与 §4.1 逐条一致（契约对照）。
- 七个日志事件落 `loop_runs.steps`。
- 五项指标可从 `action_records` 正确投影。

## 6.2 数据正确性

- 可观测面全部投影自 `action_records` / `action_schedules` / `loop_runs` 三张表（不新建指标表）。

## 6.3 异常场景

- Flag off 时调试端点不可见；指标聚合无数据返回空。

## 6.4 与已有系统兼容性

- 无对外 REST 端点（内部执行层定位）。

---

# 7. Testing Requirements

## 7.1 Unit Test

| # | 用例 | 断言 |
|---|---|---|
| U1 | 契约对照 | 三组接口签名一致 |
| U2 | 日志事件 | 七事件落 loop_runs |
| U3 | 指标投影 | 五项指标聚合正确 |

## 7.2 Integration Test

| # | 用例 | 断言 |
|---|---|---|
| I1 | 调试端点门控 | Flag off 不可见 |
| I2 | 零新建表 | 投影自三张表 |

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 执行一个 Action → 查日志 → 查指标 | 全链路可观测 |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-003（Manager）、TASK-004（Executor）、TASK-006（Result 契约，可选）。

## 8.2 后续依赖模块

- TASK-009（Testing 验收对象）。

## 8.3 需要修改的已有代码

- `app/api/v1/debug.py`（扩 Action 调试端点）。
- 既有 `loop_runs` / `action_records` 零改动（只投影）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 调试端点越权暴露 | 架构风险 | 总闸 + 调试子闸门控 |
| R2 | 指标投影性能 | 技术风险 | 有界查询 + 索引 |
| R3 | 契约冻结与实现漂移 | 技术风险 | TASK-009 验收兜底 |
| R4 | 前端范围膨胀 | 架构风险 | 明确不纳入 `apps/frontend/` |
