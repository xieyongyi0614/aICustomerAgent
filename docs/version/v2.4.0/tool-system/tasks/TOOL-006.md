# TOOL-006 Task Detail — Autonomy Integration

> 上游：[../architecture.md](../architecture.md) §7.2（Tool 与 Autonomy 2.0 集成）、§4.1（Tool Decision Layer）；[../tasks.md](../tasks.md) TOOL-006
> 状态：设计稿（未实现）
> 范围红线：**不新建自治执行器**、不新建 LLM 决策循环、不放宽任何既有额度；`_produce_autonomy_action` 形态不变；**Action = Intent，Tool = Execution** 的编排关系不得颠倒。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-006 |
| **Task Name** | Autonomy Integration |
| **Priority** | P1 |
| **Dependencies** | TOOL-004, TOOL-005 |
| **建议提交** | `feat: V2.4.0 自治工具面接入与工具事实` |

## 1.1 Goal

让 Autonomy 2.0 **真正感知并调用工具**。本任务的核心是关闭一个既有断层：`decision_pipeline.run_pipeline` 的 `capabilities` 参数早已存在，但自治侧从未传入——工具面因此从未参与自治决策。本任务首次实传工具面，并新增有界的工具事实段供自治策略消费。

同时钉死编排关系：**自治只产出意图（Action），执行经既有行动编排器与工具执行器（Tool）**，不新增执行路径、不放宽额度。

## 1.2 Scope

**包含**

- 扩展 `app/application/autonomy_engine.py`：自治 tick 首次实传 `capabilities=surface.tool_ids`。
- 扩展 `app/application/autonomy_engine.py::_collect_action_facts`：新增工具事实段（可用工具 / 最近失败 / 已熔断）。
- 扩展 `app/services/autonomy_policy.py`：`PolicySnapshot` 新增 `tool_facts` 字段并接入既有八步裁决的输入面（**不新增裁决步骤**）。
- 扩展 `app/character/asuna/action.py`：自治产行动的参数模板扩展（从"固定模板"到"工具参数模板"）。
- 单测：自治工具面正确性、工具事实有界性、额度未放宽、端到端三账对齐。

**不包含（Non-Scope）**

- 自治侧权限判定（复用 TOOL-005，本任务只确保工具面已按状态裁剪）。
- 世界事实装配（TOOL-007）。
- 工具实现体（TOOL-010）。
- 自治触发源扩展（`trigger_registry` 三类不变）。
- 工具调用预算的新档位（沿用既有 `foreground` / `background` / `event` 三档）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/application/autonomy_engine.py` | 扩展 | 自治 tick 算工具面并实传；工具事实收集 |
| `app/services/autonomy_policy.py` | 扩展 | `PolicySnapshot.tool_facts` 字段 + 输入面接入 |
| `app/character/asuna/action.py` | 扩展 | 自治产行动的工具参数模板 |
| `app/services/tool/surface.py` | 复用不改 | 工具面投影（TOOL-004 已交付） |
| `app/services/tool/context.py` | 复用不改 | `ToolContext`（自治来源装配） |

**编排关系图（本任务的核心裁决）**

```text
Autonomous Decision（autonomy_engine tick，既有）
        │  ① 候选与裁决
        ▼
TriggerEvaluator → AutonomyPolicy（八步，既有）→ AutonomyVerdict
        │  新增输入：tool_facts（本任务）
        ▼
Create Action（意图层）
   ActionIntent{action_type, params, dedupe_key, source="autonomy"}
        │  ② 编排（既有唯一入口）
        ▼
action_engine.run_action_planning
   create_record → evaluate_gates（六闸门）→ assemble_plan → execute_plan
        │
        ▼
Execute Tool（执行层）
   ToolBinding → PermissionGate → ParamValidator → Invoker → Normalizer
        │
        ▼
Receive Result
   ToolResult{status, effects, observations}
        │
        ▼
Update World State（唯一合法路径）
   effects(kind=world) → deferred_world_op → outbox → world_engine
