# PLAN-012 Task Detail — Testing & Validation

> 上游：[../architecture.md](../architecture.md) §9.6（版本验收 Gate）、§9.7（遗留问题登记）、§2.3（十条边界不变量）、§6.1 ~ §6.6（流程）、§7.10（Flag 设计）、§7.11（迁移与回滚）；[../tasks.md](../tasks.md) PLAN-012
> 状态：设计稿（未实现）
> 范围红线：**验收性质任务**——不复用本任务引入新功能；只交付场景集、Flag 矩阵、`regression-checklist.md` 与 Gate 判定；零迁移断言必须成立。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-012 |
| **Task Name** | Testing & Validation |
| **Priority** | P0 |
| **Dependencies** | PLAN-001 ~ PLAN-011 |
| **Phase** | Phase 4 接口与验收 |
| **建议提交** | `docs: V2.5.0 Planning System 回归清单与验收判定` |

## 1.1 Goal

交付版本级验收，作为 V2.5.0 Planning System 的**发布判据**：

1. **四类端到端场景集**：单目标规划 / 多步骤规划 / Tool 调用流程 / 失败恢复。
2. **Flag 矩阵一致性测试**：13 个 `v25_*` Flag 的组合矩阵与 §7.10 串行链校验逐条对照；总闸 off 时逐字节一致。
3. **交付 `docs/version/v2.5.0/planning-system/regression-checklist.md`**。
4. **§9.6 全部 Gate 的可执行判定**：G-COMPAT / G-PLAN / G-DECOMPOSE / G-BIND / G-EXEC / G-RETRY / G-WORLD / G-MEMORY / G-REFLECT / G-BOUNDARY / G-ZERO-MIGRATION。
5. **§9.7 遗留问题收口**：Q1 ~ Q10 逐条核对留痕，无悬空项。
6. **兼容窗口兑现**：V9 旧读键双写断言通过。
7. **边界不变量核对**：§2.3 十条红线逐条核对。

## 1.2 Scope

**包含**

- 四类端到端场景集（含 architecture §6.2 的四步「面试准备」样例全链）。
- Flag 矩阵一致性测试（13 Flag 组合 + 八条串行链）。
- `regression-checklist.md`（新文件）。
- §9.6 十一条 Gate 的可执行判定条目。
- §9.7 十项遗留问题的收口核对表。
- 零迁移断言（迁移链头 0046）与兼容窗口（V9 旧读键双写）验证。
- §2.3 十条边界不变量核对。
- Gate 计数差异（「十个 Gate」vs §9.6 表列 11 条）的留痕。

**不包含（Non-Scope）**

- 任何新功能 / 新模块 / 新 Flag / 新表。
- 修复发现的缺陷（缺陷回到对应任务 PLAN-001 ~ PLAN-011 修复）。
- 下一版本内容（多步并行编排 Q1 / `WorldIntentSubmitter` 接线 Q5 / V9 旧读键退役 / 计划与 `daily_plans` 收敛 Q7 / 前端计划视图 Q10）。
- 真实模型人工回归的执行（本任务交付清单与判据；实际人工回归按清单执行，属上线前待办）。
- 单个任务的 Task Detail 级验收（各任务自验；本任务做**版本级扇入**）。

## 1.3 本任务解决什么问题

PLAN-001 ~ PLAN-011 各自有 Task Detail 级验收，但**跨任务的组合效应**无人负责：

| 组合风险 | 后果 | 本任务的守卫 |
|---|---|---|
| 每个子闸单测都过，但 13 个 Flag 的**组合**行为未验证 | 用户按某一组合开启时崩溃或行为不一致 | Flag 矩阵一致性测试 |
| 每个任务都声明「Flag off 逐字节一致」，但**同时** off 时无人验证 | 「回滚即回到 V2.4.0」的承诺无法举证 | G-COMPAT（prompt + 行为快照 + 维护步骤序列） |
| 各任务的静态断言分散，**整体零迁移**无人断言 | 某个任务悄悄加了列 | G-ZERO-MIGRATION |
| 跨任务的失败恢复链路（Action 退避 × Plan 放弃 × 重规划）未串联验证 | 「无限重规划」仅在各任务内被局部守卫 | 场景集第三 / 四类 + G-RETRY |

**本任务是「全量扇入」节点**（tasks.md §2.1：`PLAN-012 ▲ 全量扇入：PLAN-001 ~ PLAN-011`），也是 version 发布的唯一判据。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Planning System（PLAN-001 ~ PLAN-011）** | 本任务的验收对象 |
| **Memory 2.0 / Reflection / Autonomy 2.0 / World Simulation / Tool System V2.4.0** | 被复用的既有系统；其既有测试必须**零修改通过** |
| **Action Engine（V9 / V2.4.0）** | 执行唯一编排器；六闸门 / 退避 / outbox 一致性模型被复用 |
| **可观测基础设施** | `loop_runs` / `decision_records` / `action_records` 三账用于链路追溯 |
| **迁移链** | 链头 `0046_tool_insight_types.py`（零迁移断言的基准） |

**关键事实（已核对真实源码）**

- 迁移链头：`0046_tool_insight_types.py`（`apps/backend/migrations/versions/`）。
- `ck_goal_plans_status`：`('draft', 'validated', 'active', 'rejected', 'superseded')` 五值。
- `ck_decision_records_kind`：`('proactive_autonomy', 'turn_goal', 'turn_intention', 'turn_behavior', 'goal_lifecycle')` 五值。
- `ck_character_goals_type` + `character_goals.status` 七态（`GoalStatus` Literal 七值）。
- `life_loop._run_user_cycle` 九步：`perception` / `state_update` / `goal_check` / `goal_supply` / `goal_advance` / `memory_retrieval` / `reflection_check` / `decision` / `world_experience`。
- `autonomy_engine.tick` 二十步（PLAN-007 断言零改动）。
- V9 旧读键（architecture §7.11 兼容窗口）：`world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`。
- §9.6 表列 11 条 Gate；architecture §9.2 与标题表述为「十个 Gate」——**差异在本任务留痕并以 §9.6 表列为准**。

