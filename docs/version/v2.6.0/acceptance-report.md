# V2.6.0 Acceptance Report

> 验收日期：2026-09-16
> 验收范围：功能 / 系统流 / 数据 / 错误 / 回归
> 配套自动化：`apps/backend/tests/v26/test_acceptance.py` + 全量 `tests/v26`
> 前置：Code Review 修复 commit `f18dbc0`（主路径接线 + 状态机权威）

---

## Status

**PASS**（有条件通过：可进入下一版本开发；下列遗留项不阻断 V2.6.0 内部验收）

---

## Completed Features

| # | Feature | 验收结论 |
|---|---|---|
| 1 | Action 统一抽象（六问可答） | PASS |
| 2 | Action 创建（`manager.create`） | PASS |
| 3 | Action 执行（`manager.execute` → `action_engine` → `ActionExecutor`） | PASS |
| 4 | 状态机（六态 + `transition_action` 唯一权威） | PASS |
| 5 | 调度（immediate/delay/cron + 优先级 + 到期队列） | PASS |
| 6 | 统一结果契约 `ActionResult` + 旧读键双写 | PASS |
| 7 | Planning → Action 1:1（`source=plan`） | PASS |
| 8 | Feedback 投影（Flag on 写入 `feedback_payload`） | PASS |
| 9 | 调试端点（4 个，Flag 门控） | PASS |
| 10 | Migration 0047（`action_schedules` + `priority`） | PASS（内存 SQLite 验证） |

---

## Test Result

| 套件 | 结果 |
|---|---|
| `tests/v26/`（含 acceptance 23 项） | **184 passed** |
| `tests/v25/` | **1415 passed, 1 skipped** |
| `tests/v24/test_tool003_action_engine.py` | **25 passed** |
| `tests/v9/` | **73 passed** |
| `tests/v8` + `v8.5` + `v23` | **297 passed, 2 skipped, 1 failed（见 Issues）** |
| `tests/v22/` | **121 passed** |
| `tests/v21/` | **120 passed, 1 failed（见 Issues）** |
| action 相关 unit/integration | **35+331 passed** |

### 功能验收明细

| 项 | 判据 | 证据 |
|---|---|---|
| 创建 | `status=created`，`dedupe_key` 生成 | `test_create` |
| 执行 | 复用原记录，不双记 | `test_execute_reuses_record` |
| 状态 | created→planned→executing→succeeded/failed/cancelled | `test_status_changes` |
| Result | 字段契约 + 往返 | `test_result_generated` / `test_result_json_roundtrip` |
| Feedback | Flag on 产出 v26 投影 | `test_feedback_produced` |
| 完整流 | Plan→Action→Execute→Outcome 1:1 | `test_plan_action_execute_outcome` |
| 调度 | 到期队列 + next_action | `test_schedule_then_due` |
| 数据 | priority/scheduled_at/planned 落库 | `test_priority_and_schedule_persist` |
| 错误 | 异常/超时归一、retry 上限、缺记录 | `TestErrorAcceptance` |
| 回归 | Flag off 默认、legacy feedback、debug 404 | `TestRegressionCheck` |

---

## Issues

### 不阻断验收

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| I1 | `tests/v23/test_ws004_day_cycle.py::test_maintenance_step_emits_markers` 失败 | 世界日循环 marker，**非 V2.6 改动引入**（`world_engine` 未改） | 单独立项排查 V2.3.0 时间推进 |
| I2 | `tests/v21/test_agent008_review_fixes.py::TestLowEnergySuppression` 失败 | Goal Stack 低能量抑制，**非 Action 执行层** | 回归 V2.1 自治抑制逻辑 |
| I3 | `due_actions` N+1 查询 | 队列大时性能 | 后续批量读 |
| I4 | 结果归一逻辑 `executor`/`result` 双份 | 维护成本 | 可收敛到 `result.py` |
| I5 | 真实 PostgreSQL 上 0047 未实测 | 迁移风险 | 上线前跑 `TEST_DATABASE_URL` 迁移 |
| I6 | 真实模型人工回归未执行 | Flag on 全链路 | 按 `regression-checklist.md` 人工执行 |
| I7 | External 执行仅占位 | 设计内（V2.7.0） | 预留 OK |

### 已关闭（Code Review）

- R1 ActionExecutor 主路径接线
- R2 Manager.execute + Planning 1:1
- R3 Feedback 挂载
- R4 Flag off 步骤序列
- R5 transition_action 状态权威
- G4 闸门自记录误判 duplicate

---

## Release Decision

**可以进入下一版本开发（V2.7.0 Tool Capability）**，条件：

1. **默认 Flag 全 off** 上线安全（已验证回归）。
2. Flag on 打开前，必须完成：
   - 真实 PG 迁移验证（I5）
   - 真实模型人工回归（I6，`regression-checklist.md` §2 A–D）
3. I1 / I2 作为独立缺陷跟踪，不挂在 V2.6.0 发布门上。

### 发布门摘要

| Gate | 结果 |
|---|---|
| G-ABSTRACT | PASS |
| G-PERSIST | PASS |
| G-MANAGE | PASS |
| G-EXEC | PASS |
| G-SCHEDULE | PASS |
| G-RESULT | PASS |
| G-INTEGRATE | PASS |
| G-OBSERVE | PASS |
| Flag off 一致性 | PASS（v25 全绿） |
| 迁移唯一新表/加列 | PASS（0047） |

---

## Sign-off

- 自动化验收：PASS
- Code Review 修复：PASS
- 人工回归：待执行（不阻塞进入下一版本开发）
- 最终裁决：**ACCEPTED FOR NEXT VERSION DEVELOPMENT**
