# PLAN-006 Task Detail — Tool System Integration

> 上游：[../architecture.md](../architecture.md) §3.4（闸门 5/6）、§3.7（执行链）、§6.3（工具面装配）、§7.7（与 Tool System 集成）、§7.9（Action / Tool 契约行）、§5.6（状态映射）；[../tasks.md](../tasks.md) PLAN-006
> 状态：DONE（已实现，commit 05fc46e，2026-09-16）
> 范围红线：**Planning 不新增任何工具选择逻辑，不绕过任何治理闸**；工具面与执行器**零改动**；`confirm_required` 不自动绕过；V2.4.0 工具侧既有测试零失败。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-006 |
| **Task Name** | Tool System Integration |
| **Priority** | P0 |
| **Dependencies** | PLAN-005 |
| **Phase** | Phase 2 执行引擎 |
| **建议提交** | `feat: V2.5.0 Planning→Action→Tool 治理契约接线` |

## 1.1 Goal

钉死 Planning → Action → Tool 的执行契约：

1. **规划期工具面接线**：闸门 5（可解析）与闸门 6（在面上）的运行时面落地，使被裁剪 / 禁用 / 熔断 / 不可用的工具**不会进入计划**。
2. **执行期治理不绕过**：步骤执行完整经过 `action_engine` 六闸门与 `ToolExecutor` 五段短路。
3. **关键裁决落地**：Planning 不新增任何工具相关的选择逻辑——规划期是**绑定**（确定性），执行期是**决策**（`ToolSelector`），二者同一套规则、同一个函数。

## 1.2 Scope

**包含**

- 闸门 5/6 的工具状态用例集：四类工具均不进计划（`disabled` / 恒 `unavailable` / 熔断 `tripped` / 被日时段或 Run Profile 剔除）。
- 「闸门 5 过、闸门 6 拒」单列用例：断言**计划步数与内容不变**、仅该步暂不装配。
- 执行链路断言：六闸门 + 五段短路每段可观测；任一前置段失败路径**零外部调用**（含 DB 写与网络）。
- `G-EXEC` 静态断言：`app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute`。
- 授权分层：`confirm_required` 等既有确认流；`permission_denied` 不重试。
- 校验分层：规划期弱校验（必填齐备），执行期强校验（`ParamValidator.validate` 唯一权威）。
- 扩展工具一视同仁（`ext.api.*` / `user.*`）。
- 结果契约归一：`ToolResult` → `PlanStepOutcome`；`failure_kind` 取值 ⊆ 既有 `TOOL_FAILURE_KINDS`（6 值）。

**不包含（Non-Scope）**

- 工具面投影八维裁剪与 `surface_hash` 的**实现**（V2.4.0 既有 `ToolSurfaceResolver`，零改动）。
- `ToolSelector` 的 tiebreak 规则（V2.4.0 既有，PLAN-004 复用）。
- 工具绑定（规划期）的实现（属 PLAN-004）。
- 计划调度 / 执行桥接 / 观测推进 / 修订的**本体实现**（属 PLAN-005；本任务只做**契约与断言**，并补齐工具治理相关的判定细节）。
- 工具健康度熔断机制（V2.4.0 既有 `ToolHealthTracker`，零改动）。
- 世界写入路径（属 PLAN-008）。

## 1.3 本任务解决什么问题

architecture §7.7 的关键裁决是：**Planning 不新增任何工具选择逻辑**。这条裁决若不单列任务交付，实现期极易发生两类退化：

| 退化 | 后果 | 本任务的守卫 |
|---|---|---|
| 在 `TaskDecomposer` 里自造一套工具排序规则 | 规划期绑定与执行期选择产生分歧，计划里的 `tool_id` 与真正执行的工具不一致 | 契约对照用例（§9.2 I7） |
| 在 `PlanExecutorBridge` 里直调 `ToolExecutor` 图快 | 绕过六闸门（额度 / 幂等 / 参数歧义）与五段短路（授权 / 校验），治理被稀释 | `G-EXEC` 静态断言（§10.3） |

同时本任务把**四类工具不进计划**与**「闸门 5 过、闸门 6 拒」**做成可判定用例——这是 architecture §1.3 断层 B3 / B4 关闭的最终证据。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Tool System V2.4.0** | **零改动**：`ToolRegistry` / `ToolSurfaceResolver` / `ToolSelector` / `ToolExecutor` / `ToolPermissionGate` / `ParamValidator` / `ToolHealthTracker` / `ToolResult` 全部复用 |
| **Action Engine（V9 / V2.4.0）** | **零改动**：`run_action_planning` 六闸门 + `assemble_plan` + `execute_plan` + `integrate_result` |
| **Memory 2.0 / Reflection** | **不涉及**（记忆边界属 PLAN-009，证据窗属 PLAN-010） |
| **Autonomy 2.0** | **不涉及**（额度数学未被本任务改动） |
| **World Simulation** | **不涉及**（世界写入属 PLAN-008） |

**关键事实（已核对真实源码）**

