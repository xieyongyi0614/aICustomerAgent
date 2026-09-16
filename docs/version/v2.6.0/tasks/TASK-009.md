# TASK-009 Testing & Validation — Task Detail

> 上游：[../architecture.md](../architecture.md) §3.2、§14、附遗留问题、§12；[../tasks.md](../tasks.md) TASK-009
> 状态：TODO
> 范围红线：**验收收口**——四类测试（Unit/Integration/Lifecycle/Failure）+ Flag 矩阵一致性 + 回归清单 + 六设计原则与六风险收口；不改变 Architecture 设计。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TASK-009 |
| **Task Name** | Testing & Validation |
| **Priority** | P0 |
| **Dependencies** | TASK-001 ~ TASK-008 |
| **Phase** | Phase 5 验收 |
| **建议提交** | `test: V2.6.0 Action 执行层验收与回归清单` |

## 1.1 Goal

保证系统稳定：四类测试（Unit / Integration / Lifecycle / Failure）+ Flag 矩阵一致性 + 回归清单 + 六设计原则与六风险收口。

## 1.2 本任务在 Action Execution System 中的作用

本任务是全版本**验收收口**（tasks.md §1.1「Priority ≠ 顺序」：P0 但最后执行）。它验证 TASK-001 ~ TASK-008 的全部交付，并产出 `regression-checklist.md` 供人工回归。

## 1.3 与其他模块的依赖关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| 前置 | TASK-001 ~ TASK-008（全量扇入） | 验证其交付 |
| 产出 | `regression-checklist.md` | 人工回归清单 |

---

# 2. Background

## 2.1 当前系统现状

| 既有测试资产 | 现状 |
|---|---|
| V4/V7/V7.5/V7.8/V8/V2.1.0 regression-checklist | 已有各版本清单 |
| pytest 测试套件 | 既有 |
| pylint 静态检查（基线 8.57/10） | 既有 |

**关键事实**：V2.6.0 引入了唯一新表 `action_schedules` 与唯一加列 `priority`，且兑现了「旧读键退役」承诺——这三处变更需要专项验收，确保 Flag 全 off 时与 V2.5.0 逐字节一致。

## 2.2 为什么需要本任务

architecture §3.2（六设计原则）、§14（六风险）、附（五遗留问题）都需要**可判定的收口**。若不专项验收，「旧读键退役破坏 V9 下游」「多步状态不一致」等风险可能在 Flag on 后才暴露。

一句话：**功能交付了（TASK-001~008），验收收口还没有（TASK-009）。**

---

# 3. Scope

## 3.1 In Scope

- 四类测试：Unit / Integration / Lifecycle / Failure。
- Flag 矩阵一致性（6 个 `v26_*` Flag 组合）。
- `regression-checklist.md` 交付。
- 六设计原则 + 六风险 + 五遗留问题收口。

## 3.2 Out of Scope

- 改变 Architecture 设计（只验证）。
- 性能压测（Q3 反馈预算压测留后续）。
- 人工回归执行（只交付清单）。

---

# 4. Technical Design

## 4.1 四类测试

### 4.1.1 Unit Test

| 覆盖 | 对象 |
|---|---|
| Action 值对象 | TASK-001 |
| `action_schedules` 仓储 | TASK-002 |
| `ActionManager` 六能力 | TASK-003 |
| `ActionExecutor` 分派 | TASK-004 |
| `ActionScheduler` 纯函数 | TASK-005 |
| `ActionResult` 值对象 | TASK-006 |

### 4.1.2 Integration Test

| 覆盖 | 对象 |
|---|---|
| Planning → Action → Tool 全链 | TASK-007 |
| World / Relationship / Memory 接线 | TASK-007 |
| 调度消费链路 | TASK-005 |

### 4.1.3 Lifecycle Test

```text
CREATED → PENDING → RUNNING → SUCCESS/FAILED/CANCELLED 全生命周期
FAILED → PENDING（retry）
终态出度 0
```

### 4.1.4 Failure Scenario

| 场景 | 期望 |
|---|---|
| 执行失败 | `ActionResult{failed, failure_kind}` |
| 超时 | `failure_kind=timeout` |
| 重试达上限 | `retry` 返回 `None` |
| 幂等重复 | 无重复副作用 |
| 状态恢复 | 进程崩溃后孤儿 RUNNING 恢复 |
| 部分完成 | `partial` 记录不回滚 |

## 4.2 Flag 矩阵（6 个 Flag）

| Flag | 控制面 |
|---|---|
| `v26_action_execution_enabled` | 总闸 |
| `v26_action_abstraction_enabled` | Action 值对象 |
| `v26_action_scheduler_enabled` | Scheduler |
| `v26_action_multistep_enabled` | 多步执行 |
| `v26_action_result_enabled` | ActionResult 契约 + 旧读键退役 |
| `v26_action_feedback_enabled` | 反馈闭环 |