## 2.2 为什么需要本任务

architecture §9.6 明确列出 11 条 Gate，但它们分散在各任务的验收条目里。版本发布需要**一张可执行的判据表**回答一个问题：

> 「V2.5.0 能不能上线？」

本任务把这个问题的答案组织为：**四类场景 + Flag 矩阵 + 十一条 Gate 判定 + 十项遗留问题收口 + 十条边界不变量核对**，并落成 `regression-checklist.md` 供上线前执行（含真实模型人工回归）。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 四类端到端场景集（含 §6.2 四步样例全链） | 场景用例 |
| R2 | Flag 矩阵一致性测试（13 Flag × 串行链八条） | 矩阵用例 |
| R3 | `regression-checklist.md`（version 级回归清单） | 新文档 |
| R4 | §9.6 十一条 Gate 的可执行判定 | Gate 判定表 |
| R5 | §9.7 十项遗留问题收口 | 收口核对表 |
| R6 | 零迁移断言（迁移链头 0046 + 值集未扩） | 断言 |
| R7 | 兼容窗口兑现（V9 旧读键双写） | 断言 |
| R8 | §2.3 十条边界不变量核对 | 核对表 |
| R9 | Gate 计数差异留痕 | 验收记录 |
| R10 | 复用声明核对（零新建 Agent Core / Memory System / Event System / Tool System） | 核对表 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 修复任何缺陷 | 回到对应任务 PLAN-001 ~ PLAN-011 |
| N2 | 新功能 / 新 Flag / 新模块 | **永不**（验收任务） |
| N3 | 各任务内部的 Task Detail 级验收 | 各任务的 §10 |
| N4 | 真实模型人工回归的**执行** | 上线前待办（本任务交付清单与判据） |
| N5 | 下一版本内容（Q1 / Q5 / Q7 / Q10 的实现） | 推后续版本 |
| N6 | 前端调试控制台 | Q10 记录，本版本不实现 |
| N7 | `WorldIntentSubmitter` 接线 | Q5，本版本不接线 |
| N8 | V9 旧读键退役 | 推 V2.6.0，并在 V2.6.0 文档登记 |

## 3.3 职责边界一句话

> **本任务不写功能，只写判据：四类场景跑通、Flag 矩阵一致、十一条 Gate 全绿、十项遗留问题无悬空、十条红线未被踩。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 交付物与依赖方向

| 交付物 | 性质 | 内容 | 依赖 |
|---|---|---|---|
| 四类端到端场景集 | 测试 | 单目标规划 / 多步骤规划 / Tool 调用流程 / 失败恢复 | PLAN-003 ~ PLAN-010 |
| Flag 矩阵测试 | 测试 | 13 Flag 组合 + 八条串行链 + 总闸 off 逐字节一致 | PLAN-002 |
| `docs/version/v2.5.0/planning-system/regression-checklist.md` | 文档 | version 级回归清单 | 全部任务 |
| Gate 判定表 | 文档 + 测试 | §9.6 十一条 | 全部任务 |
| 遗留问题收口表 | 文档 | §9.7 十项 | PLAN-003 / 004 / 008 / 010 / 011 |
| 边界不变量核对表 | 文档 + 测试 | §2.3 十条 | 全部任务 |

### 4.1.2 Component 划分

```text
① 场景集（4 类）
├── A 单目标规划      ：任一 active Goal → GoalPlanRecord；每步有 tool_id 与判据
│                       同时覆盖判据 A 的两侧（落计划 / 走 action 直通）
├── B 多步骤规划      ：§6.2 四步「面试准备」全链
│                       目标成熟 → 六源装配 → 拆解 → 逐 tick 单步执行 → 观测推进
│                       → 终态广播 → 记忆沉淀 → 反思回环
├── C Tool 调用流程   ：PlanStep → ActionIntent → 六闸门 → assemble_plan
│                       → ToolExecutor 五段短路 → ToolResult → PlanStepOutcome
│                       （Run 台账 / 决策记录 / 行动记录 三账对齐）
└── D 失败恢复        ：§6.5 判定树全覆盖（blocked 四类 + failed / timeout + 观测 error）
                        §5.5 双层重试（Action 退避 / Plan 放弃）
                        §6.6 重规划五步（预算检查 → 保留与丢弃 → 新版本生成
                                         → 落库与切换 → 审计）

② Flag 矩阵
├── 13 个 v25_* Flag 的组合矩阵
├── §7.10 串行链八条逐条对照
└── 总闸 off 逐字节一致（prompt + 行为快照 + 维护步骤序列）

③ 回归清单（新文档）
└── docs/version/v2.5.0/planning-system/regression-checklist.md

④ Gate 判定（§9.6 十一条）
└── G-COMPAT / G-PLAN / G-DECOMPOSE / G-BIND / G-EXEC / G-RETRY
    / G-WORLD / G-MEMORY / G-REFLECT / G-BOUNDARY / G-ZERO-MIGRATION

⑤ 遗留问题收口（§9.7 十项）
└── Q1 ~ Q10 逐条核对留痕

⑥ 边界不变量核对（§2.3 十条）
└── 红线 1 ~ 10 逐条核对
```

### 4.1.3 数据流：验收判定链路

```text
① 各任务交付（PLAN-001 ~ PLAN-011）
        │  各自的 Task Detail 级验收
        ▼
② 场景集执行（本任务）
        │  四类端到端；跨任务组合效应在此暴露
        ▼
③ Flag 矩阵执行
        │  13 Flag 组合 × 八条串行链；总闸 off 逐字节对照
        ▼
④ Gate 判定（§9.6 十一条）
        │  每条 Gate 有自动化或人工可判定条目，且可追溯到 §9.6 原文
        ▼
⑤ 遗留问题收口（§9.7 十项）
        │  每项有裁决结论或记录留痕
        ▼
⑥ 边界不变量核对（§2.3 十条）
        │
        ▼
⑦ 回归清单落文档 + 发布判据结论
```

## 4.2 Core Model

本任务**不新增任何模型**。下表为验收判据的数据结构（文档级）。

### 4.2.1 四类端到端场景集

