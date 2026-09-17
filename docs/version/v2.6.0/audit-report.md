# V2.6.0 System Audit Report

> **审查对象**：`AICustomerServiceAgent`（FastAPI + LangChain + PostgreSQL/SQLite）
> **分支 / 提交**：`feat/feishu_bot` / `1f74674`（V2.6.0 最后提交：`test: V2.6.0 验收测试与验收报告`）
> **审查范围**：Overall Architecture / Domain Model / Action Execution System / Code Quality / Database / Functional Completeness / Testing / Performance / Technical Debt / Refactoring / V2.7~V2.8 Readiness
> **上游文档**：V2.0 Autonomy / V2.3 World Simulation / V2.4 Relationship Dynamics / V2.5 Planning System / V2.6 Action Execution Architecture
> **审计性质**：**只读审查**——本报告不修改任何代码，只输出问题、债务、重构建议与执行计划
> **产出用途**：作为 V2.6.0 → V2.7.0 之间的质量门槛（Refactor Task 输入）

---

## 0. 审计方法与证据留痕

### 0.1 复现命令与实测结果

| # | 命令 | 实测结果 | 说明 |
|---|---|---|---|
| E1 | `uv run pytest tests/v26 -q` | **184 passed** | 与 `acceptance-report.md` 声明的 184 一致；v26 全部用例绿 |
| E2 | `uv run pytest tests/v9 tests/v24/test_tool003_action_engine.py -q` | **98 passed**（73 + 25） | Flag off 面：V9 行动语义 + V2.4 行动引擎接线零回归 |
| E3 | `uv run pytest tests/v25 -q` | **1414 passed, 1 skipped, 1 failed** | failed = `test_plan012_gates_and_invariants.py::TestOpenQuestionsClosed::test_q10_frontend_has_no_plan_debug_panel`，根因为静态扫描读 `apps/frontend/node_modules/decimal.js` 触发 Windows `PermissionError`（测试设计脆弱，非 V2.6 逻辑回归；但与 `acceptance-report.md` 声明的「1415 passed」不一致） |
| E4 | `uv run pytest tests/v23/test_ws004_day_cycle.py::test_maintenance_step_emits_markers tests/v21/test_agent008_review_fixes.py -q` | **2 failed, 24 passed** | `acceptance-report.md` 的 I1 / I2 两项「不阻断验收」缺陷**仍为红**（未修复、未独立跟踪） |
| E5 | `Get-ChildItem migrations/versions` | 链头 `0047_action_schedules_priority.py` | 唯一新表 `action_schedules` + 唯一加列 `action_records.priority`，符合 architecture §9.3 裁决 |
| E6 | `git diff --shortstat 2880354~1 HEAD` | app 16 文件 **+1738**；tests 26 文件 **+2270**；migrations **+134**；docs 13 文件 **+4138** | V2.6.0 实际改动规模（含 V2.6 期间的 v25 测试适配） |
| E7 | `Select-String .env`（`V26` 前缀） | 无命中 | 6 个 `v26_*` Flag **未登记 `.env.example`**，运维不可发现 |
| E8 | 全库检索 `feedback_kinds` / `temporary_execution` / `apply_result_feedback` / `from_capability_result` / `from_tool_execution` / `from_plan_step_outcome` | 生产者仅在 `app/` 内 2 处，**消费者 0 处**（除测试） | 反馈闭环「写而不读」；TASK-006/007 契约函数在生产路径上零调用 |

### 0.2 重点阅读面

- 值对象与状态机：`app/models/action.py`
- 执行层：`app/services/action/{contracts,executor,manager,result,scheduler,integration}.py`
- 编排与整合：`app/application/action_engine.py`（993 行）
- 仓储：`app/repositories/action_repository.py`、`app/repositories/trigger_registry_repository.py`
- 调度挂载：`app/application/life_loop.py`、`app/application/autonomy_engine.py`
- 计划桥：`app/services/planning/executor_bridge.py`
- 读面契约：`app/services/tool/{executor,normalizer,memory_policy}.py`、`app/services/reflection/evidence.py`
- 迁移与 schema：`migrations/versions/0047_action_schedules_priority.py`、`app/core/db.py`
- 调试面：`app/api/v1/action_execution.py`
- 测试：`apps/backend/tests/v26/*`（11 文件 184 例）
- 文档：`docs/version/v2.6.0/{architecture,tasks,acceptance-report,regression-checklist}.md` + `tasks/TASK-001~009.md`

---

## 1. Executive Summary

### 1.1 一句话结论

**V2.6.0 的「值对象层 / 契约层 / 持久化层」达到工程设计标准，但「执行运行时 / 调度运行时 / 反馈运行时」只交付了骨架：在当前形态下打开总闸会（a）静默降低执行数据质量、（b）产生永不终结的调度登记行、（c）让关系与自治额度语义漂移、（d）让部分 Action 永久停在 `executing`。**

因此 V2.6.0 是一个**结构正确、接线未完成**的版本：它给 V2.7 提供了正确的「形状」，但还没有提供 V2.7 需要的「数据」。

### 1.2 成熟度评分（0–10）

| 维度 | 评分 | 依据摘要 |
|---|---|---|
| Action 值对象 / 状态机 | **8** | 六态 + `_TRANSITIONS` + 纯函数，非法迁移返回 `None`；`tests/v26/test_task001_action_core_model.py` 47 例 |
| 契约冻结 | **7** | `contracts.freeze_contracts()` 四组校验（`contracts.py:61-89`），但「统一入口」`apply_result_feedback` 未接线 |
| 持久化 / 迁移 | **8** | 复用 `action_records`、唯一新表 + 唯一加列、可逆、SQLite 表重建保留索引 |
| 执行引擎 | **6** | 三路分派正确、异常归一完备；但结果形态有损（丢 `output/observations/effects/tool_id`）、`external` 为占位 |
| 调度器 | **4** | 排期 + 优先级 + 队列查询齐全；**到期执行消费端缺失**，trigger 行永久滞留 |
| 结果系统 | **6** | `ActionResult` 契约完整 + 双写函数存在；但生产路径未使用 `result.py` 的三个投影函数 |
| 反馈闭环 | **3** | 反馈投影写入 `record.result` 后**无人消费**；四系统仍走旧通道 |
| 故障恢复 / 自愈 | **2** | 无孤儿 `executing` 恢复；无 schedule 消费幂等收口；`partial` 无终态映射 |
| 调试 / 可观测 | **6** | 4 个端点 + 7 类日志事件；指标在内存聚合、N+1 查询 |
| 测试（自动化） | **6** | 184 例覆盖广，但含源码字符串断言与弱断言；缺端到端调度执行 / 恢复场景 |
| 文档-代码一致性 | **5** | 架构文档与代码映射表漂移；回归清单引用不存在的测试文件；上线前待办未勾选 |
| **综合** | **5.5** | 可进入 V2.7 开发，但**必须先完成 P0 修复**（见 §11/§13） |

### 1.3 关键发现（Top Findings）

| # | 发现 | 级别 |
|---|---|---|
| F1 | **V2.6 主路径把 `steps[].result` 降级为最小 `ActionResult`，丢失 `payload` / `tool_id` / `observations` / `duration_ms`** → outbox 世界写为空、工具证据窗失效、调试面板失真 | **P0** |
| F2 | **ActionScheduler 只登记不执行**：`action_schedules` 无运行时消费端，`consume_due_schedule` 生产零调用 → 「明天早上提醒我」链路断裂 | **P0** |
| F3 | **调度 trigger 行永滞 + 终态复活** → `life_loop` 每周期把该用户判为「有待办」，重复自治 tick（LLM 成本泄漏） | **P0** |
| F4 | **Planning 桥在 Flag on 时把 `source` 改为 `"plan"`**，而关系映射表无 `plan` 行、自治日额度只数 `source == "autonomy"` → 关系信号静默丢失 + 额度绕过 | **P0** |
| F5 | **反馈闭环名实不符**：`apply_result_feedback` 是测试专用死代码，主路径内联复制；`feedback_kinds` / `temporary_execution` 零消费者 | **P0** |
| F6 | **无孤儿 `RUNNING`/`executing` 恢复**（architecture §11.4 承诺），`partial` 结果无终态映射 → 记录可能永久停在 `executing` | **P0** |
| F7 | **多步执行未交付**：`action_plan_max_steps` 仍为 1，`v26_action_multistep_enabled` 无消费方（死 Flag）；B2 断层未关闭 | **P1** |
| F8 | **`v26_action_abstraction_enabled` 为死 Flag**（仅 settings + 测试引用），Flag 表与实现不符 | **P1** |
| F9 | **迁移链文档/测试 / 回归清单与真实文件名不一致**（引用 `test_v26_scenario_*.py` / `test_v26_flag_matrix.py` 等不存在的文件） | **P1** |
| F10 | 测试以源码字符串断言为主 + 弱断言 + 环境脆弱扫描（`node_modules`）→ 断言的是「文本」而非「行为」 | **P2** |

---

## 2. Architecture Review

### 2.1 目标链路 vs 实测连通性

目标闭环（`architecture.md:36-52`）：

```text
Autonomy（决定此刻做什么）
  → World Understanding → Relationship Modeling → Planning（计划）
  → Action → Execution → Result → State Update → Feedback
```

实测每段连通性（含证据）：