总闸 off 时逐字节一致（prompt + 行为快照 + 维护步骤序列）。

## 4.3 六设计原则收口（architecture §3.2）

| 原则 | 可判定条目 |
|---|---|
| Action 独立抽象 | Action 六问可答，零 Goal/Plan/Tool 语义依赖 |
| Planning 不执行 | `planning/` 包零 `execute`（除 `executor_bridge` 翻译） |
| Executor 不决策 | 零 `decision_pipeline` 调用 |
| Tool 是扩展能力 | 新增能力 = 声明 Adapter，不改抽象 |
| 所有执行必产 Result | 无 `None` 返回 |
| Result 支持反馈 | 四通道回写 + 三面反馈 |

## 4.4 六风险收口（architecture §14）

| 风险 | 收口 |
|---|---|
| R1 多步状态一致性 | 部分失败不回滚（记录留痕） |
| R2 旧读键退役兼容 | 双写窗口验证 |
| R3 调度执行一致性 | 唯一约束 + 幂等 |
| R4 Action 过度设计 | 字段最小化 |
| R5 反馈预算竞争 | 有界 |
| R6 新表打破零迁移 | 唯一新表 + 唯一加列 |

## 4.5 五遗留问题收口（architecture 附）

| 遗留 | 收口 |
|---|---|
| Q1 部分失败回滚 | 本版本只记录不回滚 |
| Q2 cron 语义 | 简化，留 V2.7.0 |
| Q3 反馈预算 | 压测后决定 |
| Q4 外部服务超时 | 留 V2.7.0 |
| Q5 Action 与 MCP 对齐 | 预留映射 |

---

# 5. Implementation Plan

## Step 1 — Unit Test 补齐

1. 按 §4.1.1 六对象补齐单元测试。

## Step 2 — Integration Test 补齐

1. 按 §4.1.2 三链路补齐集成测试。

## Step 3 — Lifecycle + Failure Test

1. 按 §4.1.3 / §4.1.4 补齐生命周期与失败场景测试。

## Step 4 — Flag 矩阵一致性

1. 6 个 Flag 组合矩阵 + 总闸 off 逐字节一致快照。

## Step 5 — 回归清单交付

1. 写 `docs/version/v2.6.0/regression-checklist.md`。

## Step 6 — 收口核对

1. 六原则 + 六风险 + 五遗留逐条核对留痕。

---

# 6. Acceptance Criteria

## 6.1 功能验证

- 四类测试全覆盖；Lifecycle 测试覆盖六态全迁移 + retry + 终态出度 0。

## 6.2 数据正确性

- 唯一新表 `action_schedules`；唯一加列 `priority`；无其他表/列/索引/CHECK 变更（迁移链 = 既有链头 + 1）。

## 6.3 异常场景

- Flag 总闸 off 时与 V2.5.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）；既有测试零修改通过。

## 6.4 收口完整性

- 六原则 / 六风险 / 五遗留各有裁决结论或记录留痕，无悬空项。

## 6.5 与已有系统兼容性

- `regression-checklist.md` 覆盖六原则 + 六风险 + Flag 矩阵 + 「零新建 Agent / Memory / Session / Event 系统」复用声明。

---

# 7. Testing Requirements

## 7.1 Unit Test

见 §4.1.1 六对象。

## 7.2 Integration Test

见 §4.1.2 三链路。

## 7.3 Scenario Test

| # | 场景 | 期望 |
|---|---|---|
| S1 | 「明天提醒我学习」全链 | Plan → Action → Schedule → 到期执行 → 反馈，全链路无非法迁移 |
| S2 | 执行失败 → 重试 → 成功 | 结果链完整 |
| S3 | 进程崩溃恢复 | 孤儿 RUNNING 超时置 FAILED 可重试 |

---

# 8. Dependencies

## 8.1 前置完成模块

- TASK-001 ~ TASK-008（全量扇入）。

## 8.2 后续依赖模块

- 无（全版本收口）。

## 8.3 需要修改的已有代码

- 测试套件（新增/补齐）。
- `docs/version/v2.6.0/regression-checklist.md`（新增）。

---

# 9. Risks

| # | 风险 | 类别 | 缓解 |
|---|---|---|---|
| R1 | 测试覆盖不完整 | 技术风险 | 四类测试 + 收口核对 |
| R2 | Flag 矩阵组合爆炸 | 技术风险 | 总闸 + 五子闸串行链校验（子闸开启要求总闸） |
| R3 | 回归清单与架构脱节 | 架构风险 | 六原则 + 六风险 + 五遗留逐条对应 |
| R4 | 验收流于形式 | 技术风险 | 可判定断言句（非「口头约定」） |