```

**关键纪律**：`Action = Intent`（"我要做什么"）、`Tool = Execution`（"用什么手段做"）。自治**不直接调工具**——它产出意图，交给既有编排器。

## 2.2 数据结构

### PolicySnapshot 新增字段

| 字段 | 类型 | 说明 | 默认 |
|---|---|---|---|
| `tool_facts` | dict | 工具事实段（见下） | `{}` |

### tool_facts 结构（有界）

| 键 | 类型 | 说明 | 上限 |
|---|---|---|---|
| `available` | list[str] | 当前自治工具面内的 tool_id | 取前 5（按 priority） |
| `recent_failures` | list[dict] | `{tool_id, failure_kind}` | 3 条 |
| `breaker_open` | list[str] | 已熔断 tool_id | 3 条 |

**有界纪律**：整个 `tool_facts` 经既有 `observability.bound_extra` 预算裁剪（`observability_step_extra_max_chars`），与 `action_facts` 同款——**不新增预算机制**。

### 自治工具面（Profile 收窄）

| Run Profile | 工具面 | 理由 |
|---|---|---|
| `autonomous_tick` | 剔除 `channel` 命名空间 | 无人在线时不得主动外发消息 |
| `autonomous_tick` | 剔除标签 `social` | 深夜/离线不推社交类 |
| `autonomous_tick` | 保留 `builtin.*` / `world.*` | 提醒、物品、环境查询等自足能力 |

（收窄规则由 TOOL-004 的 `SurfaceRule` 资产声明，本任务只消费。）

## 2.3 核心流程

### 自治 tick 工具面接入

```text
autonomy_engine tick（既有流程，仅插入两处）
   │
   ├─ ① 候选用户枚举（既有）
   ├─ ② TriggerEvaluator（既有）
   ├─ ③ AutonomyPolicy 裁决（既有八步）
   │       ← 新增输入 tool_facts（见下）
   │
   ├─ ④ 若 v24_tool_system_enabled：
   │      surface = ToolSurfaceResolver.resolve("autonomous_tick", ctx)
   │      capabilities = surface.tool_ids
   │   否则：
   │      capabilities = None（V2.3.0 原状，断层 B7 保持）
   │
   ├─ ⑤ decision_pipeline.run_pipeline(capabilities=capabilities, ...)
   │       ← capability 候选（P3）首次参与自治评分
   │
   └─ ⑥ _produce_autonomy_action（既有，形态不变）
          额度检查 → ActionIntent → run_action_planning
```

### 工具事实收集

```text
_collect_action_facts(user_id)  ← 既有函数，扩展
    action_enabled off → 返回 {}（既有）
    新增：v24_tool_system_enabled on 时追加 tool_facts
        surface = ToolSurfaceResolver.resolve("autonomous_tick", ctx)
        available = surface.tool_ids[:5]
        recent_failures = registry.health() 中最近失败的 3 条
        breaker_open = registry.health() 中 tripped 的 tool_id（≤3）
        → bound_extra 裁剪后返回
```

**缓存语义不变**：沿用既有 `_ACTION_FACTS_CACHE` 进程级缓存形态，工具事实同源缓存。

### 自治产行动的参数模板

```text
_params_for_autonomy_action(action_type, now)  ← 既有函数，扩展
    create_reminder → {"content": "休息一下", "due_at": now+30min}   # 既有
    新增：从 PROACTIVE_ACTION_MAP 映射到工具后，按工具声明的
          input_schema 默认值补齐缺参（source_hint == "default"）