| 段 | 结论 | 证据 | 缺口 |
|---|---|---|---|
| Autonomy → Planning | ✅ 连通 | `life_loop._run_user_cycle` → `_step_goal_advance` → `PlanExecutorBridge.execute_step` | — |
| Planning → Action | ✅ 连通（语义有漂移） | `services/planning/executor_bridge.py:265-294` | `source` 由 `autonomy` 改为 `plan`；`plan_step` 未回传 |
| Action → Execution | ✅ 连通 | `application/action_engine.py:343-364` → `services/action/executor.py:206-226` | 分派正确，但 `tool_resolver` 恒取 `plan.steps[0]`（`:312-321`） |
| Execution → Result | ⚠️ 有损 | `services/action/executor.py:74-122` 只保留 `status/error/failure_kind/effects(空)` | `output` / `observations` / `metadata(usage)` 丢失 |
| Result → State Update | ️ 半连通 | `application/action_engine.py:725-785` 仍读旧键 `payload.world_event_id` / `payload.memory_id` | V2.6 形态无 `payload` → 世界效果与记忆效果引用丢失 |
| Result → Feedback（四系统） | ❌ 未闭环 | 全库检索：`feedback_kinds` / `temporary_execution` 无消费者 | Autonomy / Reflection / Planning 仍只读旧形态 |
| Schedule → Execution | ❌ 断路 | `services/action/scheduler.py:148-190`（只登记）；`due_actions` / `next_action` 仅测试与 debug 调用 | 无到期执行者，无 `executed` 收口 |
| Recovery（崩溃/孤儿） | ❌ 未实现 | `application/action_engine.py:1059-1072` 仅处理 `planned` 过期 | architecture `:900-907` §11.4 承诺未兑现 |

**判定**：链条「形似闭合、实未闭合」。以 architecture §5.4「权威函数唯一化」表逐条核对，`ActionManager`、`ActionExecutor`、`ActionResult` 三项权威在**写入**方向成立，在**消费**方向（尤其调度与反馈）不成立。

### 2.2 架构优点

1. **值对象零依赖纪律真正落地**：`models/action.py` 无 `app.repositories` / `app.services` / IO（`tests/v26/test_task009_validation.py:143-148` 静态断言），六问可答（`:139-142`）。
2. **执行方式分派是纯数据扩展点**：`ACTION_EXECUTION_MAP`（`models/action.py:51-61`）九类型全覆盖 + `dispatch` 纯函数（`services/action/executor.py:70-71`）→ 「新增 Action = 加一行」，Executor 与 Manager 无需改动。
3. **异常永不逃逸**：`CapabilityExecutor` 超时/异常双归一（`executor.py:44-67`）+ `ActionExecutor.run` 顶层兜底（`:220-226`）→ 满足「所有执行必产 Result」原则（`:216-219` 无 `None` 返回路径）。
4. **红线未破**：`services/action/integration.py` 零 `world_engine.` / `relationship_bridge.` / `memory_repository.` 直写（`tests/v26/test_acceptance.py:289-293`）；`executor.py` 零 `decision_pipeline` / `autonomy_policy`（`test_task004_executor.py:168-175`）；工具路径经 `ToolExecutor` 五段短路（`action_engine.py:300-341, 503-548`）。
5. **Flag 范式与既有版本一致**：总闸 + 子闸 + 启动即校验（`core/settings/action_execution.py:23-38`），off 面维护步立即 `skipped`（`services/action/scheduler.py:159-163`），life_loop 步骤按闸注册（`life_loop.py:280-286`）。
6. **迁移克制且可逆**：唯一新表 + 唯一加列；SQLite 表重建保留 `ck_action_records_status` 与原三索引（`0047:61-91`），`downgrade` 对称回收。

### 2.3 架构缺陷

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| A1 | **分层倒置**：services 层反向依赖 application 层 | `services/action/manager.py:169-170`、`services/action/integration.py:113`（函数内 import `app.application.action_engine`）；`services/planning/executor_bridge.py:63` 模块级 import `run_action_planning` | 服务层不可脱离编排层复用；V2.7 继续加线时循环依赖风险上升 |
| A2 | **两套执行结果形态并存，读面未双形态适配** | 写：`action_engine.py:365-374`（最小）/ `:512-551`（富）二选一；读：`services/reflection/evidence.py:819-836` 依赖 `step["tool_id"]`、`normalizer.py:116-120` 明写「outbox 依赖 payload」 | 打开总闸即静默降级；下游数据质量污染（V2.7 经验记忆的直接输入） |
| A3 | **调度器缺消费端**（只写不读队列） | `scheduler.py:118-149` 无生产调用方 | B4 断层只关闭一半；「延迟/定时执行」不可用 |
| A4 | **trigger_registry 行滞留 + 终态复活** | `scheduler.py:176-187` 每 tick 重复 `register`；`repositories/trigger_registry_repository.py:94-96` 终态→`pending` 复活；无 `done`/`cancelled` 收口 | `life_loop._due_trigger_present:122-127` 恒真 → 重复自治 tick，成本泄漏 |
| A5 | **状态机非唯一写面**（与 R5「`transition_action` 权威」宣称不符） | 直接赋值：`action_engine.py:202`、`:835`、`:554`；`scheduler.py:86` 用了 `transition_action` 但 `:83` 又直接判 `created` | 迁移语义与审计口径存在旁路，未来加边容易漏改 |
| A6 | **反馈「统一入口」未接线** | `services/action/integration.py:111-151` 无生产调用；主路径内联复制于 `action_engine.py:749-765`；`result.py:38/86/136` 三个投影函数生产零调用 | 契约与运行时分叉；「唯一入口」不可判定 |
| A7 | **调度语义双源**（`action_schedules` + `trigger_registry`）无一致性收口 | `scheduler.py:78-99` 双写；无对账/收敛函数 | 两表可漂移；孤儿 schedule 无修复路径 |
| A8 | **多步能力名存实亡** | `core/settings/action.py:16`（`=1`）；`v26_action_multistep_enabled` 无消费方；`action_engine.py:312-321` 工具绑定恒取第 0 步 | architecture §7.1「兑现 V2.5.0 遗留 Q1」未兑现 |
| A9 | **单角色硬编码蔓延到跨角色资产层** | `models/action.py:51-61`（全局映射）+ `character/asuna/action.py`（能力/记忆/关系表）+ `models/action.py:312`（`character_id="asuna"` 默认） | 「更多角色」= 改值对象与执行层，不是加角色包 |

### 2.4 潜在风险

| # | 风险 | 触发条件 | 后果 |
|---|---|---|---|
| R1 | **Flag on 后 outbox 世界写丢失** | `v26_action_execution_enabled=on` 且 `v2_action_outbox_enabled=on` | 提醒/世界动作「报成功但世界无事件」——最严重的静默数据丢失 |
| R2 | **`v26_action_feedback_enabled=on` 后 `record.result` 被反馈投影覆写** | `action_engine.py:759` | 下游按 `ActionResult` 解析 `record.result` 时字段语义被扩写（含 `feedback_kinds` 等非契约键），隐式依赖 pydantic `extra=ignore` |
| R3 | **trigger 表随调度量线性增长且无回收** | 每次 `schedule()` + 每 tick 复登记 | 表膨胀、自治 tick 空转、可观测噪声 |
| R4 | **`partial` 结果导致记录永久 `executing`** | 任何产出 `partial` 的路径（当前仅 `result.py:150-151`，未被主路径调用） | 未来启用后：记录不终态、不计重试（`list_retryable` 要求 `next_retry_at`）、`count_active` 永久 +1 |
| R5 | **计划步与行动的一致性只在一侧成立** | 桥 `_dispatch` 未回填 `plan_step`（`executor_bridge.py:276-284`） | `PlanStepOutcome` / 反馈 `plan_step` 为空，Replay 与「哪一步做了什么」不可追 |
| R6 | **`Manager.execute` 可绕过退避窗口** | `manager.py:167-181` 对 `executing` 直接执行；`action_engine.py:403-411` 不校验 `next_retry_at` | 重复外部调用（幂等键兜底但工具层 `idempotency=none` 不保证安全） |

---

## 3. Domain Model Review

### 3.1 逐实体评估

| 实体 | 位置 | Entity 设计 | 状态管理 | 生命周期完整度 | 未来扩展性 | 判定 |
|---|---|---|---|---|---|---|
| **Character** | `models/character_action.py` / `core/db.py`（`character_id` 列） | 表兼容多角色（列存在，默认 `asuna`） | 无（角色不是状态机） | 完整 |  资产层（能力/记忆/关系/工具）全部绑定 `asuna` 包；`ACTION_EXECUTION_MAP` 定义在 `models/action.py` 而非角色包 | **需改造**（多角色前） |
| **World State** | 不在 V2.6 范围（V8/V2.3 所有，`world_engine` 唯一写面） | 良好 | 良好 | 完整 | 良好 | 保持（V2.6 只经 `deferred_world_op` → outbox） |
| **Relationship** | `models/relationship.py` + `ACTION_RELATIONSHIP_MAP` | 信号映射表「刻意收缩为两格」 | 由 `state_engine.apply_relationship_v5` 三层钳制 | 完整 | ⚠️ 映射键含 `source`，来源扩张（`plan`/`event_driven`）必须同步补行 | **需补表**（V2.6 已暴露） |
| **Plan** | `models/plan.py`（`PlanStepSpec` / `PlanStepOutcome`） | 良好（`attempt_count` 归 Plan 层） | 良好 | 完整 | 良好 | 保持；但 `PlanStepOutcome` ↔ `ActionResult` 映射为**只读投影**，实际未用于回写（`integration.to_plan_step_outcome` 生产零调用） |
| **Action** | `models/action.py:258-276` | 字段最小化达标（`test_task009_validation.py:242-260` 断言 15 字段） | 六态 + 纯函数状态机（`:130-168`） | ⚠️ 缺「恢复」阶段语义（无 `executing` 超时出口） | 良好（type 走映射表） | **需微调**（`run_id` 语义 / `plan_step` 落位） |
| **ActionResult** | `models/action.py:225-255` | 契约完整（id/action_id/status/effects/error/failure_kind/output/metadata/observations/created_at） | — | ⚠️ `partial` 无对应 `ActionRecord` 状态 | 良好（`observations` 白名单可扩） | **需裁决**（partial 映射） |
| **ActionRecord** | `models/action.py:309-334` | 复用 V9 台账，加 `priority` | 六态与 `ActionStatus` 同源 | 完整 | 良好 | 保持 |
| **ActionSchedule** | `models/action.py:351-359` | 最小（id/action_id/when_type/scheduled_at/priority/status） | 四态 `scheduled/due/executed/cancelled` | ❌ 无 `attempt_count` / `last_attempt_at` / `cooldown_until` → 无法表达「已尝试但失败」「退避后重试」 | ️ cron 语义简化到「下一时刻」 | **需扩展**（执行接入前） |
| **Action → ActionRecord 投影** | `services/action/manager.py:36-59` | ️ `run_id=record.session_id` 语义错配（architecture §6.1 定义 `run_id = loop_runs.id`）；`plan_step` 从 `intent.plan_step` 反读（无列） | — | — | — | **需修正** |

