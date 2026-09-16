# V2.5.0 Planning System 人工回归清单

> 上游：[architecture.md](./architecture.md) §9.6（Gate）、§9.7（遗留问题）、§2.3（十条红线）、§6.1 ~ §6.6、§7.10、§7.11
> 用途：版本发布判据 + 真实模型人工回归执行单
> 配套自动化：`apps/backend/tests/v25/test_plan012_*.py`
> 状态：自动化部分已交付；真实模型人工回归待上线前执行

---

## 1. 适用范围与前置

| 项 | 说明 |
|---|---|
| 版本 | V2.5.0 Planning System（PLAN-001 ~ PLAN-012） |
| 迁移链头 | `0046_tool_insight_types.py`（**零迁移**） |
| Flag 默认态 | 13 个 `v25_*` 全 off（`v25_plan_tool_required` 默认 on，但以总闸为前提） |
| 回滚路径 | 全部 `v25_*` 置 off 即回到 V2.4.0 行为（逐字节一致） |
| 自动化入口 | `uv run pytest tests/v25 -q`（Focused）→ `tests/v24` 工具侧回归 |

---

## 2. 四类端到端场景清单

| 类 | 名称 | 判据 | 自动化 |
|---|---|---|---|
| **A** | 单目标规划 | active Goal → `validated` 多步计划；每步 `tool_id` 可解析、判据可判定；判据 A 两侧（落计划 / action 直通） | `test_plan012_scenario_a_single_goal.py` |
| **B** | 多步骤规划 | architecture §6.2 四步「面试准备」全链：结构 / 调度 / 观测 / 记忆边界 / 重规划静默 | `test_plan012_scenario_b_multi_step.py` |
| **C** | Tool 调用流程 | `PlanStep → ActionIntent → 归一 → reconcile`；幂等键 `plan:{goal}:{ver}:{idx}` 可复现；failure_kind ∈ 既有 6 值 | `test_plan012_scenario_c_tool_chain.py` |
| **D** | 失败恢复 | blocked 四类；attempt_count 终态才递增；重规划保留 done 步；观测 error 不改计划状态 | `test_plan012_scenario_d_failure_recovery.py` |

### 人工补充（真实模型）

- **A**：对真实用户说「帮我安排一次体检」，观察是否产出多步计划且 debug 端点可见绑定。
- **B**：说「后天有个面试，帮我准备一下」，验证跨 tick 单步推进与 cooldown 节流。
- **C**：在 debug 面板核对 `action_records` / `decision_records` / `goal_plans.sub_goals` 三账可互追溯。
- **D**：人为禁用某工具后触发步骤，验证 `off_surface` 与重规划不重做已完成步骤。

---

## 3. Flag 矩阵清单

| # | Flag | 默认 | 依赖 |
|---|---|---|---|
| 1 | `v25_planning_enabled` | off | 总闸 |
| 2 | `v25_plan_context_enabled` | off | 总闸 |
| 3 | `v25_plan_step_binding_enabled` | off | 总闸 + `v24_tool_system_enabled` |
| 4 | `v25_plan_scheduler_enabled` | off | 总闸 |
| 5 | `v25_plan_execution_enabled` | off | 总闸 + scheduler + `action_enabled` |
| 6 | `v25_plan_observation_enabled` | off | 总闸 |
| 7 | `v25_plan_revision_enabled` | off | 总闸 |
| 8 | `v25_plan_memory_enabled` | off | 总闸 + `v2_memory_enabled` |
| 9 | `v25_plan_reflection_enabled` | off | 总闸 + `v2_reflection_enabled` |
| 10 | `v25_plan_world_feedback_enabled` | off | 总闸 |
| 11 | `v25_plan_autonomy_enabled` | off | 总闸 + `v21_agent_runtime_enabled` |
| 12 | `v25_plan_tool_required` | **on** | 总闸 + binding + tool_system（有效闸值判定） |
| 13 | `v25_plan_debug_enabled` | off | 总闸 |

### 串行链八条（§7.10）

| # | 链 | 违规表现 |
|---|---|---|
| ① | 任一 v25 子闸 ⇒ 总闸 | 启动 fail-fast，中文理由 |
| ② | 总闸 ⇒ `v2_autonomy_advanced_enabled` AND `v2_life_loop_enabled` | 同上 |
| ③ | execution ⇒ scheduler AND `action_enabled` | 同上 |
| ④ | binding ⇒ 总闸 AND `v24_tool_system_enabled` | 同上 |
| ⑤ | tool_required ⇒ binding AND tool_system | 同上 |
| ⑥ | reflection ⇒ 总闸 AND `v2_reflection_enabled` | 同上 |
| ⑦ | memory ⇒ 总闸 AND `v2_memory_enabled` | 同上 |
| ⑧ | autonomy ⇒ 总闸 AND `v21_agent_runtime_enabled` | 同上 |

