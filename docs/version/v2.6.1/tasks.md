# V2.6.1 Refactor Tasks（P0 修复批次）

> **上游**：`docs/version/v2.6.0/audit-report.md`（只读审计）
> **上游版本**：`docs/version/v2.6.0/`（设计合格、运行时未接通；综合 5.5/10）
> **定位**：V2.6.0 → V2.7.0 之间的**质量门槛批次**。只做「定向修复 + 契约收敛」，不推翻值对象 / 六态状态机 / 持久化红线。
> **主干**：REF-001 ~ REF-006（顺序即推荐执行顺序）
> **红线**：P0 全部完成前，**禁止打开 `v26_action_execution_enabled`**；Flag off 面（v26 + v9 + v24 tool003 + v25）必须保持全绿。
> **当前工作区**：`feat/feishu_bot` 上已有部分未提交改动（见 §4 WIP 快照），建卡时以磁盘现状为准，不重复造已写好的轮子。

---

## 0. 批次前提裁决

| 裁决 | 内容 | 理由 |
|---|---|---|
| 不拆骨架 | 不改 `Action` 值对象字段集、不改六态 `ActionStatus`、不新建表（除 `action_schedules` 字段扩展若调度消费端需要） | 审计 §14.3：本版本最扎实的部分是值对象与状态机 |
| 结果形态单一化 | `steps[].result` 冻结为「新契约字段 + 旧读键 `payload`」双形态，与 Flag 无关 | 消灭同列两态；保护 outbox / 证据窗 / Replay |
| 来源语义正式化 | `source="plan"` 正式化：关系映射补 `plan` 行；自治日额度计 `in ("autonomy","plan")` | 桥已写 `plan`，额度/关系必须跟上，否则静默漂移 |
| 反馈唯一入口 | 主路径必须经 `integration.apply_result_feedback`；三面（Autonomy/Reflection/Planning）各至少 1 个真实消费者 | 消灭「写而不读」与契约/运行时分叉 |
| 调度双源收口 | 执行完成后 `action_schedules` 与 `trigger_registry` 同步进终态；终态行禁止复活 | 消灭重复自治 tick（LLM 成本泄漏） |
| 验收先红后绿 | 每卡先落 §附录 B 对应测试（可先红），再改生产代码 | 避免修完无守护 |

---

## 1. 任务总览

### 1.1 总览表

| ID | Task Name | Priority | 债务 | 依赖 | 推荐序 |
|---|---|---|---|---|---|
| REF-001 | Action Result Full Shape & Dual-Write | P0 | D01 / D07 / D11（部分） | 无 | 1 |
| REF-002 | Source Semantics Unification | P0 | D04 / M5 | 无 | 2 |
| REF-003 | Feedback Loop Closure | P0 | D05 | REF-001, REF-002 | 3 |
| REF-004 | Schedule Execution Consumer | P0 | D02 | REF-001 | 4 |
| REF-005 | Schedule / Trigger Consistency | P0 | D03 | REF-004 | 5 |
| REF-006 | Recovery & Terminal States | P0 | D06 / M4 | REF-001 | 6 |
| REF-007 | P0 Verification Gate | P0 | — | REF-001~006 | 7 |
| REF-101 | Flag Governance | P1 | D08 / D16 | REF-007 | 8 |
| REF-102 | Execute Backoff Guard | P1 | D13 | REF-007 | 9 |
| REF-103 | State Machine Authority Sweep | P1 | D12 | REF-007 | 10 |
| REF-104 | Traceability Fields | P1 | D10 / M1 / M2 | REF-007 | 11 |
| REF-105 | Multistep Decision | P1 | D09 / F7 | REF-007 | 12 |
| REF-106 | Layering & Docs Convergence | P1 | D14 / D15 / D11 收尾 | REF-007 | 13 |

**Priority 语义**：P0 = Flag on 前必须清零（已完成）；P1 = 工程收敛，可与 V2.7 设计并行。

### 1.2 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| Phase A 事实面 | REF-001, REF-002 | 执行事实完整、来源语义一致 |
| Phase B 闭环面 | REF-003 | 反馈投影有真实消费者 |
| Phase C 调度面 | REF-004, REF-005 | 到期可执行、双源终态收口 |
| Phase D 恢复面 | REF-006 | 无永久非终态 |
| Phase E 门禁 | REF-007 | P0 复核 + 全量回归 + 重新 Audit |

---

## 2. 依赖关系

```text
REF-001 结果全形态 ──┬──► REF-003 反馈闭环
                     │
REF-002 来源语义 ────┘
                     │
REF-001 ─────────────┼──► REF-004 调度消费端 ──► REF-005 一致性收口
                     │
                     └──► REF-006 恢复与终态
                     
REF-001~006 ──► REF-007 门禁（T1~T7 全绿 + off 面回归 + P0 复核）
```