### 3.2 需要修改的模型列表

| # | 模型 / 字段 | 建议变更 | 理由 | 优先级 |
|---|---|---|---|---|
| M1 | `Action.run_id` ↔ `ActionRecord.session_id` | 二选一：新增 `run_id` 列（真 `loop_runs.id`）或把 `Action.run_id` 改名为 `session_id` | 当前映射会让「按 Run 追一次执行」永久错位（`manager.py:58`、`action_engine.py:362`） | P1 |
| M2 | `Action.plan_step` / `ActionRecord.intent["plan_step"]` | 升为 `ActionRecord` 独立列（或固定在 `intent` 但桥必须回填） | 计划行动 1:1 溯源是 V2.5/V2.6 契约点（`executor_bridge.py:276-284` 未回填 → 断链） | P1 |
| M3 | `ActionSchedule` | 增 `attempt_count` / `last_attempt_at` / `cooldown_until` / `finished_at`；或明确「schedule 一次性，重试走 Action 层」并冻结文档 | 现无字段可表达「已尝试、待退避」→ 调度与执行无法一致性收口 | P0（执行接入时） |
| M4 | `ActionResult.status` × `ActionRecord.status` | 明确 `partial` → 记录态映射（建议 `failed` + `failure_kind=transient`，或新增中间态裁决）并写入 `architecture.md §6.4` | 现状无出口（`action_engine.py:383-387` 提前 return → 记录留 `executing`） | P0 |
| M5 | `ACTION_RELATIONSHIP_MAP` | 补 `("create_reminder","plan","succeeded")` 等 `plan` / `event_driven` 行（或统一按 `autonomy` 记账） | Flag on 后关系信号静默丢失 | P0 |
| M6 | `ACTION_EXECUTION_MAP` 归属 | 迁到角色资产包（或按 `character_id` 建注册表） | 多角色扩展前必须解耦 | P2 |
| M7 | `ActionRecord.character_id` | 去掉 `"asuna"` 默认或改为必填 / 由角色上下文注入 | 默认值会掩盖漏传角色 id 的缺陷 | P2 |
| M8 | `ActionResult.dual_write_legacy_keys` 输出面 | 双写键位置须与 `services/tool/normalizer.py:116-120` 的 `payload` 旧读键对齐 | 双写写的是 `record.result` 顶层，而 outbox 读 `steps[].result.payload` → 双写窗口名不副实 | P0 |

---

## 4. Action Execution System Review

### 4.1 Action Definition

| 检查项 | 结论 | 证据 |
|---|---|---|
| Action 类型设计 | ✅ 九类型值集零变化，覆盖 internal/tool/external 三种执行方式 | `models/action.py:15-61` |
| 参数设计 | ✅ `ActionSchema`（required/optional/validators）在能力层声明；`normalize_core_params` 只用于幂等键 | `models/action.py:171-190, 286-306` |
| 扩展能力 | ✅ 新增 Action = 映射表加一行 + 注册能力；`ActionSource` 五值 | `models/action.py:39-61` |
| 与文档一致性 | ❌ 漂移：architecture §6.2 映射表列出 `world_action` / `search` 两个代码中不存在的键 | `architecture.md:371-379` vs `models/action.py:51-61` |
| 参数规范化纪律 | ⚠️ 桥 `to_intent` 明确不做 `normalize_core_params`（避免「规划期替执行期加工」），需长期保持 | `executor_bridge.py:40-46` |

### 4.2 Executor

| 检查项 | 结论 | 证据 |
|---|---|---|
| 执行流程 | ✅ 分派 → 三路 → 异常归一 → 必产 Result | `services/action/executor.py:206-226` |
| 调度方式 | ⚠️ 仅同步 + 「Action 级延迟登记」；异步 / 长任务无执行路径（队列消费端缺失） | `scheduler.py:156-190`；`architecture.md:478-486` §7.2 |
| 状态转换 | ⚠️ Executor 不写状态（正确），但编排层存在直接赋值旁路（见 A5） | `action_engine.py:202, 554, 835` |
| **结果保真度** | ❌ **有损**：`execute_internal` 走 `_normalize_capability_result`（成功分支丢 `payload→output` / `observations` / `usage`）；`execute_tool` 走 `_tool_execution_to_result`（丢 `execution.result` 全部内容：effects / observations / payload / duration） | `executor.py:80-92, 112-122` |
| 工具绑定正确性 | ❌ 恒取 `plan.steps[0]`、`index=0` 写死 → 多步时绑定与索引错误 | `action_engine.py:312-321, 367` |
| External 路径 | ️ 占位：固定返回 `failed / unavailable / external_adapter_reserved`（设计内，V2.7 兑现） | `executor.py:197-204` |

### 4.3 Result Handling

| 检查项 | 结论 | 证据 |
|---|---|---|
| 结果结构 | ✅ 契约完整（10 字段）；❌ 生产路径未使用契约投影函数 | `models/action.py:225-255`；`services/action/result.py:38-164`（生产零调用） |
| Feedback 机制 | ❌ 写而不读：投影写入 `record.result`（Flag on 时）；`feedback_kinds` / `temporary_execution` 全库零消费者 | `action_engine.py:749-765`；`integration.py:111-151`（未接线） |
| 错误恢复 | ⚠️ 重试数学唯一（`action_engine.py:389-400 / 629-641`）；无孤儿恢复、无 `partial` 终态、退避可被 `Manager.execute` 绕过 | `action_engine.py:1059-1072`；`manager.py:167-181` |
| 四类结果 | ⚠️ `succeeded` / `failed` 可用；`timeout` 受 `v26_action_result_enabled` 影响（on= `timeout`，off= `failed`）；`partial` **无生产者** | `result.py:55-66`；`models/action.py:228` |
| 旧读键退役承诺 |  未形成「兼容窗口」：Flag on 时下游依赖的旧键（`steps[].result.payload`）**直接不再产生** | `services/tool/normalizer.py:117`（明写 outbox 依赖）；`action_engine.py:794-805` |

### 4.4 未来能力支持度判定

| 未来能力 | 支持度 | 判定依据 | 需要的改造 |
|---|---|---|---|
| **Tool Calling** | ️ 60% | 分派 + `ToolExecutor` 五段短路已通（`action_engine.py:300-341`）；但结果缺 `tool_id` / `observations`，多步绑定写死第 0 步 | 修 F1 + 步级 `index` 透传 |
| **External API** | ⚠️ 30% | `ExecutionKind.EXTERNAL` 与占位返回就绪；无 Adapter 契约、无超时/重试策略、无授权作用域衔接 | 定义 Tool Adapter 接口 + 外部失败语义（`architecture.md:941-959`） |
| **Environment Interaction** | ⚠️ 45% | 世界读写经 outbox 唯一路径（红线正确）；但 Flag on 时 outbox `world_ops` 恒空 | 修 F1 后即基本就绪 |
| **多步 Action** |  15% | `action_plan_max_steps=1`、多步 Flag 未消费、工具绑定与步骤索引写死 | 放开步数 + 步级绑定 + `partial` 裁决 |
| **异步 / 长任务** | ❌ 20% | 无队列消费端；`background_jobs` / outbox 未接入 Action 执行 | 引入 Action Worker（见 §11 P1） |

---

## 5. Code Review

### 5.1 架构层

| 检查项 | 结论 | 证据 |
|---|---|---|
| Service 过大 | ⚠️ `application/action_engine.py` **993 行**，承担「建记录 → 闸门 → 装配 → 执行 → 整合 → 重试 → 恢复 → 事实收集」八职责；`services/action` 6 模块体量尚可（manager 190 / executor 204 / scheduler 165 / result 156 / integration 135 / contracts 74） | `application/action_engine.py`；各模块行数 |
| Controller 包含业务逻辑 | ✅ 无。`api/v1/action_execution.py`（85 行）只做门控 + 仓储读 + JSON 投影 | `api/v1/action_execution.py:28-101` |
| 数据访问混乱 | ⚠️ 仓储惯例干净；但存在**绕过仓储的状态直写**：`api/v1/action.py:71-75` 直接改 `status/attempt/next_retry_at` 并 `save_record`（V9 遗留调试端点），与「状态迁移唯一权威」冲突 | `api/v1/action.py:60-75` |
| 重复逻辑 |  三处：①结果归一 `executor._normalize_capability_result` / `_tool_execution_to_result` 与 `result.from_capability_result` / `from_tool_execution` **双份**（前者有损且被生产调用；后者富且仅测试）；②反馈投影 `integration.apply_result_feedback`（死）与 `action_engine.integrate_result:749-765`（活）双份；③重试结账 `action_engine.py:389-400` 与 `:629-641` 近乎同构 | 见 §4.2 / §4.3 |
| 分层纪律 | ❌ 倒置（A1）；另 `services/action/contracts.py` 以「反射 + 源码级契约表」表达接口冻结，属可接受的测试性资产，但置于 `services` 而非 `tests` 易误解 | `services/action/contracts.py:8-89` |

### 5.2 代码风格