- `app/services/tool/registry.py`：`ToolRegistry.resolve(tool_id)`、`ToolDescriptor`、`TOOL_ID_PATTERN = ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$`、`TOOL_HEALTH_WINDOW_SIZE = 10`、`register_builtin_tools`、`get_tool_registry()`。
- `app/services/tool/surface.py`：`ToolSurfaceResolver` / `ToolSurfacePolicy` / `ToolSelector.select_with_reason` / `surface_hash` / `DEFAULT_SURFACE_MAX_TOOLS = 12`；裁剪理由前缀 `tool_status` / `run_profile` / `part_of_day` / `scene` / `relationship_stage` / `world_unavailable` / `world_disabled` / `surface_limit`；`STATUS_LABELS = ("disabled", "deprecated", "removed", "tripped")`；`TOOL_UNAVAILABLE_TOOL_IDS` 在 resolve 时被剔除。
- 十个内置工具：`builtin.reminder.create` / `builtin.reminder.cancel` / `builtin.memory.save` / `builtin.notification.send` / `builtin.search.query`（恒 `unavailable`）/ `world.object.create` / `world.object.move` / `world.object.use` / `world.env.query` / `channel.feishu.send`。
- `app/services/tool/executor.py`：`ToolExecutor.run` 五段短路（resolve → permission → validate → invoke → normalize）；`resolve_step_binding(registry, step)`；`PERMISSION_ALLOW` / `PERMISSION_DENY` / `PERMISSION_CONFIRM_REQUIRED`；`_TERMINAL_ERRORS`。
- `app/services/tool/permission.py`：`ToolPermissionGate` → `allow` / `confirm_required` / `deny`。
- `app/services/tool/validator.py`：`ParamValidator.validate`（结构 + 语义，**唯一权威**）。
- `app/services/tool/health.py`：`ToolHealthTracker`（熔断 → `tripped`）。
- `app/services/tool/confirmation.py` + `app/application/action_engine.py::run_confirmation_round` / `_resume_confirmed_record` / `_pending_confirmation_record`：既有确认流。
- `app/application/action_engine.py`：`GATE_REASON_PENDING_CONFIRMATION = "pending_confirmation"` / `GATE_REASON_PERMISSION_DENIED = "permission_denied"`；`_TOOL_STEP_STATUSES` / `_TOOL_RECORD_OUTCOMES` / `_TOOL_ACTION_FAILURE_KINDS` 三张映射表（V2.4.0 建立的 `ToolResult → ActionRecord` 契约）。
- `app/models/tool.py::TOOL_FAILURE_KINDS`（6 值：`transient` / `permanent` / `timeout` / `unavailable` / `denied` / `invalid`）、`TOOL_EFFECT_KINDS`（5 值）。
- `app/services/action/planner.py::evaluate_gates` 六闸门：`disabled` / `ambiguous_params` / `capability_unavailable` / `duplicate` / `quota_exceeded` / `effect_already_satisfied`。

## 2.2 为什么需要本任务

V2.4.0 的定位是「给手装权限锁」，本版本的定位是「给手接上大脑的意图链」。接线过程中最危险的一步就是**为了省事而绕过锁**：计划层若直调 `ToolExecutor`，六闸门与五段短路的全部治理（额度、幂等、授权、校验、健康度）都会被稀释。

tasks.md §6 追溯矩阵明确把「散落在 §3.4 闸门 5/6 与 §7.7 的工具治理契约」独立成 PLAN-006，目的就是**避免工具治理在计划层被稀释**。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 闸门 5（工具可解析）的运行时面与工具状态用例 | 用例集 + 判定接线 |
| R2 | 闸门 6（工具在面上）的运行时面与裁剪维度用例 | 用例集 + 判定接线 |
| R3 | 四类工具不进计划的可判定证据（`disabled` / 恒 `unavailable` / `tripped` / 被时段或 Run Profile 剔除） | 用例集 |
| R4 | 「闸门 5 过、闸门 6 拒」单列用例（计划步数与内容不变） | 专项用例 |
| R5 | 执行链路断言（六闸门 + 五段短路每段可观测；前置段失败零外部调用） | 链路断言 |
| R6 | `G-EXEC` 静态断言 | 静态扫描测试 |
| R7 | 授权分层（`confirm_required` 等既有确认流；`permission_denied` 不重试） | 契约 + 用例 |
| R8 | 校验分层（规划期弱校验 vs 执行期强校验） | 契约 + 用例 |
| R9 | 扩展工具一视同仁（`ext.api.*` / `user.*`） | 用例 |
| R10 | 结果契约归一（`ToolResult → PlanStepOutcome`，`failure_kind` 不新增值） | 契约表 + 用例 |
| R11 | 工具面投影八维裁剪理由可解释、`surface_hash` 同输入同输出 | 用例 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | 工具绑定（能力 → `tool_id` 的确定性映射） | PLAN-004 |
| N2 | 六源装配 | PLAN-003 |
| N3 | 闸门 1~4 / 7 与七道闸调度 | PLAN-003 |
| N4 | 计划调度 / 执行桥接 / 观测 / 修订的本体实现 | PLAN-005 |
| N5 | 工具面 / 选择器 / 执行器 / 健康度 / 确认流的**任何改动** | **永不**（V2.4.0 冻结） |
| N6 | 记忆边界表与工具侧 deposit 决策 | PLAN-009 |
| N7 | 世界写入路径与终态广播 | PLAN-008 |
| N8 | 自治侧额度数学 | PLAN-007（本任务只断言「未放宽」） |

## 3.3 职责边界一句话

> **本任务不发明任何工具规则，只保证既有的规则在计划链路里不被稀释：规划期照面绑定，执行期照锁执行。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

本任务**不新建模块**。它是对 PLAN-003（闸门 5/6）与 PLAN-005（执行桥接）的**契约补齐与断言加固**，涉及文件：