```

**纪律**：自治产行动仍受 `autonomy_action_daily_limit` 与 `action_max_active_per_user` 双重约束——**本任务不放宽任何额度**。

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `application/autonomy_engine.py::tick` | 插入工具面计算与实传 | 增量（约 2 处） |
| `application/autonomy_engine.py::_collect_action_facts` | 追加工具事实段 | 增量 |
| `application/autonomy_engine.py::_produce_autonomy_action` | **形态不变**；参数模板扩展在资产层 | 零改动（逻辑） |
| `services/autonomy_policy.py::PolicySnapshot` | 新增 `tool_facts` 字段 | 增量（字段追加） |
| `services/autonomy_policy.py` 八步裁决 | 复用为输入信号，**不新增步骤** | 增量（读信号） |
| `services/decision_pipeline.py` | `capabilities` 参数首次被自治实传（参数已存在） | 零改动 |
| `application/agent_runtime/llm_gateway.py` | 预算档位不变（`background`） | 零改动 |
| `repositories/action_repository.py::list_records` | 既有日额度统计 | 零改动 |
| `services/tool/surface.py` / `registry.py` | 只读消费 | 零改动 |

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 工具事实为运行期值对象 |
| Field | 无新增列 | `tool_facts` 进 `PolicySnapshot`（内存态）+ `runtime_traces.steps`（既有 JSON 列） |
| Index | 无新增 | 日额度统计沿用 `action_records` 既有索引 |
| Migration | **无** | — |

**观测落点**：自治 tick 的工具面与工具事实经既有 `trace.record()` 写入 `runtime_traces.steps`；决策审计落 `decision_records`（既有）——**不新建观测表**。

---

# 4. API / Interface Design

## 4.1 工具事实收集接口

```text
interface AutonomyToolFacts:
    collect(user_id: str, ctx: ToolContext) -> dict
        # 返回 {available, recent_failures, breaker_open}
        # 总闸 off 或异常 → 返回 {}（降级为空包，不阻塞 tick）
```

| 项 | 内容 |
|---|---|
| **Input** | `user_id` + 自治来源的 `ToolContext` |
| **Output** | 有界 dict（经 `bound_extra` 裁剪） |
| **失败形态** | 任何异常 → 空包 + 日志，**不抛出**（与既有 `_collect_action_facts` 同款纪律） |

## 4.2 自治工具面接口

```text
interface AutonomySurface:
    resolve_for_tick(user_id: str, now: datetime) -> ToolSurface | None
        # 总闸 off → None（调用方传 capabilities=None，保持 V2.3.0 行为）
        # 总闸 on  → ToolSurfaceResolver.resolve("autonomous_tick", ctx)
```

## 4.3 PolicySnapshot 接口（增量）

```text
PolicySnapshot:
    ...（既有字段全部保留）
    tool_facts: dict = {}          # 新增

    # 既有派生方法不变
```

| 项 | 内容 |
|---|---|
| **Input** | 由 `autonomy_engine` 装配时填充 |
| **Output** | 只读信号，供既有八步裁决读取 |
| **兼容** | 缺省空 dict → 八步裁决行为与 V2.3.0 逐字节一致 |

## 4.4 自治产行动参数模板接口

```text
interface AutonomyActionParams:
    build(action_type: str, now: datetime, binding: ToolBinding | None) -> dict
        # binding 为 None → 回退 V9 固定模板（既有行为）
        # binding 存在   → 按 input_schema 的 default / source_hint 补齐