| 类 | 名称 | 覆盖 | 判据 |
|---|---|---|---|
| A | **单目标规划** | 任一 `active` Goal 产出 `GoalPlanRecord`；每步有明确 `tool_id` 绑定与达成判据；同时覆盖**判据 A 的两侧**（落计划 / 走 action 直通） | 计划状态为 `validated`；全部步骤 `tool_id` 可经 `ToolRegistry.resolve` 解析；判据 A 不满足的目标不落 `goal_plans` |
| B | **多步骤规划** | architecture §6.2 的四步「面试准备」样例**全链可复现** | 目标成熟 → 六源装配 → 拆解（4 Task + 工具绑定）→ 逐 tick 单步执行（受 cooldown 节流）→ 观测推进 → 终态广播 → 记忆沉淀 → 反思回环，八段各可举证 |
| C | **Tool 调用流程** | `PlanStep → ActionIntent → 六闸门 → assemble_plan → ToolExecutor 五段短路 → ToolResult → PlanStepOutcome` 全链可追溯 | Run 台账 / 决策记录 / 行动记录**三账对齐** |
| D | **失败恢复** | §6.5 判定树全覆盖（`blocked` 四类 + `failed` / `timeout` + 观测 `error`）；§5.5 双层重试；§6.6 重规划五步 | 每条分支有可判定用例；重规划不重做已完成步骤、不产生重复世界副作用 |

### 4.2.2 Flag 矩阵（13 Flag × 依赖链八条）

| # | Flag | 依赖 | 默认 | 矩阵验证点 |
|---|---|---|---|---|
| 1 | `v25_planning_enabled` | — | off | 总闸；off 时全链逐字节一致 |
| 2 | `v25_plan_context_enabled` | 总闸 | off | 六源装配开关 |
| 3 | `v25_plan_step_binding_enabled` | 总闸 | off | 闸门 5/6 开关 |
| 4 | `v25_plan_scheduler_enabled` | 总闸 | off | 调度开关 |
| 5 | `v25_plan_execution_enabled` | 总闸 + `action_enabled` | off | 执行接线开关 |
| 6 | `v25_plan_observation_enabled` | 总闸 | off | 四事实源开关 |
| 7 | `v25_plan_revision_enabled` | 总闸 | off | 重规划裁决开关 |
| 8 | `v25_plan_memory_enabled` | 总闸 + `v2_memory_enabled` | off | 记忆边界表开关 |
| 9 | `v25_plan_reflection_enabled` | 总闸 + `v2_reflection_enabled` | off | 证据窗 + 监听器开关 |
| 10 | `v25_plan_world_feedback_enabled` | 总闸 | off | 世界事实 + 终态广播开关 |
| 11 | `v25_plan_autonomy_enabled` | 总闸 + `v21_agent_runtime_enabled` | off | `plan_facts` 开关 |
| 12 | `v25_plan_tool_required` | 总闸 + `v24_tool_system_enabled` | **on** | 工具面硬依赖开关 |
| 13 | `v25_plan_debug_enabled` | 总闸 | off | 调试端点开关 |

**串行链八条（architecture §7.10）**

| # | 链 | 违规表现 |
|---|---|---|
| 1 | 任一 `v25_*` 子闸 ⇒ `v25_planning_enabled` | 启动 fail-fast，理由中文 |
| 2 | `v25_planning_enabled` ⇒ `v2_autonomy_advanced_enabled` AND `v2_life_loop_enabled` | 同上 |
| 3 | `v25_plan_execution_enabled` ⇒ `v25_plan_scheduler_enabled` AND `action_enabled` | 同上 |
| 4 | `v25_plan_step_binding_enabled` ⇒ `v25_planning_enabled` AND `v24_tool_system_enabled` | 同上 |
| 5 | `v25_plan_tool_required` ⇒ `v25_plan_step_binding_enabled` AND `v24_tool_system_enabled` | 同上 |
| 6 | `v25_plan_reflection_enabled` ⇒ `v25_planning_enabled` AND `v2_reflection_enabled` | 同上 |
| 7 | `v25_plan_memory_enabled` ⇒ `v25_planning_enabled` AND `v2_memory_enabled` | 同上 |
| 8 | `v25_plan_autonomy_enabled` ⇒ `v25_planning_enabled` AND `v21_agent_runtime_enabled` | 同上 |

> **计数留痕**：architecture §7.10 列八条链（其中①为「子闸 → 总闸」通用条目，②~⑧为跨版本依赖条目）；tasks.md 描述为「七条」（按跨版本项计）。**本任务以 §7.10 的八条为准实现，差异在验收记录中留痕**（与 §9.6 Gate 计数差异同款纪律）。

### 4.2.3 §9.6 十一条 Gate（判定表）

| Gate | 判定 | 可执行条目的归属任务 |
|---|---|---|
| **G-COMPAT** | Flag 全 off：prompt 与 V2.4.0 逐字节一致；既有测试零修改通过；`goal_planning` / `goal_observation` / `goal_execution` 原路径生效 | 全任务（本任务做扇入对照） |
| **G-PLAN** | 任一 active Goal 可产出含工具绑定的多步计划；七道闸各有可复现拒绝用例 | PLAN-003 |
| **G-DECOMPOSE** | Goal → Tasks → Actions 三级映射可举证；Task 粒度判据（独立判据 + 独立工具 + 一次 Action 内可完成）逐条成立 | PLAN-004 |
| **G-BIND** | 每个步骤的 `tool_id` 可经 `ToolRegistry.resolve` 解析且 ∈ 当前工具面；一能力多工具时绑定确定性可复现 | PLAN-004 / PLAN-006 |
| **G-EXEC** | 步骤执行经 `action_engine` 六闸门与 `ToolExecutor` 五段短路（链路断言）；Planning 目录零直调 `ToolExecutor` / `Capability.execute` | PLAN-005 / PLAN-006 |
| **G-RETRY** | 双层计数职责清晰（Action 退避 / Plan 放弃）；**重规划不重做已完成步骤、不产生重复世界副作用**（`deferred_world_op` 计数验证） | PLAN-005 |
| **G-WORLD** | 静态扫描断言：`services/planning/` 零 `world_repository` 导入；计划写世界全部经 outbox；终态经 `event_bridge` 广播 | PLAN-008 |
| **G-MEMORY** | 计划本体与中间步骤零写入 `memories`；终态三类事件各沉淀一条且 R1~R8 零豁免；重复投递不产生第二条 | PLAN-009 |
| **G-REFLECT** | 计划证据窗达门槛才产 Insight；三道闸零豁免；**Insight 不直接改写计划**（隔离断言）；`TRIGGER_REPLAN` 幂等 | PLAN-010 |
| **G-BOUNDARY** | 三者职责不重叠：Autonomy 只出 intention、Planning 只出 plan、Tool 只出 result（各自输出契约的静态与运行时断言） | PLAN-007 |
| **G-ZERO-MIGRATION** | 无新表、无新列、无新索引、无新 CHECK 值；迁移链保持 0046；`decision_records.kind` 仍为五值 | 全任务（本任务做扇入断言） |

