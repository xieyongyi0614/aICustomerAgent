# V2.6.0 Action Execution System 人工回归清单

> 上游：[architecture.md](./architecture.md) §3.2（六设计原则）、§14（六风险）、附（五遗留问题）、§12（可观测）；[tasks.md](./tasks.md)
> 用途：版本发布判据 + 真实模型人工回归执行单
> 配套自动化：`apps/backend/tests/v26/`（实现期建立）
> 状态：自动化验收完成（`test_acceptance.py` 23 项全绿；见 `acceptance-report.md`）；真实模型人工回归待执行

---

## 1. 适用范围与前置

| 项 | 说明 |
|---|---|
| 版本 | V2.6.0 Action Execution System（TASK-001 ~ TASK-009） |
| 迁移链头 | 实现期确认（V2.5.0 为 0046；本版本 + 1 = 0047，含 `action_schedules` 表 + `action_records.priority` 列） |
| Flag 默认态 | 6 个 `v26_*` 全 off（总闸 `v26_action_execution_enabled` + 五子闸） |
| 回滚路径 | 全部 `v26_*` 置 off 即回到 V2.5.0 行为（逐字节一致） |
| 自动化入口 | `uv run pytest tests/v26 -q`（Focused）→ `tests/v25` 工具侧回归 |

---

## 2. 四类端到端场景清单

| 类 | 名称 | 判据 | 自动化（真实文件） |
|---|---|---|---|
| **A** | 单 Action 执行 | `ActionIntent → Action → execute → ActionResult`；六态生命周期完整；执行方式分派正确 | `test_acceptance.py` + `test_task004_executor.py` + `test_v26_step_result_contract.py` |
| **B** | 调度执行 | 「明天早上提醒我学习」→ Plan → Action → Schedule → 到期执行 → 反馈；`action_schedules` 队列 SoT | `test_v26_schedule_execution.py` + `test_v26_outbox_world_write.py` |
| **C** | 失败重试 | 执行失败 → `retry` → 成功；`attempt` 对齐；`dedupe_key` 幂等 | `test_task003_manager.py` + `test_v26_recovery.py` |
| **D** | 状态恢复 | 进程崩溃后孤儿 `executing` 超时置 `failed` 可重试；调度丢失幂等重建 | `test_v26_recovery.py` |

### 人工补充（真实模型）

- **A**：对真实用户触发一次「查询环境」（tool）与一次「发通知」（external 占位），在 debug 面板核对 `ActionResult` 契约。
- **B**：说「明天早上提醒我学习」，观察是否落 `action_schedules` 并在到期时刻经 `trigger_registry`（action_due）投递执行。
- **C**：人为制造工具失败，观察 `retry` 是否复用原 `dedupe_key`、`attempt` 是否 +1、达上限是否返回 `None`。
- **D**：人为中断执行进程，观察维护步是否把孤儿 `RUNNING` 超时置 `FAILED`。

---

## 3. Flag 矩阵清单

| # | Flag | 默认 | 依赖 |
|---|---|---|---|
| 1 | `v26_action_execution_enabled` | off | 总闸 |
| 2 | `v26_action_abstraction_enabled` | off | 总闸 |
| 3 | `v26_action_scheduler_enabled` | off | 总闸 |
| 4 | `v26_action_multistep_enabled` | off | 总闸 |
| 5 | `v26_action_result_enabled` | off | 总闸 |
| 6 | `v26_action_feedback_enabled` | off | 总闸 |

### 串行链（architecture §10.8）

| # | 链 | 违规表现 |
|---|---|---|
| ① | 任一 v26 子闸 ⇒ 总闸 | 启动 fail-fast，中文理由 |
| ② | 总闸 ⇒ `action_enabled`（V9 既有） | 同上 |
| ③ | scheduler ⇒ 总闸 | 同上 |
| ④ | result（旧读键退役）⇒ 总闸 AND 全量测试通过 | 同上 |
| ⑤ | feedback ⇒ 总闸 | 同上 |

### 总闸 off 三重对照

1. prompt 与 V2.5.0 逐字节一致（`FROZEN_PROMPT_DIGEST`）
2. `action_engine.run_action_planning` 原路径生效（单步、自由 payload、旧读键生效）
3. `life_loop` 维护步骤序列零差异（`action_schedule` 步不注册）

---

## 4. Gate 判定清单（architecture §3.2 六原则 + §14 六风险）

| Gate | 判定 | 证据归属 |
|---|---|---|
| **G-ABSTRACT** | Action 六问可答；零 Goal/Plan/Tool 语义依赖；值集零变化 | `test_task001_action_core_model.py` |
| **G-PERSIST** | 复用 `action_records`（不新建 actions/action_results）；唯一新表 `action_schedules`；唯一加列 `priority` | `test_task002_persistence.py` |
| **G-MANAGE** | 六能力可判定；唯一生命周期入口；不决策（G3）不编排（G2） | `test_task003_manager.py` |
| **G-EXEC** | 九 ActionType 分派正确；三执行方式；Executor 不决策；不绕过五段短路 | `test_task004_executor.py` |
| **G-SCHEDULE** | 延迟/定时/优先级/队列；复用三设施；不新建调度循环 | `test_task005_scheduler.py` + `test_v26_schedule_execution.py` |
| **G-RESULT** | ActionResult 统一契约；旧读键退役（双写窗口）；四类结果 | `test_task006_result.py` + `test_v26_step_result_contract.py` |
| **G-INTEGRATE** | Planning/World/Relationship/Memory 四路接线；反馈闭环；职责不重叠 | `test_task007_integration.py` + `test_v26_feedback_consumers.py` |
| **G-OBSERVE** | 七日志事件 + 五指标；零新建指标表 | `test_task008_api.py` |
| **G-COMPAT** | Flag 全 off：prompt 逐字节一致；既有测试零修改；原路径生效 | `test_acceptance.py` + `test_task009_validation.py` |