| 检查项 | 结论 | 证据 |
|---|---|---|
| 命名规范 | ✅ 一致（函数/模块常量/私有前缀；仓储「模块级动词」惯例统一） | 全局 |
| 类型设计 | ⚠️ 关键跨界处用 `Any` 抹平：`ActionExecutor.__init__(tool_executor: Any, tool_resolver: Any, permission_snapshot: Any, tool_context: Any)`、`result.from_tool_execution(execution: Any)` | `executor.py:125-137`；`result.py:86` |
| 异常处理 | ️ 归一路径完备，但**静默吞掉**偏多：`manager.py:41-42`（`ActionResult.model_validate` 失败静默置 `None` → 坏数据不可见）、`integration.py:134-136`、`executor_bridge.py:302-304` | 同上 |
| 可维护性 | ⚠️ 隐式容错：`_append_effect:701-704` 把可能已被反馈投影扩写的 `record.result` 直接 `ActionResult(**...)` 重建，依赖 pydantic `extra=ignore`；若未来收紧为 `forbid` 即崩 | `action_engine.py:701-704, 759, 781` |
| 时间与并发 | ️ 全链路 naive `datetime.now()`（与既有约定一致，保留）；`Manager.execute` 未持 per-user 写锁（当前调用方在锁内，但契约未声明） | `manager.py:167-181`；`life_loop.py:231` |
| 注释纪律 | ✅ 遵守「用命名表达意图」+ 文档字符串承载设计出处（`architecture.md §x`） | 全局 |

### 5.3 可扩展性

| 未来增量 | 需要改动的面 | 工作量 |
|---|---|---|
| **更多 Action 类型** | ✅ 小：映射表加一行 + 能力注册（+ 关系/记忆表补行） | 低（设计目标达成） |
| **更多角色** | ❌ 大：`ACTION_EXECUTION_MAP`（值对象层）+ 角色包（能力 / 记忆模板 / 关系映射 / 工具面）+ `character_id` 默认值 + 台账口径 | 高（需先做 M6/M7） |
| **更多环境（External）** | ⚠️ 中：需先补 Adapter 契约与外部失败语义；分派层已预留 | 中 |
| **多步 / 异步** | ❌ 大：步级绑定、步级幂等、`partial` 语义、队列消费端、崩溃恢复 | 高（V2.7+） |
| **新指标 / 新面板** | ✅ 小：debug 端点模式可复制（与前端解耦，Q5 已记录） | 低 |

---

## 6. Database Review

### 6.1 表设计与字段

| 表 | 结论 | 证据 |
|---|---|---|
| `action_records`（复用） | ✅ 未新建 `actions` / `action_results` / execution records；新增 `priority`（NOT NULL，server_default 100） | `0047_action_schedules_priority.py:95-98`；`core/db.py:660-690` |
| `action_records.source` CHECK | ✅ 由三值放宽为五值，SQLite 走表重建（保留 `ck_action_records_status` + 3 索引），PG 走 drop/create constraint | `0047:19-91` |
| `action_schedules`（新表） | ⚠️ 字段最小但**不足以承载重试语义**（无 `attempt_count` / `last_attempt_at` / `finished_at`）；`when_type` / `status` CHECK 齐全 | `0047:100-122`；`models/action.py:351-359` |
| 结果落位 | ✅ 结果落 `action_records.result`、步骤落 `steps`（JSON），**零新表**，符合 §9.3 裁决 | `0047` 头部注释 |
| JSON 列形态一致性 |  `steps[].result` 存在**两种 schema**（V9 富形态 / V2.6 最小形态），同列多态 → 所有读面必须容错 | 见 §2.3 A2 |

### 6.2 索引

| 索引 | 服务的查询 | 问题 |
|---|---|---|
| `uq_action_schedules_action(action_id)` | 一 Action 一调度（幂等重建锚点，R3） | ✅ 正确；副作用：同一 Action 无法重复排期（cron 重复触发需新 Action 或表扩展） |
| `idx_action_schedules_due(status, scheduled_at, priority)` | `status IN ('scheduled','due') AND scheduled_at <= now ORDER BY priority DESC, scheduled_at` | ⚠️ `status` + `scheduled_at` 范围已耗尽前两列，第三列 `priority` 无法服务排序 → 退化为临时排序；建议 `(status, priority, scheduled_at)` 或拆分 |
| `idx_action_records_user_status` / `_user_dedupe` / `ix_..._user_id` | 用户维度查询、去重闸门 G4 | ✅；但 `list_by_status(status)`（debug 指标）**无 status 前导索引** → 6 次大范围扫描 |
| `list_retryable` 查询索引 | `status='executing' AND next_retry_at <= now` | ❌ 缺 `(status, next_retry_at)` 索引（`trigger_registry` / `outbox_events` 均有同类索引先例）→ 维护步每次全表扫描 |
| `list_by_dedupe` 查询索引 | `user_id + dedupe_key + created_at >= since` | ✅ 由 `idx_action_records_user_dedupe` 覆盖（缺 `created_at` 末列，可接受） |

### 6.3 数据生命周期

| 数据 | 现状 | 问题 |
|---|---|---|
| `action_records` | 有 `retain_cleanup`（V9 既有保留策略） | ✅ |
| `action_schedules` | **无清理 / 归档路径**；`executed` / `cancelled` 永久保留；`due` 行永不推进（无消费者） | ❌ 生命周期未定义（架构未写保留窗口） |
| `trigger_registry`（`action_schedule:*`） | 每 tick 复登记、无终态收口、终态复活 | ❌ 无界增长 + 复活（A4） |
| `outbox_events`（`action_result`） | 走既有消费器 + 死信退避 | ⚠️ Flag on 时 `world_ops` 恒空 → 「消费成功但零副作用」 |

### 6.4 查询 / 分析 / Replay / Debug 支持度

| 能力 | 支持度 | 说明 |
|---|---|---|
| **查询** | ⚠️ 中 | 按 id / user / status / dedupe / retry / planned 齐备；缺按 `schedule`、`goal_id`、`source`、`execution_kind` 的索引化查询 |
| **分析** |  低 | 指标由 Controller 内存聚合（`action_execution.py:73-87`：6 次 `list_by_status(limit=500)` + Python 过滤），无 DB 聚合、无时间窗索引；Action 面未纳入既有 `agent_metric_snapshots` 周期快照 |
| **Replay** | ❌ 低 | 凭 `action_records`（`intent` + `steps` + `result`）可复现「做了什么」；但 Flag on 时 ①steps 缺 `tool_id` / `payload` ②`plan_step` 缺失 ③`run_id` 错配 → **无法精确复现「哪一步 / 哪个工具 / 写没写世界」** |
| **Debug** | ✅ 中高 | 4 端点（清单 / 详情含 schedule / 到期队列 / 指标）+ 双重门控；缺点：`user_id` 缺省时 `list_records("")` 静默返回空（无全局视图）、无分页游标、无 steps 级可视化 |

---

## 7. Functional Review（功能完整性）

### 7.1 必须验证的四段

| 验证项 | 结论 | 判据 / 证据 | 缺口 |
|---|---|---|---|
| **Planning → Action 是否正常连接** | ⚠️ 连接成立，语义漂移 | `executor_bridge.py:265-294` 经 `ActionManager.create(source="plan")` + `execute`，PlanStep 与 Action 1:1（`tests/v26/test_review_fixes.py:76-112` 断言不新增第二条记录） | ①`plan_step` 未回填（溯源断）②`source` 由 `autonomy` 改 `plan` → 关系信号丢失 + 自治额度不计（§2.3/A3、§3.2/M5） |
| **Action → Execution 是否正常执行** | ✅ 执行成立 | 分派三路 + 内部/工具路径可跑通（`test_task004_executor.py`、`test_acceptance.py::TestFunctionalAcceptance::test_execute_reuses_record`） | 结果形态有损；`external` 占位；多步未放开 |
| **Execution → Result 是否生成结果** | ⚠️ 生成但信息丢失 | 五执行路径均产非空 `ActionResult`（`executor.py:206-226`），`test_task009_validation.py:167-181` G5 断言 | 丢 `output` / `observations` / `effects` → 下游拿不到 `world_event_id` / `memory_id` / 工具观测 |
| **Result → Feedback 是否影响后续系统** | ❌ 实质未闭环 | 反馈投影仅写入 `record.result`；`feedback_kinds` / `temporary_execution` 零消费者；`apply_result_feedback` 未接线 | Autonomy 的 `action_facts`（`action_engine.py:972-1013`）、Reflection 工具证据窗（`evidence.py:806-839`）、Planning 的 `PlanStepOutcome` 回写（`integration.to_plan_step_outcome` 生产零调用）**都仍走旧通道或读不到数据** |

### 7.2 完成度评分

```text
Action Value Object（值对象 + 状态机 + 分派映射）   : 92%
Persistence / Migration（表 + 仓储 + 迁移）         : 90%
ActionManager（生命周期七能力）                     : 80%   （execute 无锁声明 / 可绕过退避）
ActionExecutor（三路分派 + 结果捕获）               : 65%   （结果有损 / 外部占位 / 多步绑定写死）
Scheduler（延迟 / 定时 / 优先级 / 队列）            : 40%   （无到期执行消费端 + 无重试字段 + trigger 滞留）
Result System（契约 + 双写）                        : 60%   （契约函数生产零调用 / 双写键位置错位）
Feedback System（四通道 + 三面投影）                : 30%   （写而不读 / 统一入口未接线）
Recovery（孤儿 / 调度丢失 / 幂等重放）              : 20%   （仅重试数学 + 计划过期）
Observability（日志 + 指标 + 调试端点）             : 70%   （内存聚合 / N+1 / 无全局视图）
Flag Matrix（6 闸串行链 + off 逐字节一致）          : 75%   （2 个死闸 / 未登记 .env / ②链未强制）
----------------------------------------------------------
V2.6.0 综合功能完成度                              : ≈ 58%
```

> **口径说明**：百分比 = 「可判定 + 有自动化证据 + 生产路径真实生效」三者同时满足的比例；仅「有代码 + 有单测」不记为完成（这是本次审计与前份 `acceptance-report.md` 的主要分歧点）。

### 7.3 未兑现承诺清单（架构 / 任务书 → 代码）