> **Gate 计数差异留痕（要求明确）**：architecture §9.2 与标题表述为「十个 Gate」，而 §9.6 表实际列出 **11 条**。本任务**以 §9.6 表列为准**，并在验收记录中留痕该表述差异（tasks.md PLAN-012 明确要求）。

### 4.2.4 §9.7 十项遗留问题收口表

| # | 问题 | 挂载任务 | 本任务的收口核对 |
|---|---|---|---|
| Q1 | 多步工具编排语义（并行步骤 / 部分失败回滚） | 不在本版本 | 核对：`action_plan_max_steps` **保持 1**；无并行调度代码 |
| Q2 | `GoalPlanRecord` 新增字段落点 | PLAN-002 | 核对：落 `decision_records.input_snapshot`；零加列；留痕记录存在 |
| Q3 | `SubGoalSpec` 的 Pydantic `extra` 策略 | PLAN-002 | 核对：保持默认 `ignore`；新字段显式入模型；双向兼容测试存在 |
| Q4 | `fact_source="tool"` 与 `threshold_reached` 的组合语义 | PLAN-004 | 核对：`fact_source="tool"` 下**拒绝** `threshold_reached`；负例存在 |
| Q5 | `WorldIntentSubmitter` 接线 | PLAN-008 | 核对：仍 `WIRED=False`；未接线断言存在；评估结论留痕 |
| Q6 | `PlanContext` 装配的 LLM 成本与延迟 | PLAN-003 | 核对：压测记录存在；**未新增 capability 位**（`v2_life_loop_cycle_llm_budget` 数学未变） |
| Q7 | 计划与 `daily_plans` 的语义收敛 | 不在本版本 | 核对：**互不引用**（无交叉 import / 无字段共享） |
| Q8 | Reflection Insight 与 `PlanRevisionPolicy` 优先级 | PLAN-010 | 核对：优先序已裁决（事实 > 建议）；同时命中只产生一个触发用例存在 |
| Q9 | 计划完成对 Character State 的间接影响 | PLAN-008 | 核对：记录留痕存在；本版本**不做**关系域信号扩张 |
| Q10 | 计划可观测面是否纳入前端调试控制台 | PLAN-011 | 核对：记录留痕存在；本版本**仅后端端点**，前端不实现 |

**收口判据**：十项各有**裁决结论**或**记录留痕**，无悬空项。

### 4.2.5 §2.3 十条边界不变量核对表

| # | 不变量 | 核对方式 |
|---|---|---|
| 1 | 不新建表、不加迁移 | 迁移链头 `0046`；无新表 / 新列 / 新索引 / 新 CHECK |
| 2 | 不新建 Goal 系统 | `character_goals` 语义 / `GOAL_TRANSITIONS` / `set_status` 唯一写面未动（PLAN-001 差异对照） |
| 3 | 不新建执行编排器；**不放开 `action_plan_max_steps`**（保持 1） | 静态断言：常量值 = 1；无第二执行编排器 |
| 4 | 不绕过工具治理 | 闸门 5/6 + 六闸门 + 五段短路（G-BIND / G-EXEC） |
| 5 | 不直接写世界、不直接写 Character 域 | G-WORLD + 零 `character_state` / `personality_state` / `relationship_*` 写入 |
| 6 | 不绕过记忆政策 | 「R1~R8 零豁免」静态 + 运行时断言 |
| 7 | 反思不直接改写计划 | G-REFLECT 隔离断言 |
| 8 | 默认拒绝与降级放行沿用既有范式 | 工具面不可得 → 不生成该步；装配失败 → 逐段降级而非抛错 |
| 9 | V2.4.0 兼容承诺在本版本兑现 | V9 旧读键双写断言（§4.2.6） |
| 10 | Flag 全 off 时与 V2.4.0 逐字节一致 | G-COMPAT |

### 4.2.6 兼容窗口（V9 旧读键双写）

| 旧读键 | 本版本行为 | 退役窗口 |
|---|---|---|
| `world_event_id` | **继续双写** | V2.6.0（须在 V2.6.0 文档显式登记） |
| `memory_id` | **继续双写** | 同上 |
| `failure_kind` | **继续双写** | 同上 |
| `deferred_world_op` | **继续双写** | 同上 |

### 4.2.7 复用声明核对（零新建同类系统）

| 既有系统 | 复用方式 | 零新建核对 |
|---|---|---|
| Agent Core / Runtime（`life_loop` + `agent_runtime` + `background_jobs`） | 挂既有维护步 | 无新 stage / 无新调度循环 / 无新 Worker |
| Goal System（`models/goal.py` + `goal_repository` + `goal_arbitration` + `goal_service`） | 只读消费 + 单一写回 | 无第二套 Goal 系统 / 无第二套优先级算法 |
| Memory System（`memory_policy` R1~R8 + `memory2.*`） | 既有政策闸 + 既有 ingest | 无第二套记忆系统 / 无新政策闸 |
| Event System（`event_bridge` + `world_events` + `outbox`） | 复用既有广播 | 无新事件类型 / 无第二套事件系统 |
| Tool System（`ToolRegistry` / `ToolSurface` / `ToolSelector` / `ToolExecutor`） | 规划期查询 + 执行期经 Action 编排器 | 无第二套工具系统 / 无新选择逻辑 |
| Action Engine（`run_action_planning`） | 唯一执行编排器 | 无第二执行编排器 |