> **计数留痕**：architecture §7.10 列八条；tasks.md 描述为「七条」（只计跨版本项）。**以 §7.10 八条为准**。
> 自动化：`test_plan012_flag_matrix.py` + `test_plan002_enablement.py`。

### 总闸 off 三重对照

1. prompt 与 V2.4.0 逐字节一致（`FROZEN_PROMPT_DIGEST`）
2. `goal_planning` / `goal_observation` / `goal_execution` 原路径生效
3. `life_loop` 九步 + `autonomy_engine.tick` 二十步形状零差异

---

## 4. Gate 判定清单（§9.6 十一条）

> **计数留痕**：architecture §9.2 表述「十个 Gate」，§9.6 表实际 **11 条**。**以 §9.6 表列为准**。

| Gate | 判定 | 证据归属 |
|---|---|---|
| **G-COMPAT** | Flag 全 off：prompt 逐字节一致；既有测试零修改；原路径生效 | `test_plan012_flag_matrix.py`、PLAN-001 flag_regression |
| **G-PLAN** | active Goal 可产出含绑定的多步计划；七道闸各有拒绝用例 | `test_plan003_engine.py`、scenario A |
| **G-DECOMPOSE** | Goal→Task→Action 三级映射可举证；粒度判据成立 | `test_plan004_*.py` |
| **G-BIND** | 每步 `tool_id` 可 resolve 且在面上；一能力多工具确定性 | `test_plan004_binding.py`、`test_plan006_gates.py` |
| **G-EXEC** | 执行经六闸门与五段短路；Planning 零直调 ToolExecutor | `test_plan005_static_scan.py`、`test_plan006_chain.py` |
| **G-RETRY** | 双层重试职责清晰；重规划不重做 done 步、不重复世界副作用 | `test_plan005_failure_tree.py`、scenario D |
| **G-WORLD** | Planning 零 `world_repository`；写世界经 outbox；终态经 event_bridge | `test_plan008_*.py` |
| **G-MEMORY** | 计划本体/中间步骤零写入 memories；终态三类各沉淀；R1~R8 零豁免 | `test_plan009_*.py` |
| **G-REFLECT** | 证据窗达门槛才产 Insight；三道闸；Insight 不直接改写计划；REPLAN 幂等 | `test_plan010_*.py` |
| **G-BOUNDARY** | Autonomy 出 intention、Planning 出 plan、Tool 出 result | `test_plan007_boundary.py` |
| **G-ZERO-MIGRATION** | 无新表/列/索引/CHECK；迁移链 0046；kind 五值 | `test_plan012_gates_and_invariants.py` |

---

## 5. 遗留问题收口清单（§9.7 十项）

| # | 问题 | 收口结论 |
|---|---|---|
| Q1 | 多步并行编排 | **不做**；`action_plan_max_steps` 保持 1 |
| Q2 | GoalPlanRecord 字段落点 | 落 `decision_records.input_snapshot`；零加列 |
| Q3 | SubGoalSpec extra 策略 | 默认 `ignore`；新字段显式入模型；双向兼容测试 |
| Q4 | tool 源 × threshold_reached | **拒绝**；负例存在 |
| Q5 | WorldIntentSubmitter 接线 | **仍 WIRED=False**；本版本不接线 |
| Q6 | PlanContext LLM 成本 | 装配侧零 LLM；**不新增** capability 位 |
| Q7 | 计划与 daily_plans | **互不引用** |
| Q8 | Insight 与 Revision 优先序 | 同时命中只入队一次（事实 > 建议） |
| Q9 | 计划完成对 Character State 间接影响 | 记录留痕；**不做**关系域扩张 |
| Q10 | 前端计划可观测面 | **仅后端 6 端点**；前端不实现 |

自动化：`test_plan012_gates_and_invariants.py::TestOpenQuestionsClosed`。

---

## 6. 边界不变量核对清单（§2.3 十条）