---

## 5. 遗留问题收口清单（architecture 附五项）

| # | 问题 | 收口结论 |
|---|---|---|
| Q1 | 单 Action 多步部分失败回滚 | **只记录不回滚**；`partial` 结果；回滚语义留后续 |
| Q2 | `action_schedules` 的 cron 语义 | **简化到「下一次触发时刻」**；复杂 cron 留 V2.7.0 日历工具 |
| Q3 | 反馈 `action_facts` 预算上限 | **有界**（复用 `_collect_action_facts` 缓存）；压测后决定是否动态预算 |
| Q4 | External Service 超时与重试 | **预留接口不实现**；与 V2.7.0 飞书主动行为一并裁决 |
| Q5 | Action 抽象与 MCP / Function Calling 对齐 | **预留映射**（`type → ExecutionKind`）；V2.7.0 对接 |

---

## 6. 六设计原则逐条可判定（architecture §3.2）

| # | 原则 | 可判定条目 | 违规表现 |
|---|---|---|---|
| 1 | Action 独立抽象 | Action 六问可答，零 Goal/Plan/Tool 依赖 | Action 引用 Goal/Plan 语义 |
| 2 | Planning 不执行 | `planning/` 包零 `execute`（除 `executor_bridge` 翻译） | Planning 直调 ToolExecutor |
| 3 | Executor 不决策 | 零 `decision_pipeline` / `autonomy_policy` 调用 | Executor 做「要不要做」判断 |
| 4 | Tool 是扩展能力 | 新增能力 = 声明 Adapter，不改抽象/Executor | 新增能力改 Action 模型 |
| 5 | 所有执行必产 Result | 无 `None` 返回 | 执行路径无结果台账 |
| 6 | Result 支持反馈 | 四通道回写 + 三面反馈 | 结果不回写决策/反思面 |

---

## 7. 六风险收口（architecture §14）

| # | 风险 | 收口结论 | 验证 |
|---|---|---|---|
| R1 | 多步状态一致性 | 单 Action 多步顺序执行，部分失败不回滚（`partial` 记录） | scenario D |
| R2 | 旧读键退役兼容 | 双写一个版本窗口（V2.6.0）后退役 | `test_v26_task006_result.py` |
| R3 | 调度执行一致性 | `uq_action_schedules_action` + 幂等重建 | `test_v26_task005_scheduler.py` |
| R4 | Action 过度设计 | 字段最小化，可选项明确 | `test_v26_task001_model.py` |
| R5 | 反馈预算竞争 | 有界（复用缓存形态） | `test_v26_task007_integration.py` |
| R6 | 新表打破零迁移惯例 | 唯一新表 + 唯一加列，明确裁决 | `test_v26_task002_persistence.py` |

---

## 8. 兼容性红线（评审一票否决项）

1. **零新建 Agent / Memory / Session / Event 系统**：Action 层不新建任何同类系统。
2. **`action_records` 复用**：不新建 `actions` / `action_results` / execution records 表。
3. **世界唯一写面**：Action 层零直写 `world_engine`，经 `deferred_world_op` → outbox。
4. **记忆政策零豁免**：执行结果进记忆经 `memory_policy` R1~R8。
5. **工具治理不绕过**：`execute_tool` 经 `ToolExecutor` 五段短路，零直调 `Capability.execute`。
6. **Flag 全 off 逐字节一致**：prompt + 行为快照 + 维护步骤序列。

---

## 9. 上线前待办

> V2.6.1 P0/P1 部分已关闭；下列为灰度与后续项。

- [x] TASK-001 ~ TASK-008 实现（V2.6.0）
- [x] TASK-009 四类测试 + Flag 矩阵 + 本清单自动化落地（V2.6.0 + V2.6.1 补齐真实文件名）
- [x] V2.6.1 P0：结果全形态 / 调度执行 / 反馈闭环 / 来源语义 / 恢复终态
- [x] V2.6.1 P1：Flag 治理、退避守卫、`plan_step` 溯源、`run_id` 列、多步 RESERVED、文档对齐
- [ ] 旧读键退役：Flag on 且全量测试通过后，退役 `world_event_id` / `memory_id` / `failure_kind` 旧位置（architecture §14 R2）
- [ ] 真实模型人工回归（本清单 §2 人工补充项）
- [ ] P2 残留：`action_engine` 分层拆分、Queue/Worker 化、多角色就绪、多步真正交付（非 RESERVED）