```

---

# 5. Implementation Plan

## Step 1 — 自治工具面接入

1. 在 `autonomy_engine.tick` 计算自治工具面（总闸门控）。
2. 把 `capabilities=surface.tool_ids` 实传给 `decision_pipeline.run_pipeline`。
3. 总闸 off 时保持 `capabilities=None`（断层 B7 原状）。
4. 单测：工具面正确且不含 `channel.*`；off 时传 `None`；决策审计中 capability 候选出现。

## Step 2 — 工具事实段

1. 扩展 `_collect_action_facts`：追加 `tool_facts`（available / recent_failures / breaker_open）。
2. `PolicySnapshot` 新增 `tool_facts` 字段并接入既有八步裁决的输入面（**不新增步骤**）。
3. 经 `bound_extra` 预算裁剪。
4. 单测：有界性（超量截断）、装配异常降级为空包、熔断工具出现在 `breaker_open`。

## Step 3 — 参数模板与端到端验证

1. 扩展自治产行动参数模板（binding 存在时按 schema 补齐缺参）。
2. 端到端：Autonomous Decision → Create Action → Execute Tool → Receive Result → Update World State（经 outbox）。
3. 三账对齐断言：`loop_runs` / `decision_records` / `action_records` 可互相追溯。
4. 额度回归：`autonomy_action_daily_limit` 与 `action_max_active_per_user` 未被放宽。
5. 回归：Flag 全 off 时自治行为与 V2.3.0 逐字节一致。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 自治 tick 传入的工具面正确且**不含 `channel.*`**（Profile 收窄生效）。
- `tool_facts` 三键齐备且**有界**（available ≤ 5 / recent_failures ≤ 3 / breaker_open ≤ 3），超量按确定性规则截断。
- `tool_facts` 装配异常时降级为空包，**不阻塞 tick**（异常注入测试）。
- 熔断工具出现在 `breaker_open` 且不出现在 `available`。
- 自治产行动参数模板：`binding` 存在时按 schema 补齐缺参；`binding` 为 None 时回退 V9 固定模板。
- 工具候选在自治决策审计中可见（`decision_records.candidates` 含 capability 来源）。

## 6.2 Integration Acceptance

- **端到端链路通过**：Autonomous Decision → Create Action → Execute Tool → Receive Result → Update World State，且世界写入经 outbox 唯一路径（静态与运行期双重断言）。
- **三账对齐**：`loop_runs`（Run）/ `decision_records`（决策）/ `action_records`（行动与工具执行）可互相追溯（run_id / decision 审计 / record.id）。
- 额度**未放宽**：`autonomy_action_daily_limit` 与 `action_max_active_per_user` 行为与 V2.3.0 逐字节一致（对照测试）。
- `_produce_autonomy_action` 形态不变（diff 断言）；`llm_gateway` 预算档位与数学不变。
- `decision_pipeline.py` 零 diff（本任务只改调用方传参，不改管线）。
- **Flag 全 off 时**：`capabilities=None`，自治行为与 V2.3.0 逐字节一致；既有测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 总闸 on 但注册表为空（无工具声明） | 工具面为空 → `capabilities=[]` → 无 capability 候选，决策仍正常（silence 兜底） |
| E2 | 自治工具面内全部工具已熔断 | `available` 为空、`breaker_open` 非空；决策不因无可用工具而失败 |
| E3 | `tool_facts` 超出字符预算 | `bound_extra` 裁剪后仍为合法 dict（不截断成非法 JSON） |
| E4 | `_collect_action_facts` 中工具面计算抛异常 | 捕获后返回 `{}`，自治 tick 继续（不中断其他用户） |
| E5 | 自治产行动映射到不在工具面内的工具 | `select` 返回 `None` → 不产行动（等价 V9 `capability_unavailable`），不抛错 |
| E6 | 同一 tick 内工具面与执行时状态不一致（工具被熔断） | 执行前重新判状态 → `unavailable`；不产生行动副作用 |
| E7 | 自治产行动命中日额度上限 | 保持 V9 行为：记录日志、不产行动、不消耗工具调用 |
| E8 | `PolicySnapshot.tool_facts` 缺省（未装配） | 八步裁决行为与 V2.3.0 逐字节一致 |
| E9 | 深夜时段自治 tick | 工具面按日时段规则进一步收窄（标签 `social` 剔除），与 TOOL-004 规则一致 |
| E10 | 事件驱动 Run（`event_driven`） | 工具面按 Profile 收窄为只读工具；本任务不改变该 Profile 的阶段序列 |
| E11 | 工具执行超时 | `failure_kind=timeout` 进 `recent_failures`；健康度计一次失败 |
| E12 | 用户离线多日后的首个自治 tick | 工具面按当前时刻投影（非离线期间回溯），不补算历史工具面 |