| # | 不变量 | 核对 |
|---|---|---|
| 1 | 不新建表、不加迁移 | 迁移链 0046；Z1~Z8 |
| 2 | 不新建 Goal 系统 | PLAN-001 差异对照 |
| 3 | 不放开 `action_plan_max_steps` | 默认 1 |
| 4 | 不绕过工具治理 | G-BIND / G-EXEC |
| 5 | 不直接写世界 / Character 域 | G-WORLD 静态扫描 |
| 6 | 不绕过记忆政策 | G-MEMORY R1~R8 |
| 7 | 反思不直接改写计划 | G-REFLECT 隔离断言 |
| 8 | 默认拒绝与降级放行沿用既有范式 | 装配降级 / 工具面 fail-closed |
| 9 | V2.4.0 兼容窗口兑现 | V9 旧读键双写 |
| 10 | Flag 全 off 逐字节一致 | G-COMPAT |

---

## 7. 复用声明核对（零新建同类系统）

| 既有系统 | 复用方式 | 零新建 |
|---|---|---|
| Agent Core / Life Loop | 挂既有维护步 | 无新 stage / Worker |
| Goal System | 只读消费 + 单一写回 | 无第二套优先级 |
| Memory System | 既有 R1~R8 + ingest | 无第二套记忆 |
| Event System | event_bridge + outbox | 无新事件类型 |
| Tool System | 规划查询 + 执行经 Action | 无第二套选择逻辑 |
| Action Engine | 唯一 `run_action_planning` | 无第二编排器 |

---

## 8. 零迁移与兼容窗口

| 项 | 期望 |
|---|---|
| 迁移链头 | `0046_tool_insight_types.py` |
| 新 Alembic revision | 0 |
| `ck_goal_plans_status` | 五值未扩 |
| `ck_decision_records_kind` | 五值未扩 |
| V9 旧读键 | `world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op` 继续双写 |
| 退役窗口 | V2.6.0（须在 V2.6.0 文档显式登记） |

---

## 9. 真实模型人工回归指引（上线前）

### 9.1 启用链（一次只开一组）

```text
V25_PLANNING_ENABLED=true
V2_AUTONOMY_ADVANCED_ENABLED=true
V2_LIFE_LOOP_ENABLED=true
→ 观察后：
V25_PLAN_CONTEXT_ENABLED=true
V25_PLAN_STEP_BINDING_ENABLED=true
V24_TOOL_SYSTEM_ENABLED=true
→ 观察后：
V25_PLAN_SCHEDULER_ENABLED=true
V25_PLAN_EXECUTION_ENABLED=true
ACTION_ENABLED=true
→ 观察后：
V25_PLAN_OBSERVATION_ENABLED=true
（可选）V25_PLAN_MEMORY / REFLECTION / WORLD_FEEDBACK / AUTONOMY / DEBUG
```

### 9.2 操作步骤

1. 配置 Flag 按 9.1 逐组开启，每组观察后再开下一组。
2. 对话触发多步目标（如「后天有个面试，帮我准备一下」）。
3. 观察 debug 端点（`v25_plan_debug_enabled=true`）：
   - 计划清单 / 单计划详情 / 步骤绑定 / 装配结果 / 修订链 / 待推进步骤
4. 验证跨 tick 单步推进与 cooldown。
5. 关闭总闸，确认行为回到 V2.4.0。
6. 执行既有工具侧与世界侧回归（`tests/v24`、世界侧既有测试）。

### 9.3 库断言速查

```sql
SELECT id, goal_id, version, status, json_array_length(sub_goals)
 FROM goal_plans WHERE goal_id = :goal_id ORDER BY version;

SELECT kind, decision, reason, created_at
 FROM decision_records
 WHERE user_id = :user_id AND kind = 'goal_lifecycle'
 ORDER BY created_at DESC LIMIT 20;

SELECT status, gate_reason, attempt
 FROM action_records WHERE user_id = :user_id
 ORDER BY created_at DESC LIMIT 20;
```

### 9.4 回滚演练

1. 全部 `v25_*` 置 off（`v25_plan_tool_required` 可留 on，但无总闸不生效）。
2. 重启进程。
3. 确认规划/执行/观测均走 V2.4.0 原路径；无数据回滚需求。

---

## 10. 执行记录

| 日期 | 执行人 | 结论 | 备注 |
|---|---|---|---|
| 2026-09-16 | Coding Agent（自动化） | 交付场景集 + Flag 矩阵 + Gate/红线/零迁移断言 + 本清单 | 真实模型人工回归待上线前执行 |
| — | — | — | — |