**关键路径**：REF-001 → REF-004 → REF-005 → REF-007  
**可并行**：REF-001 完成后，REF-002 / REF-006 可与 REF-003 / REF-004 并行推进。

### 2.1 与 V2.6.0 原任务的映射

| 本批任务 | 对应 audit §11.1 | 修复的债务 |
|---|---|---|
| REF-001 | P0-1 + P0-7 | D01, D07（并消解 D11 一半） |
| REF-002 | P0-4 | D04 |
| REF-003 | P0-5 | D05 |
| REF-004 | P0-2 | D02 |
| REF-005 | P0-3 | D03 |
| REF-006 | P0-6 | D06 |
| REF-007 | §13.2 P0 门禁 | — |

---

## 3. 批次门禁（Definition of Done）

| 项 | 判据 |
|---|---|
| 测试 | `tests/v26` + `tests/v9` + `tests/v24/test_tool003_action_engine.py` + `tests/v25` 全绿；附录 B 的 T1~T7 用例全绿 |
| 行为 | 「明天早上提醒我学习」端到端自动化可跑：Plan → Action → Schedule → 到期执行 → 世界事件 → 反馈 |
| 回归 | Flag 全 off 时 v9 / v24 面逐字节不回归；E3 的 `node_modules` 脆弱扫描用例一并修掉 |
| 债务 | audit 报告一票否决项（§14.5）五条全部可判定清零 |
| 留痕 | 在 `audit-report.md` 末尾追加「P0 复核结论」与日期 |

---

## 4. 工作区 WIP 快照（建卡时磁盘现状）

> 下列改动已在 `feat/feishu_bot` 工作区未提交。任务卡中标注 **WIP** 的条目表示「代码主路径已有实现，仍缺测试与验收」；标注 **TODO** 的表示尚未开始。

| 任务 | WIP 状态 | 已见改动 |
|---|---|---|
| REF-001 | **DONE（代码+测）** | `executor.py` 改调 `result.from_*`；`step_result_payload` 双形态；`integrate_result` 不再覆盖已有 payload；T1/T2 测试绿 |
| REF-002 | **DONE（代码+测）** | 关系映射 `plan` 行；额度计 `plan`；`relationship_bridge` 修复 `session_id=None`；T7 测试绿 |
| REF-003 | **DONE（代码+测）** | 主路径 `_apply_feedback` → `apply_result_feedback`；Autonomy `recent_feedback`；Reflection 证据窗反馈键；Planning `to_plan_step_outcome` 生产投影 |
| REF-004 | **DONE（代码+测）** | 维护步 CAS 认领 → `Manager.execute` → `mark_schedule_executed`；端到端提醒可跑 |
| REF-005 | **DONE（代码+测）** | 成功后 trigger `done`；终态 `action_schedule` 不复活 |
| REF-006 | **DONE（代码+测）** | `_recover_stale_executing` 已挂 `_expire_planned`；`partial→failed`；T5/T6 测试绿 |
| REF-007 | **DONE（P0 复核通过）** | 1744 回归绿；E3 已修；audit 附录 C 留痕 |
| REF-101 | **DONE** | `.env.example` 登记 V26 闸；`enablement_violations` 总闸⇒action_enabled；RESERVED 告警 |
| REF-102 | **DONE** | `Manager.execute` 退避窗口守卫；恢复步经 `transition_action` |
| REF-103 | **DONE（关键路径）** | 恢复步经 `transition_action`；partial 不滞留；权威断言测试 |
| REF-104 | **DONE（plan_step；run_id 债务登记）** | 桥回填 `plan_step=step_<i>`；`run_id` 仍别名 session_id（D10 已知，待迁移） |
| REF-105 | **DONE（RESERVED 裁决）** | `action_plan_max_steps=1`；multistep Flag RESERVED + 告警 + 文档 |
| REF-106 | **DONE（文档对齐）** | 回归清单文件名对齐；architecture 映射表与代码一致；分层拆分仍留 P2 |
| 全部 | **P0+P1 关闭（分层拆分与 run_id 迁移留后续）** | 可进入 Flag on 灰度准备 |

**执行建议**：先为 WIP 项补红/绿测（不改生产代码），再推进 TODO 项；提交前按 REF 卡拆分 commit，避免「一锅端」。

---

## 5. 任务明细（摘要）

完整 Task Detail 见 `tasks/REF-XXX.md`。此处只保留 Goal 与验收锚点。

### REF-001 Action Result Full Shape & Dual-Write

**Goal**：Flag on 主路径 `steps[].result` 同时含新契约字段与旧读键；outbox 世界写、工具证据窗、Replay 在 Flag on 下全部可工作。