## 4.3 State Machine

本任务**不引入任何状态机**。下表为验收判定自身的过程状态（文档级）。

### 4.3.1 验收判定过程

```text
① 场景集执行
    ├─ 全过 ──────────────────────► ②
    └─ 有失败 ──► 缺陷回到对应任务（PLAN-00x）修复 → 重跑 ①

② Flag 矩阵执行
    ├─ 全过（含总闸 off 逐字节一致）─► ③
    └─ 有失败 ──► 回 ① 或回 PLAN-002

③ Gate 判定（§9.6 十一条）
    ├─ 全绿 ──────────────────────► ④
    └─ 有红 ──► 缺陷归属任务修复 → 重跑对应场景 + 该 Gate

④ 遗留问题收口（§9.7 十项）
    ├─ 无悬空 ────────────────────► ⑤
    └─ 有悬空 ──► 补裁决或补留痕

⑤ 边界不变量核对（§2.3 十条）
    ├─ 全过 ──────────────────────► ⑥
    └─ 有违反 ──► 回退重审对应裁决（architecture §3.1 / §4.1 / §4.9）并留痕

⑥ 回归清单落文档 + 发布判据结论
```

### 4.3.2 逐字节一致的三重对照（G-COMPAT）

```text
Flag 全 off 时：
    ├─ prompt 对照：规划 prompt 与 V2.4.0 逐字节一致
    ├─ 行为快照对照：goal_planning / goal_observation / goal_execution 行为零差异
    └─ 维护步骤序列对照：life_loop 九步 + autonomy_engine.tick 二十步形状零差异
       ⇒ 三者同时成立才判 G-COMPAT 绿
```

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `autonomy_engine.tick` 二十步序列 | 被验收项 | **形状快照对照** |
| 六维权重 / `_SOURCE_PRIORITY` / `_ACTION_SOURCES` | 被验收项 | **快照对照零差异** |
| G-BOUNDARY | 输出契约断言 | **Gate 判定** |
| 额度与冷却未放宽 | 被验收项 | **负例核对** |

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| V2.4.0 工具侧既有测试 | 必须零失败 | **扇入回归** |
| G-BIND / G-EXEC | Gate | **判定** |
| `action_plan_max_steps` = 1 | 红线 3 | **静态断言** |
| 工具面 / 选择器 / 执行器契约 | 被复用 | **零改动核对** |

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| G-WORLD | Gate | **判定**（静态扫描 + outbox 路径 + 广播） |
| 世界侧既有测试 | 必须零失败 | **扇入回归** |
| `world_events.type` 值域 | 未扩 | **值集对照** |
| `WorldIntentSubmitter` | `WIRED=False` | **未接线核对（Q5）** |

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| G-MEMORY | Gate | **判定**（零写入 + 三类终态各一条 + R1~R8 零豁免） |
| R1 不误杀 | 专项 | **核对**（失败 / 放弃类候选可通过 R1） |
| `memories` 表结构 | 未变 | **列集与值集对照** |
| 记忆侧既有测试 | 必须零失败 | **扇入回归** |

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| G-REFLECT | Gate | **判定**（门槛 + 三闸 + 隔离 + 幂等） |
| 既有三消费者回归 | 必须不变 | **回归对照** |
| 三道闸零豁免 | 专项 | **核对** |
| 证据通道值集 | 由 2 值扩 3 值 | **值集对照** |

## 5.6 与 Goal System / Action Engine

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| Goal 域差异对照 | 零改动 | **扇入核对（PLAN-001 的差异对照在版本级复核）** |
| `character_goals` / `goal_plans` 表结构 | 未变 | **列集与 CHECK 值集对照** |
| `goal_observation` / `goal_execution` 原路径 | Flag off 时生效 | **G-COMPAT 对照** |
| 迁移链头 | `0046` | **G-ZERO-MIGRATION 断言** |

## 5.7 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 计划生成 / 拆解 / 调度 / 执行 / 观测 / 修订的逻辑 | 不涉及（只验收） | 属 PLAN-003 ~ PLAN-005 |
| 工具治理逻辑 | 不涉及（只验收） | 属 PLAN-006 |
| 世界 / 记忆 / 反思 / 自治接线逻辑 | 不涉及（只验收） | 属 PLAN-007 ~ PLAN-010 |
| 调试端点的实现 | 不涉及（只验收门控与投影） | 属 PLAN-011 |
| 前端调试控制台 | 不涉及（Q10 记录） | 推后续版本 |
| 下一版本内容 | 不涉及 | Q1 / Q5 / Q7 / 旧读键退役均明确排除 |

---

# 6. API / Interface Design

本任务**不新增任何接口**。下表为验收面的「接口」——即被验收的契约集合与验收脚本的调用形态。

## 6.1 被验收的契约集合（扇入清单）

| 来源 | 契约 | 验收方式 |
|---|---|---|
| PLAN-001 | Goal 四项契约 + 四条联动不变量 | 差异对照 + 不变量用例 |
| PLAN-002 | 值对象 + 模型扩展 + Flag/参数 + 串行链 | 序列化往返 + 双向兼容 + 串行链负例 |
| PLAN-003 | `PlanContextAssembler` + `PlanningEngine` + 七道闸 | 六源两态 + 七道闸负例 + 零 LLM |
| PLAN-004 | `TaskDecomposer` + `PlanValidator` 三闸 | tiebreak 复现 + 白名单 + 纯函数 |
| PLAN-005 | `PlanScheduler` + `PlanExecutorBridge` + `PlanObserver` + `PlanRevisionPolicy` | 搬运等价性 + 双层重试 + 保留步不重做 |
| PLAN-006 | 闸门 5/6 + 执行链路 + 四类工具不进计划 | 链路断言 + 零外部调用 + G-EXEC |
| PLAN-007 | `plan_facts` + 候选面 + 额度未放宽 | 六字段 + 快照对照 + 负例 |
| PLAN-008 | 九类世界事实 + 三条合法路径 + 终态广播 | G-WORLD + outbox 幂等 + 修订不广播 |
| PLAN-009 | 判据 A/B/C + R1 不误杀 | 零写入 + 三类终态 + G-MEMORY |
| PLAN-010 | 三证据窗 + 监听器 + Q8 去重 | 三窗场景 + 三门槛负例 + 隔离 |
| PLAN-011 | 六模块签名 + 三只读函数 + 审计投影 + 6 端点 | 签名对照 + 投影重建 + 端点门控 |