| # | 承诺 | 出处 | 现状 |
|---|---|---|---|
| 1 | 多步执行（放开 `action_plan_max_steps` > 1，关闭 B2） | `architecture.md:450-455`、`tasks.md:131` | ❌ 仍为 1（`core/settings/action.py:16`），Flag 无消费方 |
| 2 | 状态恢复：孤儿 `RUNNING` 超时置 `FAILED` | `architecture.md:900-907` §11.4 | ❌ 未实现（`action_engine.py:1059-1072` 只处理 `planned`）；`regression-checklist.md:29` 引用的 `test_v26_scenario_d_recovery.py` 不存在 |
| 3 | 旧读键退役「双写一个版本窗口」 | `architecture.md:976` R2、`regression-checklist.md:138` | ⚠️ 双写只写 `record.result` 顶层，下游读的 `steps[].result.payload` 在 Flag on 时缺失 → 窗口失效 |
| 4 | 反馈统一入口 `apply_result_feedback` | `tasks.md:317-319`（TASK-007） | ❌ 生产未接线 |
| 5 | 七日志事件落 `loop_runs.steps` | `architecture.md:915-925` | ⚠️ 部分：`Action Created/Scheduled` 用 `logger.info`，未落 `loop_runs.steps`（无统一事件落库） |
| 6 | 五指标（执行次数 / 成功率 / 平均耗时 / 重试率 / 取消率） | `architecture.md:929-935` | ⚠️ 仅 debug 端点内存聚合；平均耗时用 `executed_at - created_at`（`action_execution.py:86-87`），非真实执行耗时 |
| 7 | 「明天早上提醒我学习」端到端可复现（Plan → Action → Schedule → 到期执行 → 反馈） | `tasks/TASK-005.md:290` | ❌ 只到「Schedule + 到期队列查询」（`test_task005_scheduler.py:129-144`），**无执行环节** |
| 8 | 零新建 Agent / Memory / Session / Event 系统 | `architecture.md:11` | ✅ 达成 |
| 9 | 世界唯一写面 / 记忆 R1~R8 零豁免 / 工具五段短路 | `architecture.md:11` | ✅ 达成（静态断言留痕） |
| 10 | Flag 全 off 时逐字节一致 | `architecture.md:873` | ✅ 基本达成（E2：v9 + v24 98 passed；但 E3 的 1 例失败为环境性，E4 两例为既有缺陷） |

---

## 8. Testing Review

### 8.1 已有测试（`apps/backend/tests/v26/`，184 例）

| 文件 | 例数 | 覆盖面 | 质量评价 |
|---|---|---|---|
| `test_task001_action_core_model.py` | 47 | 值对象 / 值集零变化 / 映射全覆盖 / 状态机 | ✅ 强（含序列化往返 + 非法迁移） |
| `test_task002_persistence.py` | 14+ | 表 / 加列 / source 五值 / 5 个 schedule 仓储函数 | ✅ 强（含 CHECK 负例） |
| `test_task003_manager.py` | 22 | 七能力 + 不可变字段 + 边界 | ✅ 较好（部分为源码字符串断言 `:142-150`） |
| `test_task004_executor.py` | ~14 | 九类型分派 / 三路 / 异常归一 / 超时 | ️ 含弱断言（`:141-148`）与源码断言（`:168-175`） |
| `test_task005_scheduler.py` | 14 | 三种 when / 排序确定性 / 队列 / 唯一约束 / 挂载 | ⚠️ **缺「到期执行」断言**（只验查询与登记） |
| `test_task006_result.py` | ~18 | 契约字段 / 四类结果 / 双写 / 投影 | ⚠️ 投影函数测的是**未被生产调用**的那份实现 |
| `test_task007_integration.py` | ~10 | 计划桥 / 四通道路由 / 反馈 legacy vs v26 | ⚠️ 测的是 `apply_result_feedback`（死代码） |
| `test_task008_api.py` | 7 | 4 端点 + 门控 | ✅ 基本 |
| `test_task009_validation.py` | ~30 | 生命周期 / 失败场景 / Flag 矩阵 / 六原则 / 六风险 / 五遗留 | ⚠️ 多为「文本/常量断言」，缺行为级端到端 |
| `test_acceptance.py` | 23 | 功能 / 数据 / 错误 / 回归 | ✅ 较好；`:49` 兜底态含 `executing` → 说明「未终态」被容忍 |
| `test_review_fixes.py` | ~12 | Code Review 修复回归（主路径接线 / 状态机 / 桥 Flag on） | ✅ 有价值 |

### 8.2 缺失测试 / 高风险模块

| # | 缺失 / 薄弱 | 风险 | 建议用例（可直接落地） |
|---|---|---|---|
| T1 | **Flag on 主路径的 `steps[].result` 形态契约**（`payload` / `tool_id` / `observations` / `duration_ms` 必须存在） | 最高（F1 根因） | `test_v26_step_result_contract.py`：Flag on 跑 `create_reminder`（internal）与 `query_environment`（tool），断言 steps 同时含新键与 `payload` 旧键、`record.result.observations.world_event_id` 存在 |
| T2 | **outbox 模式端到端世界写**（Flag on + `v2_action_outbox_enabled`） | 最高（R1） | 断言 `world_ops` 非空、消费后 `world_events` 恰 1 行 |
| T3 | **调度到期执行**（消费端落地后） | 高（F2） | `scheduled_at < now` → 跑维护步 → Action 达终态且 `action_schedules.status == "executed"` |
| T4 | **trigger 行生命周期**（无滞留 / 无复活） | 高（A4） | 到期 → 执行 → 行达 `done`；再跑一轮断言不复活、`_due_trigger_present` 为 False |
| T5 | **孤儿 `executing` 恢复** | 高（F6） | 造 `status="executing"` 且 `updated_at` 超阈值 → 跑维护步 → 置 `failed` 且可 retry |
| T6 | **`partial` 结果映射** | 高（M4） | 注入 `partial` → 断言记录不滞留 `executing` |
| T7 | **关系信号与自治额度口径**（source 语义） | 高（F4） | Flag on 计划步 `create_reminder` succeeded → 断言 `user_care/weak` 事件落库；断言自治日计数口径（含或明确不含） |
| T8 | **Flag 矩阵真组合** | 中（F8） | 32 组合参数化，断言行为与 Flag 表一致（当前仅默认值断言） |
| T9 | **多步**（放开后） | 中 | 3 步计划 → 顺序执行、步级 tool 绑定、`partial` 语义 |
| T10 | **计划↔行动溯源** | 中 | 由 `action_records` 反查 `goal_id` + `plan_step`（当前 `plan_step` 为空） |
| T11 | **`Manager.execute` 退避窗口** | 中 | `executing` + `next_retry_at` 未到 → 拒绝立即执行 |
| T12 | **静态扫描测试环境鲁棒性** | 低-中（E3） | `test_plan012 ... q10` 排除 `node_modules` / `dist` |

### 8.3 测试工程质量问题

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| Q1 | **源码字符串断言**（断言文本而非行为） | `test_task003_manager.py:142-150`、`test_task004_executor.py:168-175`、`test_task009_validation.py:143-165, 316-320` | 保留少量架构红线断言；行为断言下沉执行路径，避免「改名即红 / 不改名即绿」的假安全 |
| Q2 | **弱断言 / 兜底式断言** | `test_task004_executor.py:141-148`、`test_acceptance.py:49` | 收敛为精确期望态；把「未终态」变成失败信号 |
| Q3 | **测死代码不测活代码** | `test_task006_result.py`（`from_*` 投影）、`test_task007_integration.py:109-133` | 先接线再断言，或在文档显式承认未接线 |
| Q4 | **文档引用不存在的测试文件** | `regression-checklist.md:26-29, 73-81` | 与真实文件名对齐（建议「路径 + 断言名」双锚点） |
| Q5 | **已知失败长期挂账** | E4：v23 day-cycle marker、v21 低能量抑制（`acceptance-report.md:69-70` I1/I2） | 建独立缺陷条目 + 归属版本，不阻塞但必须可追踪 |
| Q6 | **缺四类场景端到端自动化（A/B/C/D）** | `regression-checklist.md:26-29` 四场景均无对应实现文件 | 按 §8.2 T1~T7 补齐，即等价于 A/B/C/D |

---

## 9. Performance Review

### 9.1 数据增长

| 面 | 增长来源 | 风险 | 建议 |
|---|---|---|---|
| `action_records` | 每次对话 / 自治 / 计划步各 1 行（V2.6 新增 `plan` 来源） | ️ 线性增长，有 `retain_cleanup` 兜底 | 保留策略按 `source` / `action_type` 分级 |
| `action_schedules` | 每次 `schedule()` 1 行；`executed` / `cancelled` 不回收 | ⚠️ 中 | 定义保留窗口 + 归档（与 `action_records` 对齐） |
| `trigger_registry` | 每 tick 复登记 `action_schedule:{id}`（同键 upsert，行数不涨但**状态永非终态**） | ❌ 高（复活 + 空转） | 执行接入选尸 + 终态收口（T4） |
| `outbox_events` | Flag on + outbox 模式每次执行 1 行 | ✅ 有消费器与死信 | 修复 F1（当前 `world_ops` 恒空 → 行被消费但零意义） |
| JSON 列（`steps` / `result`） | 富形态含完整工具观测与去敏参数 | ⚠️ 单行膨胀 | 延续 `redact_params` / 字段截断 / `bound_extra` 纪律 |

### 9.2 查询压力

| # | 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P1 | **debug 指标 6 次 `list_by_status(limit=500)`**（内存过滤，全量拉 JSON） | `api/v1/action_execution.py:73-87` | 每请求最多 3000 行反序列化；无 status 前导索引 | 改 DB 聚合（`COUNT` / `AVG` + `GROUP BY`）或补 `(status, created_at)` 索引 |
| P2 | **`scheduler.due_actions` N+1** | `scheduler.py:118-140`（每条 schedule 一次 `get_record`） | 队列增大后线性 IO | 单查询 JOIN 或批量 `in_`（acceptance-report I3 已记录，仍未修） |
| P3 | **`list_retryable` 无索引** | `action_repository.py:147-157` | 维护步每次全表扫描 | 加 `(status, next_retry_at)` 索引 |
| P4 | **`_autonomy_action_today` 拉 200 行再 Python 计数** | `autonomy_engine.py:368-375` | 每自治周期一次 | 改 `COUNT(*)` 聚合 + `(user_id, source, created_at)` 索引 |
| P5 | **`collect_facts` 拉 50 行再过滤** | `action_engine.py:972-1013` | 每决策周期一次 | 有界可接受，可下沉为聚合查询 |
| P6 | **`action_schedules` 到期排序不吃索引** | §6.2 | 队列增长后排序成本上升 | 调整索引列序 |