**验收锚点**：`test_v26_step_result_contract.py` + `test_v26_outbox_world_write.py`（T1/T2）

### REF-002 Source Semantics Unification

**Goal**：`source="plan"` 正式化——关系信号不丢、自治日额度不绕过；文档与映射表一致。

**验收锚点**：`test_v26_source_semantics.py`（T7）

### REF-003 Feedback Loop Closure

**Goal**：`apply_result_feedback` 成为生产唯一入口；`feedback_kinds` / `temporary_execution` 至少各有 1 处真实消费者。

**验收锚点**：`test_v26_feedback_consumers.py`

### REF-004 Schedule Execution Consumer

**Goal**：维护步消费到期 schedule：原子认领 → `Manager.execute` → `mark_schedule_executed`；「明天早上提醒我」端到端可跑。

**验收锚点**：`test_v26_schedule_execution.py`（T3）

### REF-005 Schedule / Trigger Consistency

**Goal**：执行完成后 trigger 行 `done`；终态不复活；连续两轮维护步 `_due_trigger_present=False`。

**验收锚点**：`test_v26_schedule_execution.py`（T4 段）

### REF-006 Recovery & Terminal States

**Goal**：孤儿 `executing` 超时 → `failed`；`partial` 不滞留；无「永久非终态」路径。

**验收锚点**：`test_v26_recovery.py`（T5/T6）

### REF-007 P0 Verification Gate

**Goal**：批次收口——全量回归、文档对齐、audit P0 复核留痕、可进入 Flag on 灰度准备。

**验收锚点**：audit §13.2 P0 门禁四项全过

---

## 附录 A：涉及文件清单（按卡）

| 卡 | 主要生产文件 | 主要测试文件 |
|---|---|---|
| REF-001 | `services/action/executor.py`, `services/action/result.py`, `application/action_engine.py` | `tests/v26/test_v26_step_result_contract.py`, `test_v26_outbox_world_write.py` |
| REF-002 | `character/asuna/action.py`, `application/autonomy_engine.py`, `services/planning/executor_bridge.py`, `docs/.../architecture.md` | `tests/v26/test_v26_source_semantics.py` |
| REF-003 | `application/action_engine.py`, `services/action/integration.py`, `application/autonomy_engine.py`, `services/reflection/evidence.py`, `services/planning/executor_bridge.py` | `tests/v26/test_v26_feedback_consumers.py` |
| REF-004 | `services/action/scheduler.py`, `application/life_loop.py`, `services/action/manager.py` | `tests/v26/test_v26_schedule_execution.py` |
| REF-005 | `services/action/scheduler.py`, `repositories/trigger_registry_repository.py` | 同上 |
| REF-006 | `application/action_engine.py`, `repositories/action_repository.py`, `core/settings/action.py` | `tests/v26/test_v26_recovery.py` |
| REF-007 | `docs/version/v2.6.0/audit-report.md`, `regression-checklist.md`, `.env.example`（若并入 Flag 治理） | 全量 |

## 附录 B：建议测试文件（可直接建卡）

| 文件 | 覆盖 | 关联 |
|---|---|---|
| `tests/v26/test_v26_step_result_contract.py` | 主路径 steps/result 形态契约（新键 + `payload` + `tool_id` + `observations` + `duration_ms`） | REF-001 / T1 |
| `tests/v26/test_v26_outbox_world_write.py` | Flag on + outbox：`world_ops` 非空 → 消费后事件恰 1 | REF-001 / T2 |
| `tests/v26/test_v26_schedule_execution.py` | 到期执行 + trigger `done` + 不复活 | REF-004/005 / T3/T4 |
| `tests/v26/test_v26_source_semantics.py` | `plan` 来源关系信号与自治额度口径 | REF-002 / T7 |
| `tests/v26/test_v26_feedback_consumers.py` | 反馈投影有真实消费者 | REF-003 |
| `tests/v26/test_v26_recovery.py` | 孤儿 `executing` 超时；`partial` 不滞留 | REF-006 / T5/T6 |

---

## 附录 C：明确不在本批次

| 项 | 归属 |
|---|---|
| P1-1 ~ P1-8（归一份收尾、多步交付、Flag 治理、溯源字段、状态机唯一权威、退避守卫、分层拆分、文档全面对齐） | audit §11.2，可与 V2.7 设计并行 |
| P2-1 ~ P2-6（Queue/Worker、可观测性、多角色、External Adapter、测试策略、隐式容错） | audit §11.3 / V2.7+ |
| Flag on 灰度与真实模型人工回归 | REF-007 之后 |

---

**文档状态**：已建立 / 随实现更新卡状态（TODO → WIP → DONE）