## 6.2 验收脚本的调用形态（不写实现）

```text
# 场景集
scenario.single_goal_planning()        # A 类：含判据 A 两侧
scenario.multi_step_planning()         # B 类：§6.2 四步样例全链
scenario.tool_invocation_chain()       # C 类：三账对齐
scenario.failure_recovery()            # D 类：判定树 + 双层重试 + 重规划五步

# Flag 矩阵
flag_matrix.combinations()             # 13 Flag 组合
flag_matrix.enablement_chain()         # 串行链八条逐条
flag_matrix.all_off_bytewise()         # prompt + 行为快照 + 维护步骤序列

# Gate 判定
gate.judge("G-COMPAT")                 # … 十一条
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | Gate 判定条目**可追溯到 §9.6 原文** | 逐条映射表 |
| D2 | 每条 Gate 至少有一个自动化或人工可判定条目 | 判定表完整性检查 |
| D3 | 场景集必须覆盖判据 A 的**两侧**（落计划 / action 直通） | 用例断言 |
| D4 | 场景集必须覆盖 `blocked` **四类** | 用例断言 |
| D5 | Flag 全 off 对照必须**三重**（prompt / 行为快照 / 维护步骤序列） | 三者同时断言 |
| D6 | 本任务**零新增 Flag / 零新增模块** | 静态断言 |

## 6.3 `regression-checklist.md` 结构契约

```text
docs/version/v2.5.0/planning-system/regression-checklist.md
├── 1 适用范围与前置（Flag 全 off 基线 / 迁移链头 0046）
├── 2 四类端到端场景清单（A/B/C/D，含逐项判据）
├── 3 Flag 矩阵清单（13 Flag + 八条串行链 + 全 off 三重对照）
├── 4 Gate 判定清单（§9.6 十一条，逐条可判定条目 + 追溯）
├── 5 遗留问题收口清单（§9.7 十项）
├── 6 边界不变量核对清单（§2.3 十条）
├── 7 复用声明核对（零新建 Agent Core / Memory / Event / Tool System）
├── 8 零迁移与兼容窗口（0046 / V9 旧读键双写）
└── 9 真实模型人工回归指引（执行步骤，非本任务执行）
```

## 6.4 异常契约

| 情形 | 处置 |
|---|---|
| 场景集失败 | 缺陷归属对应任务（PLAN-00x）修复；**不在本任务打补丁** |
| Flag 矩阵失败 | 回 PLAN-002（串行链）或回 ① 重跑 |
| Gate 判定红 | 缺陷归属任务修复 → 重跑对应场景 + 该 Gate |
| 遗留问题悬空 | 补裁决或补留痕；**不允许悬空结项** |
| 边界不变量被违反 | **回退重审**对应裁决（architecture §3.1 / §4.1 / §4.9）并留痕 |
| 发现建表 / 建列需求 | 说明设计已被违背，**回退重审** §4.9 并留痕；不得直接加列 |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | architecture §2.3 红线 1；计划 / 步骤 / 审计 / 证据全部落在 `goal_plans` / `action_records` / `decision_records` / `loop_runs` 四张既有表 |
| 新列 | 无 | 全部扩展落在既有 JSON 列（`goal_plans.sub_goals` / `decision_records.input_snapshot` / `action_records.steps` / `loop_runs.steps`） |
| 新索引 | 无 | 复用既有 `uq_goal_plans_goal_version` / `idx_goal_plans_goal_status` / `idx_decision_records_user_time` |
| 改 CHECK | 无 | `ck_goal_plans_status` 五值、`ck_decision_records_kind` 五值、`ck_character_goals_status` 七态均未变 |
| 迁移 | 无 | **迁移链头必须仍为 `0046_tool_insight_types.py`** |

**G-ZERO-MIGRATION 的可执行判定**

| # | 判定项 | 期望 |
|---|---|---|
| Z1 | 迁移链头 | `0046_tool_insight_types.py` |
| Z2 | 新增 Alembic revision | 0 个 |
| Z3 | 新表 | 0 张 |
| Z4 | 新列 | 0 列 |
| Z5 | 新索引 | 0 个 |
| Z6 | 新 CHECK 值 | 0 个（`ck_goal_plans_status` / `ck_decision_records_kind` / `ck_character_goals_*` 值集未扩） |
| Z7 | 值域型常量未扩 | `ActionStatus` / `GATE_REASONS` / `DecisionKind` / `world_events.type` / `memories.type` / `memories.source` 均未新增值 |
| Z8 | 若出现建表 / 建列需求 | **必须回退重审 §4.9 并留痕**（不得直接加列） |

**兼容窗口（回滚可行性）**：全部 `v25_*` Flag 置 off 即回到 V2.4.0 行为（逐字节一致）；无数据回滚需求（无新表、无破坏性列变更、无值域扩张）。

---

# 8. Implementation Plan

## Step 1 — 场景集 A：单目标规划

1. 构造 `active` 目标 → 规划 → 断言产出 `GoalPlanRecord(status="validated")`。
2. 断言每步有 `tool_id` 绑定与达成判据。
3. **覆盖判据 A 两侧**：多步跨天的目标落计划；单步当场可验的目标走 action 直通（不落 `goal_plans`）。
4. 单测 + 集成用例。

## Step 2 — 场景集 B：多步骤规划（§6.2 四步样例全链）

1. 以「后天有个面试，帮我准备一下」为样例，逐段验证八段链路：
   目标成熟 → 六源装配 → 拆解（4 Task + 工具绑定）→ 逐 tick 单步执行（受 cooldown 节流）→ 观测推进 → 终态广播 → 记忆沉淀 → 反思回环。
2. 每段给出可举证证据（`goal_plans` / `action_records` / `decision_records` / `world_events` / `memories` / `insights`）。
3. 断言跨 tick 单步推进与 cooldown 节流生效。
4. 端到端用例。

## Step 3 — 场景集 C：Tool 调用流程

1. 验证 `PlanStep → ActionIntent → 六闸门 → assemble_plan → ToolExecutor 五段短路 → ToolResult → PlanStepOutcome` 全链。
2. 断言**三账对齐**：Run 台账（`loop_runs`）/ 决策记录（`decision_records`）/ 行动记录（`action_records`）。
3. 断言每段可观测（打桩：各段调用一次、顺序固定）。
4. 端到端用例。

## Step 4 — 场景集 D：失败恢复

1. §6.5 判定树全覆盖：`blocked` 四类（`permission_denied` / `invalid_params` / `pending_confirmation` / `capability_unavailable`）+ `failed` / `timeout` + 观测 `error`。
2. §5.5 双层重试：Action 层技术性退避重试 + Plan 层业务性放弃，各有用例。
3. §6.6 重规划五步：预算检查 → 保留与丢弃 → 新版本生成 → 落库与切换 → 审计，逐步可判定。
4. **G-RETRY 专项**：重规划不重做已完成步骤、不产生重复世界副作用（`deferred_world_op` 计数验证）。
5. **无限重规划阻断**：达 `v25_plan_revision_budget` → 计划 `rejected` + 目标 `failed("plan_exhausted")`。
6. 端到端用例。

## Step 5 — Flag 矩阵一致性测试

1. 13 个 `v25_*` Flag 的组合矩阵：枚举合法组合（满足八条串行链）+ 非法组合（各链至少一个违规负例）。
2. 八条串行链逐条对照：违规启动 fail-fast 且理由中文可读。
3. **总闸 off 三重对照**：prompt 逐字节 + 行为快照零差异 + 维护步骤序列形状零差异。
4. 断言既有测试**零修改**通过。
5. 单测 + 集成用例。

## Step 6 — Gate 判定（§9.6 十一条）

1. 为十一条 Gate 各定义自动化或人工可判定条目，并**逐条追溯到 §9.6 原文**。
2. 汇总各任务的 Gate 相关验收条目，做版本级扇入判定。
3. 记录 Gate 计数差异（「十个 Gate」vs §9.6 表列 11 条）并以表列为准。
4. 输出 Gate 判定表（每条：判定 / 证据 / 追溯）。

## Step 7 — 遗留问题收口（§9.7 十项）

1. 逐项核对 Q1 ~ Q10 的裁决结论或记录留痕（§4.2.4 表）。
2. 无悬空项断言（每项必须有结论或留痕链接）。
3. 明确本版本**不做**的项（Q1 / Q5 接线 / Q7 / Q9 关系域扩张 / Q10 前端）与其推后版本。

## Step 8 — 边界不变量与复用声明核对（§2.3 十条）

1. 逐条核对十条红线（§4.2.5 表）。
2. 逐条核对六类既有系统的复用声明（§4.2.7 表）。
3. 特别核对：红线 3（`action_plan_max_steps` = 1）、红线 10（Flag 全 off 逐字节一致）、红线 1（零迁移）。
4. 零新建同类系统断言：无第二套 Goal / Memory / Event / Tool / Action 系统。

## Step 9 — 零迁移与兼容窗口验证

1. G-ZERO-MIGRATION 八项判定（§7 表）逐条断言。
2. V9 旧读键（`world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`）**双写断言**通过；兼容窗口 ≥ 一个版本。
3. 明确退役窗口推 V2.6.0 并登记要求。

## Step 10 — 交付 `regression-checklist.md`

1. 按 §6.3 结构契约撰写 `docs/version/v2.5.0/planning-system/regression-checklist.md`。
2. 包含四类场景清单、Flag 矩阵清单、十一条 Gate 判定清单、十项遗留问题收口清单、十条边界不变量核对清单、复用声明核对、零迁移与兼容窗口、真实模型人工回归指引。
3. 清单条目与 architecture §9.6 / §9.7 / §2.3 / §7.10 / §7.11 逐条对应（可追溯）。
4. 交付后本任务结项；实际人工回归按清单执行（属上线前待办）。

---

# 9. Testing Strategy

> 本任务的「测试」即版本级验收本身。下表按 Unit / Integration / Scenario 三层组织验收条目。

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | Flag 默认值矩阵 | 13 个 Flag 默认值与 §7.10 逐条一致（12 off + `v25_plan_tool_required` on） |
| U2 | 串行链八条 | 每条一个违规负例，逐条命中并报出违规链；理由中文可读 |
| U3 | 参数边界 | §7.10 的 14 个参数默认值一致；越界 fail-fast |
| U4 | 判据 A 两侧 | 落计划 / action 直通各一例 |
| U5 | §6.5 判定树分支 | `blocked` 四类 + `failed` / `timeout` + 观测 `error` 各一例 |
| U6 | 双层重试计数 | Action 层 `attempt` 递增时机与 Plan 层 `attempt_count` 递增时机各一例 |
| U7 | 重规划理由码 | 四条理由码各一例；优先序归一正确（Q8） |
| U8 | Gate 判定条目完整性 | 十一条 Gate 各至少一条可判定条目；可追溯到 §9.6 |
| U9 | 遗留问题收口完整性 | 十项各有结论或留痕；无悬空 |
| U10 | 边界不变量核对完整性 | 十条各有核对结论 |
| U11 | 复用声明核对 | 六类既有系统的「零新建」断言各一例 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **G-COMPAT 三重对照** | prompt 逐字节 + 行为快照零差异 + 维护步骤序列形状零差异 |
| I2 | 既有测试零修改通过 | 测试文件 diff 为空；全量回归绿 |
| I3 | 原路径生效 | Flag off 时 `goal_planning` / `goal_observation` / `goal_execution` 走原路径 |
| I4 | `life_loop` 九步序列 | 形状快照对照零差异 |
| I5 | `autonomy_engine.tick` 二十步序列 | 形状快照对照零差异 |
| I6 | 六维权重与 `_SOURCE_PRIORITY` | 快照对照零差异 |
| I7 | **G-ZERO-MIGRATION 八项** | §7 表 Z1~Z8 逐条断言 |
| I8 | 兼容窗口 | V9 旧读键四项双写断言通过 |
| I9 | 三账对齐 | `loop_runs` / `decision_records` / `action_records` 对同一次步骤执行可互追溯 |
| I10 | 值集未扩 | `ActionStatus` / `GATE_REASONS` / `DecisionKind` / `world_events.type` / `memories.*` 值集快照未变 |
| I11 | 世界侧 / 工具侧既有测试 | 零失败 |
| I12 | 表结构未变 | `character_goals` / `goal_plans` / `action_records` / `decision_records` / `loop_runs` / `memories` 列集与 CHECK 未变 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 覆盖 | 期望 |
|---|---|---|---|
| S1 | **A 类 单目标规划** | 判据 A 两侧 | 落计划侧产出 `validated` 计划；直通侧不落 `goal_plans` |
| S2 | **B 类 多步骤规划** | §6.2 四步样例八段全链 | 八段各可举证；跨 tick 单步推进 + cooldown 节流生效 |
| S3 | **C 类 Tool 调用流程** | 执行链 + 三账对齐 | 六闸门与五段短路全经过；三账可互追溯 |
| S4 | **D 类 失败恢复** | 判定树 + 双层重试 + 重规划五步 | 每条分支可判定；**不重做已完成步骤、不产生重复世界副作用**；无限重规划被预算阻断 |
| S5 | **「帮我规划一次旅行」** | 跨 PLAN-003 ~ PLAN-010 组合 | 装配（含世界事实）→ 拆解（工具绑定）→ 执行（治理链路）→ 观测（四事实源）→ 终态（广播）→ 记忆（边界表）→ 反思（证据窗与回环）全链走通 |
| S6 | Flag 全 off 全链 | G-COMPAT | 与 V2.4.0 逐字节一致 |
| S7 | 回滚演练 | Flag 全 off | 回到 V2.4.0 行为；无数据回滚需求 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- 四类端到端场景全部通过，且 §6.2 的四步计划样例全链可复现（含跨 tick 单步推进与 cooldown 节流）。
- Flag 全 off 时与 V2.4.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）；既有测试**零修改**通过。
- §9.6 全部 Gate 各有自动化或人工可判定条目，且全部可追溯到 §9.6 原文；「十个 Gate」与表列 11 条的表述差异在验收记录中留痕并以表列为准。
- **零迁移断言成立**：迁移链头仍为 0046；无新表 / 新列 / 新索引 / 新 CHECK 值；`ck_goal_plans_status` 五值、`ck_decision_records_kind` 五值未变；若出现建表 / 建列需求必须回退重审 §4.9 并留痕。
- **失败恢复全链可判定**：Action 层技术性退避重试与 Plan 层业务性放弃双层语义各有用例；重规划不重做已完成步骤、不产生重复世界副作用（`deferred_world_op` 计数验证）；「无限重规划」被 `v25_plan_revision_budget` 阻断（达上限后计划 `rejected` + 目标 `failed("plan_exhausted")`）。
- §9.7 十项遗留问题各有裁决结论或记录留痕，无悬空项。
- V9 旧读键（`world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`）双写断言通过，兼容窗口 ≥ 一个版本。
- 回归清单覆盖 §2.3 十条边界不变量与「零新建 Agent Core / Memory System / Event System / Tool System」复用声明。
- 计划对世界的写入路径与 V9 一致性（outbox 幂等 + 崩溃重放）在世界侧既有测试中零失败。
- `regression-checklist.md` 已交付且条目与 architecture §9.6 / §9.7 / §2.3 / §7.10 / §7.11 可追溯对应。

## 10.2 Integration Acceptance

- 十一条 Gate 全部可判定（G-COMPAT / G-PLAN / G-DECOMPOSE / G-BIND / G-EXEC / G-RETRY / G-WORLD / G-MEMORY / G-REFLECT / G-BOUNDARY / G-ZERO-MIGRATION），每条附证据与追溯。
- `life_loop` 九步序列、`autonomous_tick` stage 序列、`autonomy_engine.tick` 二十步序列三者形状快照零差异。
- 六维权重数学 / `_SOURCE_PRIORITY` / `_ACTION_SOURCES` 快照零差异。
- 既有系统侧测试零失败：`goal_*` / `action_*` / `tool*` / `world*` / `memory*` / `reflection*` / `autonomy*` / `decision_pipeline` / `life_loop` / `agent_runtime`。
- 表结构零变更：六张核心表的列集与 CHECK 值集未变。
- 回滚可行性：Flag 全 off 即回到 V2.4.0 行为（逐字节一致）；无数据回滚需求。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`；G-ZERO-MIGRATION 八项判定全绿。
- **零新建同类系统**：无第二套 Goal / Memory / Event / Tool / Action 系统；六类既有系统复用声明逐条核对通过。
- **验收任务不引入功能**：本任务零新增 Flag、零新增模块、零新增端点、零新增表；发现缺陷一律回到对应任务修复。
- **差异留痕**：Gate 计数差异（十个 vs 十一条）与串行链计数差异（七条 vs 八条）均在验收记录中留痕并明确以架构表列为准。
- **无悬空项**：§9.7 十项遗留问题逐项收口；§2.3 十条红线逐条核对；无「待定」「待确认」类条目。
- **交付物齐全**：`regression-checklist.md` 按 §6.3 结构契约交付，覆盖九个小节。
- **上线前待办明确**：真实模型人工回归按清单执行，本任务交付清单与判据、不执行回归。
- **文档一致**：本文件与 architecture §9.6 / §9.7 / §2.3 / §6.1 ~ §6.6 / §7.10 / §7.11 及 tasks.md PLAN-012 Acceptance Criteria 逐条对应，无自相矛盾。