### 9.3 执行队列与并发

| # | 问题 | 说明 | 建议 |
|---|---|---|---|
| C1 | **无队列消费端** → 无并发模型 | 调度器只登记；执行依赖「对话/自治周期内同步执行」 | 引入 Action Worker（挂既有循环，拉 `action_schedules` + `FOR UPDATE SKIP LOCKED` / CAS 认领） |
| C2 | **无「认领」语义（非原子）** | `scheduler.py:167-172` 仅以 `item.status == "scheduled"` 判断后覆写 `due` | 参照 `trigger_registry.claim_due_followups` / `outbox_repository` 的 CAS 写法 |
| C3 | **执行不持锁的契约缺口** | `Manager.execute` 无 per-user 写锁，当前靠调用方（`life_loop.py:231` / `post_process`）持锁 | Manager 内置锁或在契约层显式声明前置条件 |
| C4 | **同步执行阻塞风险** | `execute_plan` 全程 `await`（默认超时 10s）跑在回复链路内 | 维持「工具失败永不阻塞回复」纪律；长任务走异步（V2.7） |
| C5 | **失败 schedule 无退避** | 无 `attempt_count` / `cooldown`，失败会每 tick 重试 | 表扩展 + 退避（M3） |

### 9.4 优化建议（按收益排序）

1. **P0 修复即最大性能修复**：修好 `steps[].result` 形态与执行消费端后，outbox 无效写与重复自治 tick 立即消失——当前 A4 的空转是**持续性 LLM 成本**，不是理论风险。
2. 指标下沉 DB（P1）+ 索引补齐（P3/P6）：debug 面板与维护步从 O(N) 降到接近 O(log N)。
3. 批量读替代 N+1（P2/P4）。
4. `action_schedules` 增 `attempt_count` / `cooldown_until` 后，到期扫描可加限流与退避，避免失败 schedule 空转。

---

## 10. Technical Debt

| # | 问题 | 位置 | 影响 | 优先级 |
|---|---|---|---|---|
| D01 | V2.6 主路径 `steps[].result` 丢 `payload` / `tool_id` / `observations` / `duration_ms` | `application/action_engine.py:365-374`；`services/action/executor.py:80-122` | outbox 世界写为空（提醒静默失效）、工具证据窗不可用、Replay/Debug 失真、V2.7 经验数据污染 | **P0** |
| D02 | 调度器无到期执行消费端 | `services/action/scheduler.py:148-190` | 「延迟 / 定时执行」功能不可用（B4 只关一半） | **P0** |
| D03 | 调度 trigger 行滞留 + 终态复活 → 重复自治 tick | `scheduler.py:176-187`；`trigger_registry_repository.py:94-96`；`life_loop.py:122-127` | 持续性 LLM 成本泄漏、表噪声 | **P0** |
| D04 | Planning 桥 Flag on 时 `source="plan"`，关系映射无该行、自治额度不计数 | `executor_bridge.py:276-284`；`character/asuna/action.py:164-171`；`autonomy_engine.py:368-375` | 关系信号静默丢失 + 额度被绕过（行为漂移） | **P0** |
| D05 | 反馈「统一入口」未接线 + 反馈投影零消费者 | `integration.py:111-151`；`action_engine.py:749-765` | 反馈闭环名存实亡；契约与运行时分叉 | **P0** |
| D06 | 无孤儿 `executing` 恢复；`partial` 无终态映射 | `action_engine.py:1059-1072, 383-387` | 记录可能永久滞留非终态；`count_active` 虚高、闸门误判 `quota_exceeded` | **P0** |
| D07 | 旧读键「双写窗口」位置错位（写 `record.result` 顶层，读 `steps[].result.payload`） | `models/action.py:246-255` vs `services/tool/normalizer.py:117` | 兼容承诺失效；下游脆断 | **P0** |
| D08 | 死 Flag：`v26_action_abstraction_enabled` / `v26_action_multistep_enabled` 无消费方 | `core/settings/action_execution.py:14,16` | Flag 表与实现不符，运维误判 | **P1** |
| D09 | 多步执行未交付（`action_plan_max_steps=1`；工具绑定恒第 0 步、`index=0` 写死） | `core/settings/action.py:16`；`action_engine.py:312-321, 367` | B2 未关闭；V2.5 遗留 Q1 未兑现 | **P1** |
| D10 | `Action.run_id = session_id` 语义错配；`plan_step` 无列且桥未回填 | `manager.py:56-58`；`action_engine.py:362`；`executor_bridge.py:276-284` | 溯源链断裂（Run / PlanStep 级审计不可用） | **P1** |
| D11 | 结果归一三份实现（活的有损 / 死的富），生产用了错的那份 | `executor.py` vs `services/action/result.py:38-164` | 维护分叉；修一处不生效 | **P1** |
| D12 | 状态机非唯一写面（多处直接赋值 `status`） | `action_engine.py:202, 554, 835`；`api/v1/action.py:71-75` | 迁移语义漂移；审计不可判定 | **P1** |
| D13 | `Manager.execute` 可绕过 `next_retry_at` 退避窗口 | `manager.py:167-181`；`action_engine.py:403-411` | 重复执行 / 重复外部调用风险 | **P1** |
| D14 | services 层反向依赖 application 层（分层倒置） | `manager.py:169`、`integration.py:113`、`executor_bridge.py:63` | 可复用性差、循环依赖风险 | **P1** |
| D15 | 文档-代码追踪断裂（回归清单引用不存在的测试文件；上线前待办未勾选；映射表键名漂移） | `regression-checklist.md:26-29, 73-81, 136-139`；`architecture.md:371-379` | 验收不可复核；「已交付」口径失真 | **P1** |
| D16 | v26 Flag 未登记 `.env.example`；「总闸 ⇒ `action_enabled`」链未在任何处强制 | `.env.example`；`core/settings/enablement.py:120-245` | 运维配置错误只能表现为「行为不变」 | **P1** |
| D17 | 指标内存聚合 + 多查询；`due_actions` N+1；缺 `(status, next_retry_at)` 索引 | `api/v1/action_execution.py:73-87`；`scheduler.py:118-140`；`action_repository.py:147-157` | debug 面慢查询；维护步全表扫描 | **P2** |
| D18 | `action_schedules` 无清理/归档；索引列序对优先级排序不友好；`claim` 非原子 | `0047:123-127`；`scheduler.py:167-172` | 多进程双认领；数据无界 | **P2** |
| D19 | 测试以源码字符串断言 + 弱断言为主；静态扫描读 `node_modules`（环境脆弱） | `test_task003_manager.py:142-150` 等；E3 | 假安全、CI 噪声 | **P2** |
| D20 | 单角色硬编码（映射表在值对象层、`character_id="asuna"` 默认） | `models/action.py:51-61, 312` | 多角色成本集中在核心层 | **P2** |
| D21 | 隐式容错链（`_append_effect` 依赖 pydantic `extra=ignore`；`model_validate` 失败静默置 `None`） | `action_engine.py:701-704`；`manager.py:41-42` | 未来收紧校验即崩 | **P2** |
| D22 | 七日志事件未落 `loop_runs.steps`（仅 `logger.info`） | `manager.py:108-110`；`scheduler.py:100-106` | 生命周期事件不可查询 / 不可回放 | **P2** |

---

### 10.1 债务分布

| 优先级 | 数量 | 集中区域 |
|---|---|---|
| **P0** | 7 | 执行结果形态、调度消费、来源语义、反馈接线、恢复闭环 |
| **P1** | 9 | 契约收敛、Flag 治理、溯源字段、状态机权威、分层 |
| **P2** | 6 | 性能索引、生命周期、测试策略、多角色就绪、可观测性 |

---

## 11. Refactoring Recommendations

> 原则：**先保真，再补链，最后收敛**。P0 全部完成前，**不要打开 `v26_action_execution_enabled`**（当前默认 off，线上安全）；P0 完成后才进入 V2.7 的数据建设。

### 11.1 P0 必须修复（影响系统稳定性 / 数据正确性）