| 文件 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/engine.py`（PLAN-003） | 已有 | 补齐闸门 5/6 的工具状态判定细节 | → `ToolRegistry.resolve`（只读） |
| `app/services/planning/executor_bridge.py`（PLAN-005） | 已有 | 补齐面复核与结果归一的工具状态映射 | → `action_engine.run_action_planning`（唯一入口） |
| `app/services/tool/*` | V2.4.0 既有 | **零改动** | 被 Planning 只读消费 |
| `app/application/action_engine.py` | V9 / V2.4.0 既有 | **零改动** | 被 Planning 唯一调用 |

**分层纪律（静态断言强制）**
- `app/services/planning/` 零直调 `ToolExecutor.run` / `Capability.execute`（G-EXEC）。
- `app/services/planning/` 零写入工具注册表 / 健康度（只读消费，注册表快照必须不变）。
- `app/services/planning/` 零自造工具排序 / 过滤规则（只调 `ToolRegistry.resolve` 与 `ToolSelector.select_with_reason`，不自建规则）。

### 4.1.2 Component 划分

```text
规划期（PLAN-003 闸门 5/6 + PLAN-004 绑定）
├── 闸门 5：ToolRegistry.resolve(tool_id) 必须成功              「这个工具存在吗」（声明面）
└── 闸门 6：tool_id ∈ ctx.tool_surface.tool_ids                 「这一刻它能用吗」（运行时面）
        ├── 面来自 ToolSurfaceResolver.resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx)
        └── 面已剔除：disabled / deprecated / removed / tripped / 恒 unavailable
                      / run_profile 不符 / part_of_day 不符 / scene 不符
                      / relationship_stage 不符 / world 不可用 / surface_limit

执行期（PLAN-005 执行桥 + 既有 Action 编排器）
├── PlanExecutorBridge.execute_step
│     ├── A2 面复核（防御性，非第二次决策）
│     └── action_engine.run_action_planning（唯一执行入口）
│           ├── 六闸门：disabled / ambiguous_params / capability_unavailable
│           │           / duplicate / quota_exceeded / effect_already_satisfied
│           ├── assemble_plan → ToolSurface → ToolSelector.select_with_reason
│           ├── ToolExecutor.run（五段短路）
│           │     resolve → permission → validate → invoke → normalize
│           └── integrate_result（四通道）
└── ToolResult → PlanStepOutcome 归一（白名单裁剪 observations）
```

### 4.1.3 数据流：一次步骤执行的治理链路

```text
PlanStepSpec{tool_id, params, expected_effects, observation_keys}
        │
        ▼ ① 规划期已过闸（闸门 5/6 在计划生成时完成）
        │
        ▼ ② 执行期（本任务的核心契约面）
PlanExecutorBridge.to_intent → ActionIntent{action_type, params, dedupe_key, source="autonomy"}
        │
        ▼
action_engine.run_action_planning
        ├─ new_record → ActionRecord(status=created)
        ├─ evaluate_gates（六闸门）
        │     任一不过 → record.status="cancelled" + record.gate_reason=理由 → 落库 → 返回
        │     ★ 此后零外部调用（含 DB 写与网络）
        ├─ assemble_plan → _assemble_plan_via_tools → ToolSurface → ToolSelector
        │     装配失败 → status="cancelled" + gate_reason="capability_unavailable"
        ├─ execute_plan → ToolExecutor.run（五段短路）
        │     resolve  ✗ → 终态错误（不 invoke）
        │     permission ✗ deny → PERMISSION_DENY（不 invoke）
        │     permission ~ confirm_required → 登记确认流 + 不 invoke
        │     validate ✗ → 终态错误（不 invoke）
        │     invoke → normalize
        └─ integrate_result（world via outbox / memory / relationship / note）
        ▼
ActionRecord{status, steps[0].result=ToolResult, attempt, next_retry_at}
        ▼
PlanExecutorBridge 归一 → PlanStepOutcome{status, tool_id, failure_kind, effects, observations}
```

## 4.2 Core Model

本任务**不新增模型**。下表为工具治理侧的契约表。

### 4.2.1 工具面裁剪维度（八维，V2.4.0 既有，本任务只消费）

| 维度 | 理由前缀（既有常量） | 对计划的影响 |
|---|---|---|
| 工具状态 | `tool_status`（`disabled` / `deprecated` / `removed` / `tripped`） | 闸门 6 拒 → 该步不进计划 |
| Run Profile | `run_profile` | 闸门 6 拒 → 该步不进计划 |
| 日时段 | `part_of_day` | 闸门 6 拒 → **计划的步数与内容不变**，仅该步暂不装配 |
| 场景 | `scene` | 同上 |
| 关系阶段 | `relationship_stage` | 同上 |
| 世界不可用 | `world_unavailable` | 同上 |
| 世界关闭 | `world_disabled` | 同上 |
| 面上限 | `surface_limit` | 面被截断，多余工具暂不在面 |

> 每条 `excluded` 携带 reason（既有 `ToolSurface.excluded`）；`surface_hash` 同输入同输出。

### 4.2.2 四类「不进计划」的工具（本任务的可判定清单）

| # | 类型 | 判据 | 拒在哪一闸 | 例 |
|---|---|---|---|---|
| T1 | `disabled`（运行期禁用） | 面裁剪（`tool_status:disabled`） | 闸门 6 | 运维禁用某工具（`v24_tool_disabled_ids`） |
| T2 | 恒 `unavailable` | `TOOL_UNAVAILABLE_TOOL_IDS` 裁剪 | 闸门 6 | `builtin.search.query` |
| T3 | 熔断 `tripped` | 健康度熔断（`tool_status:tripped`） | 闸门 6 | 连续失败的 `world.env.query` |
| T4 | 被日时段 / Run Profile 剔除 | 面裁剪（`part_of_day` / `run_profile`） | 闸门 6 | `channel.feishu.send` 在 `late_night`；`channel.*` 在自治面 |

**闸门 5 vs 闸门 6 的证据要求（本任务的评审要点）**

| 场景 | 闸门 5 | 闸门 6 | 计划的最终形态 |
|---|---|---|---|
| 工具已注册且在面上 | 过 | 过 | 该步正常装配 |
| 工具**未注册** | **拒** | —（不到） | 计划 `rejected`（`plan_tool_unresolvable`） |
| 工具已注册但不在面上 | **过** | **拒** | **计划步数与内容不变**；仅该步暂不装配（等面恢复） |

> **本任务必须单列「闸门 5 过、闸门 6 拒」用例**，并断言「计划步数与内容不变、仅该步暂不装配」——这是 architecture §3.4 对该闸门差异的明确要求。

### 4.2.3 六闸门（执行期，V9 / V2.4.0 既有，本任务断言其经过性）

| # | 闸门 | 依据 | 不过时 |
|---|---|---|---|
| 1 | `disabled` | `action_enabled` / 工具状态 | `record.status="cancelled"`，`gate_reason="disabled"` |
| 2 | `ambiguous_params` | 参数歧义 | `gate_reason="ambiguous_params"` |
| 3 | `capability_unavailable` | 能力不可用 | `gate_reason="capability_unavailable"` |
| 4 | `duplicate` | `dedupe_key` 命中（`action_dedupe_window_hours`） | `gate_reason="duplicate"` |
| 5 | `quota_exceeded` | 额度（`action_max_active_per_user` 等） | `gate_reason="quota_exceeded"` |
| 6 | `effect_already_satisfied` | 效果已达成 | `gate_reason="effect_already_satisfied"` |

### 4.2.4 五段短路（`ToolExecutor.run`，V2.4.0 既有，本任务断言其经过性）

| # | 段 | 失败时的行为 |
|---|---|---|
| 1 | `resolve` | 绑定失败 → 终态错误，**不 invoke** |
| 2 | `permission` | `deny` → `PERMISSION_DENY`，**不 invoke**；`confirm_required` → 登记确认流，**不 invoke** |
| 3 | `validate` | 结构 / 语义非法 → 终态错误，**不 invoke** |
| 4 | `invoke` | 真实外部调用 |
| 5 | `normalize` | 归一为 `ToolResult` |

### 4.2.5 授权与校验分层（本任务的契约）

| 层 | 规划期（本任务） | 执行期（既有，唯一权威） |
|---|---|---|
| 参数校验 | **弱校验**：必填齐备 | **强校验**：`ParamValidator.validate`（结构 + 语义） |
| 授权 | 不裁决 | `ToolPermissionGate.evaluate` → `allow` / `confirm_required` / `deny` |
| `confirm_required` | 不预判 | 等既有确认流（`services/tool/confirmation.py` + `run_confirmation_round`） |
| `permission_denied` | 不预判 | `blocked` → `step.failed`；**不重试**（授权拒绝非瞬时） |
| 弱校验不过 | 该步在**规划期即被拒** | — |

### 4.2.6 结果契约（`ToolResult → PlanStepOutcome`）

| `ToolResult` 字段 | `PlanStepOutcome` 字段 | 归一规则 |
|---|---|---|
| `status` | `status` | `succeeded` / `failed` / `timeout` / `unavailable` / `denied` / `invalid` / `pending_confirmation` → 六态映射（PLAN-005 §4.3.4） |
| `effects` | `effects` | 投影 `kind` / `ref` / `reversible`；取值 ⊆ `TOOL_EFFECT_KINDS`（5 值） |
| `observations` | `observations` | **按 `step.observation_keys` 白名单裁剪** |
| `failure_kind` | `failure_kind` | 取值即既有 `TOOL_FAILURE_KINDS`（6 值），**不新增** |
| `usage` | `duration_ms` / `attempt` | 既有 usage 投影 |
| `error` / `redacted` / `raw_error` | — | 不进 `PlanStepOutcome`（脱敏后只进 Action 台账） |

**`tool_id` 字段的差异回填**：`PlanStepOutcome.tool_id` 取**实际执行**的工具（`ActionRecord.steps[0].tool_id`），可能与计划绑定的 `tool_id` 不同（如执行期 `ToolSelector` 因收件人偏好选了另一个）——差异进审计，不视为错误。

### 4.2.7 扩展工具（一视同仁）

| 命名空间 | 权限下限（既有） | 本任务 |
|---|---|---|
| `ext.api.*` | `sensitive` | 只要在面上且可解析即可被规划，**不设特判** |
| `user.*` | `dangerous` | 同上 |

> 纪律：Planning **不为扩展工具设任何特殊分支**。扩展工具的可规划性完全由既有面投影与权限门决定。

## 4.3 State Machine

本任务**不新增状态机**。下为本任务涉及的既有状态与其在计划链路中的体现。

### 4.3.1 工具生命周期（V2.4.0 既有）与计划的交互

```text
enabled ──disable──► disabled ──enable──► enabled
   │                     │
   │ deprecate           │ deprecate
   ▼                     ▼
deprecated ──────────────────────► removed
   ▲
   └── 运行期熔断（健康度）：tripped 作为「运行期状态标签」叠加在生命周期之上，
       经工具面裁剪（tool_status:tripped）从面剔除 → 闸门 6 拒
```

| 工具状态 | 在面上 | 闸门 5 | 闸门 6 | 计划的最终形态 |
|---|---|---|---|---|
| `enabled` 且无裁剪 | ✅ | 过 | 过 | 正常装配 |
| `enabled` 但被时段 / Profile 裁剪 | ❌ | 过 | **拒** | 步数与内容不变，暂不装配该步 |
| `disabled` / `deprecated` / `removed` | ❌ | 过（已注册） | **拒** | 同上 |
| 恒 `unavailable` | ❌ | 过（已注册） | **拒** | 同上 |
| 熔断 `tripped` | ❌ | 过（已注册） | **拒** | 同上 |
| 未注册 | — | **拒** | —（不到） | 计划 `rejected`（`plan_tool_unresolvable`） |

### 4.3.2 `ToolExecutionStatus`（7 值，既有）与步骤终态的映射

| `ToolExecutionStatus` | `ActionRecord.status` | `PlanStepOutcome.status` |
|---|---|---|
| `succeeded` | `succeeded` | `succeeded` |
| `failed` | `failed` | `failed` |
| `timeout` | `failed` | `timeout` |
| `unavailable` | `cancelled` | `blocked`（`gate_reason="capability_unavailable"`） |
| `denied` | `cancelled` | `blocked`（`gate_reason="permission_denied"`） |
| `invalid` | `cancelled` | `blocked`（`gate_reason="invalid_params"`） |
| `pending_confirmation` | `planned`（等确认） | `blocked`（`gate_reason="pending_confirmation"`） |

> **不新增 `ActionStatus` 值，不新增 `GATE_REASONS` 值**（V9 六态 + V2.4.0 已扩十值已完备）。

### 4.3.3 `confirm_required` 状态流转（三条路径）

```text
步骤执行 → permission=confirm_required
        │
        ├─ 登记确认流（_register_confirmation，既有）
        ├─ ActionRecord.status = "planned"（不 invoke，零外部调用）
        └─ PlanStepOutcome.status = "blocked"（gate_reason="pending_confirmation"）
             │
             ├─ ① 用户批准 → action_engine 续跑（_resume_confirmed_record）
             │        · 参数与幂等键复用原调用 → 回 succeeded 分支
             └─ ② 用户否定 / ③ TTL 过期（_expire_pending_confirmations）
                      → ActionRecord 终态 failed → step.failed
```

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 额度数学 | `action_max_active_per_user` / `autonomy_action_daily_limit` / `autonomy_min_interval_minutes` 属既有 | **断言未放宽**（负例：额度耗尽时步骤不执行、不产生 `ActionRecord`） |
| `quota_exceeded` 闸门 | 六闸门之一 | **断言经过性** |
| `plan_facts` / 候选面 | PLAN-007 | **不涉及** |

**为什么只断言不放宽**：计划触发的执行走既有编排器入口，额度天然生效；本任务的价值是**把「不得成为绕过额度的后门」变成可判定负例**（architecture §7.3 接线 3 的评审红线）。

## 5.2 与 Tool System

**本任务的核心。**

| 关注点 | Tool System（V2.4.0，零改动） | 本任务 |
|---|---|---|
| 工具身份 | `ToolDefinition.id` | 步骤 `tool_id` 指向它 |
| 解析 | `ToolRegistry.resolve(tool_id)` → `ToolBinding` | 闸门 5 消费 |
| 可用性 | `ToolSurfaceResolver.resolve(run_kind, ctx)` → `ToolSurface{tool_ids, excluded, surface_hash}` | 闸门 6 消费 |
| 选择 | `ToolSelector.select_with_reason(intent, surface)` | 执行期由 `assemble_plan` 内部调用（Planning **不重复选择**） |
| 授权 | `ToolPermissionGate.evaluate` → `allow` / `confirm_required` / `deny` | 步骤遇 `confirm_required` → 等既有确认流 |
| 校验 | `ParamValidator.validate`（结构 + 语义，唯一权威） | 规划期只做弱校验 |
| 执行 | `ToolExecutor.run` 五段短路 | 经 `action_engine` 间接调用（**不直调**） |
| 结果 | `ToolResult{status, effects, observations, failure_kind, usage, error, redacted, raw_error}` | 归一为 `PlanStepOutcome` |
| 健康度 | `ToolHealthTracker`（熔断） | 熔断工具经面剔除 → 闸门 6 自动拒 |
| 扩展 | `ext.api.*` / `user.*` | 一视同仁，不设特判 |
| 确认流 | `services/tool/confirmation.py` + `run_confirmation_round` | 步骤遇 `confirm_required` 等既有确认流，**不自动绕过** |

**关键裁决（architecture §7.7）**：计划期的「选哪个工具」是**绑定**（`TaskDecomposer`，确定性，一能力多工具时按 `ToolSelector` 的确定性规则）；执行期的「选哪个工具」是**决策**（`ToolSelector` 在真实 intent 与真实面上）。二者用**同一套规则、同一个函数**，因此不会产生分歧。

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `world_unavailable` / `world_disabled` 面裁剪维度 | 世界不可用时相关工具被面剔除 | **消费**（断言 `world.*` 工具在世界关闭时不进计划） |
| 计划写世界（`deferred_world_op` → outbox） | PLAN-008 | **不涉及** |

**为什么不涉及**：本任务只关心「世界关闭时 `world.*` 工具是否被正确剔除」——这是**工具面消费**，不是世界写入。写入路径属 PLAN-008。

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 工具侧 deposit 决策（`TOOL_MEMORY_TEMPLATES` / `services/tool/memory_policy.py`） | V2.4.0 既有 `BOUNDARY_TABLE` | **零改动、不覆盖**（本任务的执行链不修改工具记忆决策） |
| 计划终态记忆 | PLAN-009 | **不涉及** |

**为什么不涉及**：工具这次的调用「值不值得记住」由工具侧边界表决定，属 PLAN-009 的判据 C；本任务只保证执行链不改写该决策。

## 5.5 与 Reflection

**完全不涉及。**

| 关注点 | 本任务 | 原因 |
|---|---|---|
| 工具证据窗（`GROUP_KIND_TOOL` / `GROUP_KIND_FAILURE`） | 数据由既有 `action_records.steps` 提供 | 证据窗聚合属 PLAN-010 |
| 熔断与健康度可观测 | V2.4.0 既有通道 | 本任务不改 |

## 5.6 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 七道闸 | 不涉及（闸门 5/6 的实现属 PLAN-003，本任务补判定细节与用例） | PLAN-003 |
| 工具绑定 | 不涉及 | PLAN-004 |
| 调度 / 观测 / 修订本体 | 不涉及（本任务只补执行桥的治理细节） | PLAN-005 |
| outbox / `event_bridge` | 不涉及 | PLAN-008 |
| `memories` / `memory_policy` | 不涉及 | PLAN-009 |
| `reflection/evidence.py` | 不涉及 | PLAN-010 |
| `PolicySnapshot` | 不涉及 | PLAN-007 |

---

# 6. API / Interface Design

本任务不新增公开接口；下表为**被本任务加固的既有接口契约**。

## 6.1 规划期闸门接口（PLAN-003 的 `PlanningEngine` 内部）

```text
_evaluate_tool_resolvable(steps, registry) -> str | None      # 闸门 5
    # 对每个 kind="tool" 且 tool_id 非空的步骤调 ToolRegistry.resolve(tool_id)
    # 任一失败 → 返回 "plan_tool_unresolvable"；全通过 → None

_evaluate_tool_on_surface(steps, surface) -> str | None       # 闸门 6
    # 对每个 kind="tool" 且 tool_id 非空的步骤校验 tool_id ∈ surface.tool_ids
    # 任一不在面 → 返回 "plan_tool_off_surface"；全通过 → None
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 闸门 5 只调 `ToolRegistry.resolve`（只读），**零注册表改动** | 注册表快照对照 |
| D2 | 闸门 6 只读 `surface.tool_ids`，**零面重算**（不自行调用 `ToolSurfaceResolver`） | 静态断言 |
| D3 | 闸门 5/6 分别可独立关闭（受 `v25_plan_step_binding_enabled` 门控） | 开关用例 |
| D4 | 「闸门 5 过、闸门 6 拒」时计划步数与内容不变 | 专项用例（§9.1 U4） |

## 6.2 执行期桥接接口（PLAN-005 的 `PlanExecutorBridge` 内部）

```text
_surface_recheck(step, ctx) -> bool          # A2 面复核（防御性）
    # step.tool_id ∈ ToolSurfaceResolver.resolve(RUN_KIND_AUTONOMOUS_TICK, tool_ctx).tool_ids

_normalize_result(record, step) -> PlanStepOutcome
    # 读 record.steps[0].result（ToolResult）
    # status → 六态；failure_kind → 既有六值；observations → 按 observation_keys 裁剪
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D5 | `execute_step` **只**经 `action_engine.run_action_planning`；**不得**直调 `ToolExecutor.run` / `Capability.execute` | 静态断言（G-EXEC） |
| D6 | A2 面复核是**防御性断言**，不是第二次决策（不改变计划内容，不选择工具） | 用例断言：复核失败 → `outcome.status="blocked"`，计划不改 |
| D7 | `observations` 只保留 `observation_keys` 声明的键 | 用例断言 |
| D8 | `failure_kind` 取值全部 ⊆ `TOOL_FAILURE_KINDS`（6 值） | 值集快照对照 |

## 6.3 链路断言契约（本任务交付的可判定证据）

| # | 断言 | 判定方式 |
|---|---|---|
| L1 | 一次步骤执行完整经过**六闸门** | 打桩：六个闸门判定函数各被调用一次（顺序固定） |
| L2 | 一次步骤执行完整经过**五段短路** | 打桩：`resolve` → `permission` → `validate` → `invoke` → `normalize` 顺序固定、各一次 |
| L3 | 任一**前置段失败路径零外部调用** | 打桩断言：含 DB 写与网络调用（`invoke` 未被触达） |
| L4 | `permission=confirm_required` 时**零外部调用** | 打桩断言（`invoke` 未被触达）+ 确认流已登记 |
| L5 | 规划期弱校验不过的步骤**不进入执行** | 用例：不产生 `ActionRecord` |

## 6.4 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| 工具解析失败（`resolve` 段） | `ToolExecutor` | 终态错误；`PlanStepOutcome.status="failed"`（`failure_kind="permanent"`） |
| 授权 `deny` | `ToolPermissionGate` | `blocked`（`gate_reason="permission_denied"`）→ `step.failed`；**不重试** |
| 授权 `confirm_required` | `ToolPermissionGate` | `blocked`（`gate_reason="pending_confirmation"`）→ 等既有确认流 |
| 参数校验非法 | `ParamValidator` | `blocked`（`gate_reason="invalid_params"`）→ `step.failed`（`permanent`） |
| 工具熔断（`tripped`） | `ToolHealthTracker` | 该工具被面剔除 → 闸门 6 拒（规划期）或 `capability_unavailable`（执行期 A2） |
| 扩展工具权限不足 | `ToolPermissionGate` | 同上（按既有权限门处置，Planning 不特判） |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 工具执行台账复用 `action_records.steps`（V2.4.0 已含 `tool_id` / `permission` / `validation`） |
| 新列 | 无 | 工具面投影（`ToolSurface`）是内存值对象，进 trace；确认流状态复用既有 `action_records.status` / `gate_reason` |
| 新索引 | 无 | 工具相关查询由既有索引覆盖（`action_records.dedupe_key` / `user_id+status`） |
| 改 CHECK | 无 | `ActionStatus` 值集不变；`GATE_REASONS` 值集不变（V2.4.0 已扩十值） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| 工具执行台账 | `action_records.steps` | `action_engine.execute_plan` / `action_repository.save_record` | ❌ |
| 确认流状态 | `action_records.status` / `gate_reason` | `action_engine._register_confirmation` / `run_confirmation_round` | ❌ |
| 世界副作用 | `action_records` + outbox | `action_repository.save_record_with_outbox`（经工具效果） | ❌ |

> **本任务不自建任何表**：工具治理的持久化完全复用 V9 / V2.4.0 既有台账。若实现期发现需要为「计划-工具绑定」建表，说明 architecture §4.9 裁决被违背，须回退重审。

---

# 8. Implementation Plan

## Step 1 — 闸门 5/6 判定细节补齐

1. 闸门 5：对 `kind="tool"` 且 `tool_id` 非空的步骤逐一调 `ToolRegistry.resolve(tool_id)`；任一失败 → `plan_tool_unresolvable`。
2. 闸门 6：对同类步骤校验 `tool_id ∈ ctx.tool_surface.tool_ids`；任一不在面 → `plan_tool_off_surface`。
3. 两个闸门分别受 `v25_plan_step_binding_enabled` 门控，可独立关闭。
4. 断言闸门 5 零注册表改动（快照对照）；闸门 6 零面重算（不自行调 `ToolSurfaceResolver`）。
5. 单测：闸门 5 负例（未注册 `tool_id`）；闸门 6 负例（`builtin.search.query` / `late_night` 下的 `channel.feishu.send`）。

## Step 2 — 四类工具不进计划的用例集（T1~T4）

1. T1 `disabled`：设置 `v24_tool_disabled_ids` 禁用某工具 → 断言其不在面且不进计划。
2. T2 恒 `unavailable`：`builtin.search.query` → 断言被 `TOOL_UNAVAILABLE_TOOL_IDS` 剔除。
3. T3 熔断 `tripped`：打桩使工具连续失败触发熔断 → 断言 `tool_status:tripped` 裁剪生效。
4. T4 时段 / Profile 剔除：`late_night` 下的 `channel.*`；自治面下的 `channel.*`。
5. 每条断言 `excluded` 携带正确 reason 前缀。

## Step 3 — 「闸门 5 过、闸门 6 拒」专项用例

1. 构造：工具已注册（闸门 5 可解析）但被时段剔除（闸门 6 不在面）。
2. 断言：闸门 5 返回 `None`（过），闸门 6 返回 `plan_tool_off_surface`（拒）。
3. **断言计划的步数与内容不变**——仅该步暂不装配；恢复面后该步可装配。
4. 断言两闸门分别独立关闭时的行为差异。

## Step 4 — 执行链路断言（六闸门 + 五段短路）

1. 对六闸门判定函数打桩，断言顺序固定、各调用一次。
2. 对 `ToolExecutor.run` 五段打桩，断言顺序固定、各调用一次。
3. **前置段失败零外部调用**：对每一段注入失败，断言 `invoke` 未被触达，且无 DB 写（`action_records` 除既有记录外无新增）与无网络调用。
4. `confirm_required`：断言 `invoke` 未触达 + 确认流已登记 + `ActionRecord.status="planned"`。
5. 单测：L1~L5 五条断言各自可判定。

## Step 5 — 静态断言加固（G-EXEC）

1. 扫描 `app/services/planning/`：零 `ToolExecutor` 导入 / 零 `Capability.execute` 调用 / 零 `ToolHealthTracker` 写方法调用 / 零工具注册表写方法调用。
2. 断言 `services/planning/` 零自造工具排序或过滤规则（不新增 `sorted(...)` 类工具排序常量）。
3. 断言执行入口唯一：`action_engine.run_action_planning` 是 `services/planning/` 唯一触达 Action 层的函数。

## Step 6 — 授权 / 校验分层落地

1. 规划期弱校验：断言必填齐备（不校验类型 / 格式 / 语义）。
2. 执行期强校验：断言 `ParamValidator.validate` 是唯一权威（本任务零二次校验）。
3. `confirm_required` 三条路径：批准续跑（参数与幂等键复用）/ 否定转 `failed` / TTL 过期转 `failed`。
4. `permission_denied`：断言不重试（`attempt` 不增加）。

## Step 7 — 扩展工具与权限下限

1. `ext.api.*` / `user.*` 在面上且可解析时可被规划（用例）。
2. 断言 Planning 对扩展工具**零特判分支**（静态：`planning/` 零 `ext.api` / `user` 字符串判断）。

## Step 8 — 结果契约归一与回归

1. `ToolResult → PlanStepOutcome` 归一：状态映射七行、`failure_kind` 六值、`effects` 投影、`observations` 白名单裁剪。
2. `tool_id` 差异回填进审计（执行工具与计划绑定不一致时）。
3. 回归：V2.4.0 工具侧既有测试零失败（注册表 / 面投影 / 选择器 / 执行器 / 健康度 / 确认流契约未被改动）。
4. Flag off 时工具面不参与规划（`SubGoalSpec.tool_id` 不写），绑定只在执行期由 `ToolSelector` 发生，行为与 V2.4.0 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 闸门 5 可解析判定 | 未注册 `tool_id` → `plan_tool_unresolvable`；已注册 → `None` |
| U2 | 闸门 6 在面上判定 | 不在面 → `plan_tool_off_surface`；在面 → `None` |
| U3 | 两闸门独立关闭 | `v25_plan_step_binding_enabled` off 时两闸门均不生效 |
| U4 | **「闸门 5 过、闸门 6 拒」单列** | 闸门 5 返回 `None`、闸门 6 拒；**计划步数与内容不变**；该步暂不装配（恢复面后可装配） |
| U5 | T1 `disabled` | 面裁剪 `tool_status:disabled`；工具不进计划 |
| U6 | T2 恒 `unavailable` | `TOOL_UNAVAILABLE_TOOL_IDS` 剔除生效 |
| U7 | T3 熔断 `tripped` | 健康度熔断 → 面裁剪 `tool_status:tripped`；工具不进计划 |
| U8 | T4 时段 / Profile | `late_night` 下 `channel.*` 被剔除；自治面下 `channel.*` 被剔除 |
| U9 | 面裁剪理由可解释 | 每条 `excluded` 携带 reason，前缀与维度对应 |
| U10 | `surface_hash` 稳定 | 同输入同输出 |
| U11 | 状态映射七行 | `ToolExecutionStatus` → `ActionRecord.status` → `PlanStepOutcome.status` 与 §4.3.2 逐行一致 |
| U12 | `failure_kind` 值域 | 全部 ⊆ `TOOL_FAILURE_KINDS`（6 值） |
| U13 | `observations` 白名单裁剪 | 未在 `observation_keys` 声明的键不可见 |
| U14 | 扩展工具可规划 | `ext.api.*` / `user.*` 在面上且可解析时可进计划 |
| U15 | 规划期弱校验 | 必填缺失 → 规划期被拒（不进入执行） |
| U16 | `tool_id` 差异回填 | 执行工具 ≠ 计划绑定时，差异进审计且不视为错误 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **链路断言 L1** | 六闸门各被调用一次，顺序固定 |
| I2 | **链路断言 L2** | 五段短路顺序固定、各一次 |
| I3 | **零外部调用 L3** | 任一前置段失败 → `invoke` 未触达；零 DB 写（除既有记录）；零网络调用 |
| I4 | **零外部调用 L4** | `confirm_required` → `invoke` 未触达；`ActionRecord.status="planned"` |
| I5 | **G-EXEC 静态断言** | `app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute` |
| I6 | 注册表零改动 | 闸门 5 调用前后注册表快照一致 |
| I7 | **绑定与选择一致** | 规划期绑定结果与执行期 `ToolSelector.select_with_reason` 结果一致（同函数同规则） |
| I8 | `confirm_required` 三路径 | 批准续跑（参数与幂等键复用原调用）/ 否定转 `failed` / TTL 过期转 `failed` |
| I9 | `permission_denied` 不重试 | `attempt` 不增加；无重试记录 |
| I10 | 额度未放宽 | `action_max_active_per_user` 生效；额度耗尽时步骤不执行、不产生 `ActionRecord` |
| I11 | Action 值集未扩 | `ActionStatus` / `GATE_REASONS` 值集快照未变 |
| I12 | V2.4.0 工具侧既有测试零失败 | 注册表 / 面投影 / 选择器 / 执行器 / 健康度 / 确认流契约未被改动 |
| I13 | 世界关闭时 `world.*` 剔除 | `world_unavailable` / `world_disabled` 裁剪生效，`world.*` 工具不进计划 |
| I14 | **Flag off 逐字节一致** | `SubGoalSpec.tool_id` 不写；绑定只在执行期由 `ToolSelector` 发生 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」工具链路全链** | `PlanStep.tool_id` → `to_intent` → 六闸门 → `assemble_plan` → `ToolExecutor` 五段 → `ToolResult` → `PlanStepOutcome` | 三账对齐（Run 台账 / 决策记录 / 行动记录）；每段可观测 |
| S2 | 创建提醒步骤 | `builtin.reminder.create` 步骤执行 | `permission` 正常 → `validate` 通过 → `invoke` → `ToolResult{effects:[{kind:world}]}` → `deferred_world_op` → outbox |
| S3 | 查天气步骤 | `world.env.query` 步骤执行 | 读类工具；`effects` 为空；步骤候选判据以 `tool` 源判定 |
| S4 | 提醒步骤需确认 | `permission=confirm_required` | 零外部调用；等既有确认流；批准后续跑且幂等键复用 |
| S5 | 权限被拒 | `permission=deny` | `step.failed`；**不重试**；不自动绕过 |
| S6 | 工具熔断 | `world.env.query` 连续失败触发熔断 | 后续计划中该工具被闸门 6 拒（`tool_status:tripped`） |
| S7 | 时段剔除 | `late_night` + `channel.feishu.send` 步骤 | 闸门 5 过、闸门 6 拒；计划步数不变 |
| S8 | 扩展工具 | `ext.api.*` 工具在面上 | 可被规划与执行（一视同仁） |
| S9 | 全部额度耗尽 | `action_max_active_per_user` 达上限 | 六闸门 `quota_exceeded` → 步骤不执行、不产生 `ActionRecord` |
| S10 | Flag off | 绑定子闸 off → 一次规划与执行 | `sub_goals` 无 `tool_id`；执行期由 `ToolSelector` 绑定；行为与 V2.4.0 逐字节一致 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- **链路断言**：一次步骤执行完整经过六闸门与五段短路（每段可观测），且任一前置段失败路径**零外部调用**（打桩断言，含 DB 写与网络）。
- **G-EXEC**：静态扫描断言 `app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute`。
- 闸门 5/6 各有工具状态用例，四类工具均不进计划：`disabled` / 恒 `unavailable` / 熔断 `tripped` / 被日时段或 Run Profile 剔除（如 `channel.*` 在 `late_night`）；其中「闸门 5 过、闸门 6 拒」**必须单列用例**，且断言计划步数与内容不变、仅该步暂不装配。
- 一能力多工具时，规划期绑定结果与执行期 `ToolSelector` 选择结果一致（同函数同规则，用例对照）。
- `confirm_required` 步骤**零外部调用**（打桩断言）且经既有确认流恢复；规划期弱校验不过的步骤在规划期即被拒（不进入执行）。
- 工具面投影的八维裁剪理由逐条可解释，每条 `excluded` 携带 reason；`surface_hash` 同输入同输出。
- 扩展命名空间工具（`ext.api.*` / `user.*`）在面上且可解析时可被规划（用例）。
- `PlanStepOutcome.failure_kind` 取值全部落在既有 `TOOL_FAILURE_KINDS`（6 值）内；`ActionStatus` 与 `GATE_REASONS` 值集未扩。
- `permission_denied` 不重试（`attempt` 不增加）；`invalid_params` 转 `permanent`；`capability_unavailable` 等下一 tick 复面。
- Flag off 时工具面不参与规划（`SubGoalSpec.tool_id` 不写），绑定只在执行期由 `ToolSelector` 发生，行为与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- V2.4.0 工具侧既有测试零失败（注册表 / 面投影 / 选择器 / 执行器 / 健康度 / 确认流契约未被改动）。
- 闸门 5 调用前后工具注册表快照一致（只读消费，零状态改动）。
- 闸门 6 不自行调用 `ToolSurfaceResolver`（面由装配期提供，零重算）。
- `action_engine.run_action_planning` 的额度与冷却未放宽（负例：额度耗尽时步骤不执行、不产生 `ActionRecord`）。
- 三账对齐：Run 台账（`loop_runs`）/ 决策记录（`decision_records`）/ 行动记录（`action_records`）对同一次步骤执行可互相追溯。
- 世界关闭时 `world.*` 工具被正确剔除（面裁剪 `world_disabled` 生效）。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`。
- **零新增工具逻辑**：`services/planning/` 零自造工具排序 / 过滤 / 映射规则；只用 `ToolRegistry.resolve` 与 `ToolSelector.select_with_reason`（静态断言）。
- **零特判**：Planning 对扩展工具零特殊分支（静态断言：`planning/` 零 `ext.api` / `user` 命名空间字符串判断）。
- **治理未被稀释**：`G-EXEC` + 链路断言 + 授权分层三条共同构成「计划层不得绕过工具治理」的完整守卫。
- **「闸门 5 过、闸门 6 拒」的语义正确**：该场景下计划的**内容与步数不变**（不是拒绝整份计划），只有该步暂不装配——这是 architecture §3.4 对该闸门差异的明确要求，用例可判定。
- **文档一致**：本文件与 architecture §3.4 / §3.7 / §6.3 / §7.7 / §7.9 / §5.6 及 tasks.md PLAN-006 Acceptance Criteria 逐条对应，无自相矛盾。