| # | 任务 | 具体动作 | 验收判据 |
|---|---|---|---|
| **P0-1** | **恢复 `steps[].result` 全形态（修 D01/D07）** | `_execute_plan_via_action_executor` 统一产出「`ActionResult` 新契约 + 旧读键」双形态：internal 路径改用 `result_service.from_capability_result`（保留 `output` / `observations` / `metadata.usage`）；tool 路径改用 `result_service.from_tool_execution`（保留 `effects` / `observations` / `duration_ms` / `tool_id`）；步骤字典补 `tool_id` / `permission` / `validation` / `duration_ms`；`steps[].result.payload` 保留 `deferred_world_op` 等旧读键 | §8.2 T1 + T2 绿；`_integrate_via_outbox` 的 `world_ops` 非空；`evidence._window_facts` 能取到 `tool_id` |
| **P0-2** | **接线调度执行消费端（修 D02）** | 新增 Action 执行维护步（挂 `life_loop` 既有维护序列尾部或独立 worker）：`list_due_schedules` → **原子认领（CAS：`scheduled`/`due` → `due`/`executing`）** → `ActionManager.execute(action_id)` → 终态则 `mark_schedule_executed`；失败按 `failure_kind` 退避；`trigger_registry` 行同步收口 `done` | §8.2 T3 + T4 绿；「明天早上提醒我学习」端到端（Plan → Schedule → 执行 → 世界事件 → 反馈）自动化可跑 |
| **P0-3** | **调度与触发一致性收口（修 D03）** | `register` 对「已终结的一次性 `action_schedule`」不再复活（按 `trigger_type` + payload `kind` 判定语义）；`step_action_schedule` 仅对 `scheduled` 且未执行的 Action 登记；执行完成后 `mark_schedule_executed` + trigger `done` | 连续两轮维护步后 `_due_trigger_present` 为 False |
| **P0-4** | **统一来源语义（修 D04）** | 二选一裁决并落文档：①`source="plan"` 正式化 → 补 `ACTION_RELATIONSHIP_MAP` 的 `plan` 行、`_autonomy_action_today` 口径扩为 `source in ("autonomy","plan")`；②桥沿用 `PLAN_STEP_ACTION_SOURCE("autonomy")`，`plan` 仅作辅助 `origin` 字段 | §8.2 T7 绿；关系事件与额度计数符合文档 |
| **P0-5** | **反馈闭环真正闭合（修 D05）** | `integrate_result` 改为调用 `integration.apply_result_feedback`（唯一入口）并删除内联分支；为三面反馈定义**消费者**：Autonomy `collect_facts` 读反馈投影、Reflection 增加执行结果证据窗、Planning 经 `integration.to_plan_step_outcome` 回写 | `feedback_kinds` / `temporary_execution` 至少各 1 处生产消费者；`apply_result_feedback` 进主路径（静态断言守护） |
| **P0-6** | **状态恢复与终态闭环（修 D06）** | `_expire_planned` 同址扩展：扫描 `status="executing"` 且 `executed_at/updated_at` 超阈值（新设置 `ACTION_EXECUTING_TIMEOUT_MINUTES`）→ 置 `failed` + `failure_kind=timeout`（可选退避）；`partial` → 记录态映射裁决并写回 `architecture §6.4` | §8.2 T5 + T6 绿；不存在「永久 `executing`」路径 |
| **P0-7** | **双写键位置对齐（并入 P0-1）** | 在 `steps[].result` 内落旧读键（`world_event_id` / `memory_id` / `payload`）以对齐 `normalizer.py:117` 既有契约；或把全部旧读者迁到新键后删除旧键（二选一并冻结） | 旧读者（outbox / 工具证据窗 / `executor_bridge._result_kind`）在 Flag on 下全部可工作 |

### 11.2 P1 建议优化（影响开发效率 / 演进成本）

| # | 任务 | 动作 | 收益 |
|---|---|---|---|
| P1-1 | 结果归一收敛为一份 | `result.py` 三投影函数成为**唯一实现**，删除 `executor.py` 内两个 `_normalize_*` | 消除「修一处不生效」 |
| P1-2 | 多步交付或明确回退 | 要么放开 `action_plan_max_steps` + 步级绑定（`index` 透传 + 按步取 `plan.steps`）+ `partial` 语义；要么把 `v26_action_multistep_enabled` 标 RESERVED 并从 Flag 表移除（沿用 `v23 RESERVED` 先例） | 消除死 Flag 与文档-实现不符 |
| P1-3 | Flag 治理 | `v26_*` 登记 `.env.example`；「总闸 ⇒ `action_enabled`」等链纳入 `enablement_violations`；`v26_action_abstraction_enabled` 补用途或删除 | 运维可发现、启动即 fail-fast |
| P1-4 | 溯源字段修正 | `Action.run_id` 与 `session_id` 解耦（M1）；`plan_step` 落列 + 桥回填（M2） | Replay / 计划推进可精确追溯 |
| P1-5 | 状态机唯一权威 | 所有 `record.status = ...` 改经 `transition_action`；补静态断言（禁止裸赋值） | 迁移语义可判定 |
| P1-6 | 退避窗口守卫 | `Manager.execute` 校验 `next_retry_at`（未到则拒绝 / 返回 hold） | 防重复外部调用 |
| P1-7 | 分层收敛 | `action_engine`（993 行）拆为 `action_orchestrator` / `action_integrator` / `action_recovery`；services 层经 Protocol 端口回调，去掉 services → application 的 import | 降复杂度、消除分层倒置 |
| P1-8 | 文档-代码对齐 | 回归清单测试文件名对齐；任务表状态/commit 回填；`architecture.md:371-379` 映射表与代码一致；`regression-checklist §9` 勾选 | 验收可复核 |

### 11.3 P2 长期优化（架构演进方向）

| # | 方向 | 内容 |
|---|---|---|
| P2-1 | **Action Queue / Worker 化** | 以 `action_schedules` 为 SoT 引入消费者 + `SKIP LOCKED` 认领 + 限流 + 退避；「同步执行」限定为前台查询类 Action |
| P2-2 | **可观测性升级** | 指标落 DB（或复用 `agent_metric_snapshots`）；七事件落 `loop_runs.steps`；debug 端点补分页与 steps 级视图 |
| P2-3 | **多角色就绪** | `ACTION_EXECUTION_MAP` / 能力表 / 记忆模板 / 关系映射下沉到角色注册表；`character_id` 变必填 |
| P2-4 | **External Adapter 协议** | 定义 `ToolAdapter`（`execute` + 权限作用域 + 超时/重试策略 + 幂等声明），对接 V2.7 飞书 / 日历 / 搜索 |
| P2-5 | **测试策略升级** | 以「行为契约 + 场景快照」替代源码字符串断言；补 Replay（同输入同输出）与状态机属性测试 |
| P2-6 | **隐式容错显式化** | `_append_effect` 改显式字段透传；`model_validate` 失败可观测告警而非静默 `None` |

---

## 12. Future Architecture Compatibility

### 12.1 V2.7 Memory Evolution（Experience Memory / Reflection / Memory Consolidation）

| V2.7 依赖的前置数据 | 当前状态 | 结论 |
|---|---|---|
| 执行事实：`action_records.steps[].result`（工具 / 观测 / 效果） | ❌ Flag on 时缺 `tool_id` / `observations` / `effects` | **必须先修 D01**，否则经验记忆建立在残缺事实上 |
| 执行效果引用：`world_event_id` / `memory_id` | ❌ Flag on 时不在 `steps[].result`，`record.result.effects` 为空 | 经验与「世界/记忆副作用」不可关联 |
| 工具效能证据窗（TOOL-009 三窗） | ❌ Flag on 时 `_window_facts` 取不到 `tool_id` → 窗口为空 | 记忆巩固（consolidation）缺少证据来源 |
| 计划↔行动溯源（`goal_id` + `plan_step`） | ⚠️ `plan_step` 缺失 | 经验无法归因到「为哪个目标做了什么」 |
| 执行时长 / 成功率等质量信号 | ⚠️ `duration_ms` 丢失、指标仅 debug 面 | 经验权重（importance/confidence）缺少量化依据 |
| Reflection 触发（执行失败 → Insight） | ⚠️ 依赖 `record.status` 可用；但 `partial`/孤儿态会污染 | 需先修 D06 |
| 记忆投递（`memory_bridge`） | ✅ 参数模板路径可用（不依赖 effects） | 可直接复用 |

**结论**：V2.7 的「原始素材」= Action 执行事实；**当前素材是残缺的**。V2.7 开始前的必做项 = §11.1 的 P0-1 / P0-5 / P0-6（另加 P0-4 的关系信号一致性）。

### 12.2 V2.8 Self Improvement（Behavior Adjustment / Personality Evolution）

| V2.8 依赖 | 当前状态 | 需要提前调整 |
|---|---|---|
| 行为调整的证据链（Insight → 行为参数） | ⚠️ Insight 证据窗依赖执行事实与工具窗 | 同 12.1，先补齐事实面 |
| 人格演化输入（情绪 / 关系 / 经验） | ✅ 情绪、关系、经验通道齐备（V2.2 / V8.5 / V2.0） | 无阻塞 |
| 「行为是否有效」的闭环判定 | ❌ 反馈投影无消费者 | 必须完成 P0-5（否则无法判定「这次行为是否改善了结果」） |
| 行为变更的可回滚审计 | ✅ `evolution_ledger` + `agent_metric_snapshots` 既有 | 建议把 Action 指标纳入快照（P2-2） |
| 多角色人格演化 | ❌ 单角色硬编码 | 若 V2.8 前要多角色，需先做 P2-3 |

**结论**：V2.8 的架构通道已存在，但**判定依据（反馈闭环）失效**；不修 P0-5，V2.8 只能做「无依据的自我调整」，属于高风险方向。

### 12.3 必须提前调整的地方（V2.7 前）

| # | 调整 | 原因 | 关联 |
|---|---|---|---|
| 1 | 冻结 `steps[].result` **单一 schema**（新契约 + 旧读键并存，Flag 无关） | 避免「同列两态」继续扩散到 V2.7 数据 | D01 / D07 / P0-1 |
| 2 | 冻结 `source` 语义与 `ACTION_RELATIONSHIP_MAP` 全覆盖 | 来源扩张是常态（`plan` / `event_driven`），映射缺失即静默丢信号 | D04 / P0-4 |
| 3 | 冻结 `ActionResult` 为**唯一对外反馈契约**并接入消费者 | V2.7/V2.8 都靠它判定行为效果 | D05 / P0-5 |
| 4 | 引入执行态超时出口（孤儿恢复） | 数据质量与闸门计数正确性前提 | D06 / P0-6 |
| 5 | 溯源字段补齐（`run_id` / `plan_step`） | Replay、经验归因、评估（V2.7 评估面） | D10 / P1-4 |
| 6 | 调度执行消费端上线 + 一致性收口 | 「主动行为 / 定时提醒」是飞书机器人主动能力的底座 | D02 / D03 / P0-2~3 |

---

## 13. Priority Plan（后续执行计划）

### 13.1 推荐执行顺序

```text
V2.6.0 完成（当前）
    ↓
【Audit】本报告（只读审查）
    ↓
【Refactor Task 建立】按 §10 债务表建条目（D01~D22 → 任务卡）
    ↓
【P0 批次】（必须，禁止开 Flag）
    P0-1 结果全形态（D01/D07/D11 部分）
    P0-2 调度执行消费端（D02）
    P0-3 调度/触发一致性（D03）
    P0-4 来源语义统一（D04/M5）
    P0-5 反馈闭环接线（D05）
    P0-6 恢复与终态（D06/M4）
    ↓ 每项以 §8.2 对应测试（T1~T7）为验收
【重新 Audit（P0 复核）】——Flag on 灰度前必做
    ↓
【P1 批次】（工程收敛，可与 V2.7 设计并行）
    P1-1 归一份 / P1-2 多步裁决 / P1-3 Flag 治理 / P1-4 溯源
    P1-5 状态机权威 / P1-6 退避守卫 / P1-7 分层收敛 / P1-8 文档对齐
    ↓
【Flag on 灰度】v26 全闸 on + 真实模型人工回归（regression-checklist §2）
    ↓
V2.7 Memory Evolution 立项（数据基线已可信）
    ↓
【P2 批次】（与 V2.7/V2.8 并行）
    P2-1 Queue/Worker 化 / P2-2 可观测性 / P2-3 多角色 / P2-4 Adapter / P2-5 测试策略 / P2-6 隐式容错
```

### 13.2 批次门禁（Definition of Done）

| 批次 | 门禁 |
|---|---|
| P0 | ①§8.2 T1~T7 全绿 ②`tests/v26` + `tests/v9` + `tests/v24/test_tool003` + `tests/v25` 全绿（含修复 E3 环境脆弱用例）③Flag off 面逐字节回归 ④本报告 P0 项复核通过 |
| P1 | ①静态断言（状态机权威 / 分层 / 契约唯一入口）落地 ②文档与代码一致 ③无死 Flag |
| Flag on 灰度 | ①真实 PostgreSQL 迁移 0047 验证（acceptance I5）②真实模型人工回归 A~D（acceptance I6）③debug 面板指标与真实一致 |
| V2.7 立项 | P0 + P1 完成，且「执行事实完整性」有自动化守护 |

### 13.3 工时与风险提示（估计）

| 批次 | 相对工作量 | 主要风险 |
|---|---|---|
| P0 | 大（执行层 + 调度层 + 整合层三处改动，牵动 v9/v24/v25 回归） | 改动面广 → 必须靠 Flag off 逐字节回归兜底 |
| P1 | 中 | 多步裁决涉及 V2.5 契约，需与规划域会签 |
| P2 | 中-大 | 多角色改造面最广，建议单独立项 |
| 重新 Audit | 小 | — |

---

## 14. Final Conclusion

### 14.1 当前版本成熟度

| 面向 | 判定 |
|---|---|
| **作为「设计交付」** | ✅ **合格**：值对象、状态机、映射表、Flag 范式、迁移纪律均达工程标准，文档化程度高（architecture 55KB + 9 个 Task Detail） |
| **作为「可上线能力」** |  **不合格**：Flag on 会静默丢执行事实（D01）、调度不执行（D02）、关系信号丢失（D04）、反馈不闭环（D05）、存在非终态滞留（D06） |
| **作为「V2.7 数据基线」** | ⚠️ **未就绪**：V2.7 需要的是「执行事实」，当前事实残缺 |
| **作为「Flag off 的线上版本」** | ✅ **安全**：6 闸默认 off（`.env` 未开）、off 面回归成立（E2：98 passed；E3/E4 为环境性/既有缺陷） |

**综合成熟度**：**5.5 / 10**——「骨架已成型、神经未接通」。

### 14.2 是否建议进入 V2.7

**建议：可进入 V2.7 的「设计与立项」，但不得进入 V2.7 的「数据依赖实现」阶段，直到 P0 完成。**

理由：V2.7（Experience Memory / Reflection / Consolidation）与 V2.8（Self Improvement）都直接消费 V2.6 产出的执行事实与反馈投影。若带着 D01/D05 进入 V2.7，会产出**结构性错误的历史数据**，且这些数据的修正成本随时间线性上升（本报告开头引述的判断成立）。

### 14.3 是否需要先重构

**需要，但不是「大重构」，而是「定向修复 + 契约收敛」：**

- **必须先做（P0）**：7 项定向修复，集中在 `action_engine.execute_plan`、`services/action/{executor,result,integration,scheduler}.py`、`executor_bridge._dispatch` 四处，**不触碰 V2.5 及更早的对外契约**。
- **可延后（P1/P2）**：993 行 `action_engine` 拆分、分层 Protocol 化、多角色就绪、Queue/Worker 化——这些是演进优化，不应阻塞 V2.7 数据基线修复。
- **不需要**：不推翻 Action 值对象与六态状态机（它们是本版本最扎实的部分），不需要新增表（除 `action_schedules` 的字段扩展），不需要改动世界/记忆/关系的写入红线。

### 14.4 推荐执行顺序（一句话版）

```text
建 Refactor 任务卡（D01~D07）
 → 修 P0-1（结果全形态）→ 修 P0-4（来源语义）→ 修 P0-5（反馈接线）
 → 修 P0-2/P0-3（调度执行与一致性）→ 修 P0-6（恢复与终态）
 → 补 T1~T7 自动化 → 重新 Audit（P0 复核）
 → P1 收敛（归一份 / 状态机权威 / 溯源 / Flag 治理 / 文档对齐）
 → Flag on 灰度（PG 迁移 + 真实模型 A~D 人工回归）
 → 进入 V2.7 Memory Evolution
```

### 14.5 一票否决项（Flag on 之前必须清零）

1. 不允许存在「报告成功但世界无副作用」的执行路径（D01 + D07）。
2. 不允许存在「永久非终态」的记录（D06）。
3. 不允许存在「产出但无消费者的反馈契约」（D05）。
4. 不允许「同一业务语义两种来源值」导致的静默信号丢失（D04）。
5. 不允许「文档宣称已交付但代码未实现」（D08/D09/D15）。

### 14.6 审计声明

- 本报告为**只读审查**结论，未修改任何业务代码、测试或迁移。
- 所有判定均附 `文件:行号` 证据；未能复现或存疑之处已标注（如 E3 的环境性失败）。
- 本报告可作为 V2.6.0 → V2.7.0 之间的**技术基线**：P0 复核通过后，建议在本文件末尾追加 `P0 复核结论` 与日期，形成闭环留痕。

---

## 附录 A：关键证据索引

| 主题 | 证据位置 |
|---|---|
| Action 值对象 / 状态机 | `app/models/action.py:15-61, 130-168, 225-276, 309-359` |
| 执行分派与有损归一 | `app/services/action/executor.py:70-122, 197-226` |
| 主路径步骤形态构造 | `app/application/action_engine.py:300-381` |
| 整合与反馈内联分支 | `app/application/action_engine.py:725-810` |
| 重试 / 过期 / 恢复缺口 | `app/application/action_engine.py:383-400, 1016-1072` |
| 调度器（登记不执行） | `app/services/action/scheduler.py:24-190` |
| 调度仓储（含 `list_due_schedules`） | `app/repositories/action_repository.py:270-341` |
| trigger 复活语义 | `app/repositories/trigger_registry_repository.py:53-99` |
| life_loop 挂载与 due 判定 | `app/application/life_loop.py:115-127, 280-286, 749-752` |
| 自治额度计数 | `app/application/autonomy_engine.py:368-375` |
| 计划桥 Flag on 分支 | `app/services/planning/executor_bridge.py:213-294` |
| 关系映射表（缺 `plan` 行） | `app/character/asuna/action.py:162-171` |
| 工具落库形态（outbox 依赖 payload） | `app/services/tool/normalizer.py:116-120` |
| 反思工具证据窗（依赖 tool_id / observations） | `app/services/reflection/evidence.py:806-839, 875-900` |
| 迁移 0047 | `migrations/versions/0047_action_schedules_priority.py:19-134` |
| Schema 与索引 | `app/core/db.py:660-720` |
| 调试端点与内存聚合 | `app/api/v1/action_execution.py:13-101` |
| Flag 定义与串行链 | `app/core/settings/action_execution.py:8-38`；`app/core/settings/enablement.py:120-245` |
| 契约冻结 | `app/services/action/contracts.py:8-89` |
| v26 测试 | `apps/backend/tests/v26/*.py`（11 文件 184 例） |
| 文档承诺 | `docs/version/v2.6.0/architecture.md:371-379, 450-486, 860-935, 971-992`；`tasks.md`；`acceptance-report.md`；`regression-checklist.md` |

## 附录 B：建议新增的回归用例清单（可直接建卡）

| 用例文件 | 覆盖 | 关联债务 |
|---|---|---|
| `tests/v26/test_v26_step_result_contract.py` | 主路径 steps/result 形态契约（新键 + 旧读键 + tool_id + observations + duration） | D01 / D07 / T1 |
| `tests/v26/test_v26_outbox_world_write.py` | Flag on + outbox：世界写端到端（`world_ops` 非空 → 消费后事件恰 1） | D01 / T2 |
| `tests/v26/test_v26_schedule_execution.py` | 到期执行：认领 → 执行 → `executed` → trigger `done` | D02 / D03 / T3 / T4 |
| `tests/v26/test_v26_source_semantics.py` | `plan` 来源的关系信号与自治额度口径 | D04 / T7 |
| `tests/v26/test_v26_feedback_consumers.py` | 反馈投影有真实消费者（Autonomy / Reflection / Planning） | D05 / P0-5 |
| `tests/v26/test_v26_recovery.py` | 孤儿 `executing` 超时 → `failed`；`partial` 不滞留 | D06 / T5 / T6 |
| `tests/v26/test_v26_flag_matrix_combinations.py` | 6 闸组合矩阵行为一致（替代默认值断言） | D08 / T8 |
| `tests/v26/test_v26_traceability.py` | `run_id` / `plan_step` / `goal_id` 溯源可反查 | D10 / T10 |

---

**报告结束**（V2.6.0 System Audit / 只读审查 / 未修改任何代码）
