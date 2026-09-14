# TOOL-003 Task Detail — Tool Executor

> 上游：[../architecture.md](../architecture.md) §4.3（Tool Executor）、§4.4（参数验证）、§5.5（结果契约）、§3.4（异常处理）、§7.8（Flag 设计）；[../tasks.md](../tasks.md) TOOL-003
> 状态：设计稿（未实现）
> 范围红线：**复用 V9 执行器的调用实现，不复制其代码**；不新建表；权限段在本任务为占位（allow-all），真实判定由 TOOL-005 替换；不做重试决策（属 `action_engine`）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-003 |
| **Task Name** | Tool Executor |
| **Priority** | P0 |
| **Dependencies** | TOOL-002 |
| **建议提交** | `feat: V2.4.0 工具执行器与结果归一` |

## 1.1 Goal

交付**执行纪律层**——给"调用一个工具"这件事装上四道纪律：授权（占位）、校验、超时、归一。具体交付五段短路执行器、双层参数校验（结构 + 领域语义）、`CapabilityResult → ToolResult` 结构化归一、执行结果落既有台账 `action_records.steps`，以及工具健康度与熔断。

本任务结束后，任一工具调用都应能回答："它被授权了吗（占位放行）、参数合法吗、执行了多久、产出了什么结构化结果、失败了属于哪一类失败"。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/executor.py`：`ToolExecutor`（五段短路编排）。
- 新增 `app/services/tool/validator.py`：`ParamValidator` + 五个语义校验器。
- 新增 `app/services/tool/normalizer.py`：`ObservationNormalizer`。
- 新增 `app/services/tool/health.py`：熔断判定（连续失败、冷却、半开）——或并入 `registry` 调用侧，按实现便利裁决。
- 扩展 `application/action_engine.py`：`execute_plan` 在总闸开启时改走 `ToolExecutor`；`steps[]` 落新增字段。
- 扩展 `models/action.py`：`GATE_REASONS` 三值（TOOL-001 已加，本任务消费）。

**不包含（Non-Scope）**

- 真实权限判定与确认流（TOOL-005）——本任务权限段为**占位 allow-all**，接口已冻结。
- 工具面投影与选择（TOOL-004）。
- 记忆 / 反思 / 关系投递（TOOL-008 / TOOL-009；本任务只产出 `ToolEffect`）。
- 工具实现体本身（TOOL-010）。
- 多步计划编排（`action_plan_max_steps` 保持 1，Q1 留后续版本）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 | 依赖 |
|---|---|---|---|
| `app/services/tool/executor.py` | 新增 | 五段短路编排；调用 V9 `CapabilityExecutor` | validator / normalizer / permission(占位) |
| `app/services/tool/validator.py` | 新增 | 双层参数校验 + 语义校验器注册表 | `ToolSchema`（TOOL-001） |
| `app/services/tool/normalizer.py` | 新增 | `CapabilityResult` → `ToolResult` | 值对象 |
| `app/services/tool/health.py` | 新增 | 熔断判定与半开 | registry 健康度 |
| `app/services/action/executor.py` | 复用不改 | `CapabilityExecutor.run()` 提供超时/异常归一/usage | — |
| `app/application/action_engine.py` | 扩展 | `execute_plan` 分支走 ToolExecutor；`steps[]` 落新字段 | ToolExecutor |

**分层图**

```text
action_engine.execute_plan（既有编排器，状态机与重试不变）
        │
        ▼
ToolExecutor.run(binding, invocation, ctx) -> ToolExecution
        │
        ├─ ① PermissionGate.evaluate()      ← 占位：总闸关或权限闸关时 allow-all
        ├─ ② ParamValidator.validate()      ← 双层校验
        ├─ ③ CapabilityExecutor.run()       ← V9 既有（超时 / 异常归一 / usage）
        ├─ ④ ObservationNormalizer.normalize()
        └─ ⑤ health.record_outcome()        ← 熔断判定
```

## 2.2 数据结构

### ValidationReport

| 字段 | 类型 | 说明 |
|---|---|---|
| `passed` | bool | 是否通过 |
| `structural` | list[dict] | `{param, code, message}` |
| `semantic` | list[dict] | `{param, code, message}` |
| `normalized` | dict | 规范化后的参数 |

**结构校验码集**：`missing_required` / `type_mismatch` / `enum_invalid` / `range_violated` / `length_violated` / `pattern_mismatch` / `format_invalid` / `unknown_param`。

**语义校验码集**：`not_future` / `location_not_found` / `object_not_in_inventory` / `recipient_not_authorized` / `content_over_budget`。

### ToolResult 归一映射（本任务核心契约）

| V9 `CapabilityResult` | V2.4.0 `ToolResult` | 说明 |
|---|---|---|
| `status`（succeeded/failed/timeout/unavailable） | `status`（7 值超集） | 新增 denied / invalid / pending_confirmation |
| `payload["world_event_id"]` | `effects[].kind="world"`, `ref=<id>` + `observations["world.event_id"]` | 双写兼容 |
| `payload["memory_id"]` | `effects[].kind="memory"`, `ref=<id>` + `observations["memory.id"]` | 双写兼容 |
| `payload["deferred_world_op"]` | 不进 observations（执行细节） | 原样保留在 payload 内（outbox 依赖） |
| `payload["failure_kind"]` | 顶层 `failure_kind` | 旧位置保留 |
| `payload["cancelled"]` | `observations["world.cancelled_count"]` | 逐工具映射 |
| `payload["due_at"]` | `observations["time.due_at"]` | 逐工具映射 |
| `usage` | `usage`（追加 `tool_id` / `external_calls`） | 增量 |
| — | `redacted` | 由 `ToolParameter.sensitive` 驱动 |
| — | `raw_error` | 归一异常时填 `normalize_failed` |

**逐工具 observations 映射表**（角色资产或工具声明内声明，本任务落地框架 + 内置工具条目）：

| tool_id | observations 键 |
|---|---|
| `builtin.reminder.create` | `world.event_id`, `time.due_at` |
| `builtin.reminder.cancel` | `world.cancelled_count` |
| `builtin.memory.save` | `memory.id` |
| `world.object.create/move/use` | `world.object_id`, `world.location_id` |
| `world.env.query` | `env.weather`, `env.part_of_day`, `env.location` |
| `builtin.search.query` | `search.result_count`（内容见 `untrusted` 标记） |

### ToolExecution（落 `action_records.steps[]`）

在 V9 既有 step 结构上**增量追加**三字段，旧字段原样保留：

| 字段 | 新增 | 说明 |
|---|---|---|
| `index` / `capability` / `action` / `params` / `status` | 否 | V9 既有 |
| `result` | 否（内容升级） | 总闸 on 时存 `ToolResult`；off 时存 V9 原始 `CapabilityResult.model_dump()` |
| `tool_id` | ✅ | 工具身份 |
| `permission` | ✅ | `{level, decision, reason, confirmed}` |
| `validation` | ✅ | 失败时存 `ValidationReport`，通过时为 `None` |
| `duration_ms` | ✅ | 执行耗时（原在 usage 内，提升为顶层便于投影） |

## 2.3 核心流程

### 五段短路执行

```text
run(binding, invocation, ctx)
   │
   ├─ ① resolve
   │     注册表无此 tool_id / effective_status != enabled
   │     → status=unavailable, failure_kind=unavailable，终止
   │
   ├─ ② permission（占位实现）
   │     v24_tool_permission_enabled = off → allow（占位放行）
   │     on  → 调 PermissionGate.evaluate()（TOOL-005 实现）
   │     deny → status=denied, gate_reason=permission_denied，终止（零外部调用）
   │     confirm_required → status=pending_confirmation，终止（零外部调用）
   │
   ├─ ③ validate（v24_tool_schema_validation_enabled）
   │     off → 跳过（仅 V9 ActionSchema 弱校验，由 planner 已做）
   │     on  → 双层校验
   │     失败 → status=invalid, gate_reason=invalid_params，终止（零外部调用）
   │     通过 → params := report.normalized
   │
   ├─ ④ invoke
   │     CapabilityExecutor.run(step, ctx)   ← V9 既有：wait_for 超时 + 异常归一 + usage
   │
   └─ ⑤ normalize + record
         ObservationNormalizer.normalize() → ToolResult
         health.record_outcome(ok, failure_kind) → 熔断判定
         回填 record.steps[].result
```

### 熔断判定

```text
record_outcome(tool_id, ok, failure_kind)
    ok=True  → consecutive_failures=0；tripped=False；last_success_at=now
    ok=False → consecutive_failures += 1；last_failure_at=now
               consecutive_failures >= v24_tool_breaker_threshold
                   → tripped=True；tripped_at=now
    tripped 且 now - tripped_at >= v24_tool_breaker_cooldown_seconds
        → 半开：tripped=False，consecutive_failures 保留（下次失败立即重熔）
```

**熔断的消费方**：`ToolRegistry.effective_status` 读 `tripped` 返回 `disabled`（TOOL-002 已建三层叠加），因此熔断工具自动从工具面消失，无需 TOOL-004 额外处理。

**熔断不改变工具声明**：`tripped` 只在健康度内存态，重启归零。

### 语义校验器注册表

```text
validator.register_semantic(name, fn)
    fn(params: dict, ctx: ToolContext) -> list[str]      # 返回错误信息列表，空表示通过

内置五个（本任务交付）：
    future_datetime         : due_at 必须晚于 ctx.now
    location_exists         : location 必须在 ctx.world.locations 内
    object_in_inventory     : object 必须在 ctx.inventory 内
    recipient_authorized    : 收件人必须在 ctx.authorized_recipients 内
    content_within_budget   : content 长度 ≤ 工具声明预算
```

**ToolContext 依赖**：`location_exists` 与 `object_in_inventory` 需要世界事实。本任务按 **TOOL-004 定义的 `ToolContext` 结构**消费，字段缺失时校验器**降级放行并记录**（不因上下文缺失而误拒）——世界事实的完整装配在 TOOL-007。

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/action/executor.py::CapabilityExecutor` | 直接实例化并调用 `run(step, ctx)`；**不复制其实现** | 零改动（或加 `tool_id` 透传，最小增量） |
| `services/action/registry.py::ExecutionContext` | 复用为执行上下文；`ToolContext` 是它的超集 | 零改动 |
| `application/action_engine.py::execute_plan` | 总闸 on 时改走 `ToolExecutor`；off 时保持 V9 原路径 | 分支增量 |
| `application/action_engine.py::integrate_result` | 读 `ToolResult.effects` 替代 `payload` 字符串硬取（旧键兜底） | 增量 |
| `models/action.py::ActionRecord.steps` | 落新增三字段（JSON 内嵌，无 DDL） | 增量 |
| `models/action.py::transition_action` | **零改动**；`ToolExecutionStatus` 映射到 V9 六态由本任务负责 | 零改动 |
| `models/action.py::CapabilityResult` | 只读消费；**不修改** | 零改动 |
| `repositories/action_repository.py` | 沿用 `save_record`；无新方法 | 零改动 |

### 状态映射（ToolExecutionStatus → V9 ActionStatus）

| ToolExecutionStatus | ActionRecord.status | gate_reason |
|---|---|---|
| `unavailable` | `cancelled` | `capability_unavailable` |
| `denied` | `cancelled` | `permission_denied` |
| `invalid` | `cancelled` | `invalid_params` |
| `pending_confirmation` | `planned` | `pending_confirmation` |
| `succeeded` | `succeeded` | — |
| `failed` / `timeout` | `failed` 或 `executing`（重试） | 由 `failure_kind` + 既有退避决定 |

**不新增 ActionStatus 值**——V9 六态已完备，细粒度原因由 `gate_reason` 承载。

---

# 3. Database Changes

**本任务无 DDL 变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 执行台账复用 `action_records`（V9 既有，架构 §5.1 裁决） |
| Field | 无新增列 | 新增的 `tool_id` / `permission` / `validation` / `duration_ms` 落在 `action_records.steps` 这个**既有 JSON 列内部**，属结构演进而非 DDL |
| Index | 无新增 | 执行查询沿用既有 `action_records` 索引 |
| Migration | **无** | 若实现阶段发现需要为 `steps` 建独立表或加列，即为设计违背，须回退重审 architecture §5.1 |

**JSON 结构演进兼容策略**

| 读取方 | 读法 | 兼容期 |
|---|---|---|
| V9 既有代码（`integrate_result` / `collect_facts`） | 读 `steps[].result.payload.<旧键>` | 保留 ≥ 一个版本窗口 |
| V2.4.0 新代码 | 读 `steps[].result.effects` / `.observations`（新键优先） | 永久 |
| 调试端点（TOOL-004） | 读新键，旧键兜底 | 永久 |

**回滚**：`v24_tool_observation_enabled` 置 off → `steps[].result` 立即回到 V9 原始 `CapabilityResult.model_dump()` 形态，无需数据迁移。

---

# 4. API / Interface Design

## 4.1 执行器接口

```text
interface ToolExecutor:
    run(binding: ToolBinding,
        invocation: ToolInvocation,
        ctx: ToolContext) -> ToolExecution
```

| 项 | 内容 |
|---|---|
| **Input** | `binding`（TOOL-002 解析产物）、`invocation`（决策层产出）、`ctx`（执行上下文 + 预读世界事实） |
| **Output** | `ToolExecution`（含 `result: ToolResult`、`permission`、`validation`、`duration_ms`） |
| **失败形态** | **不抛异常**——一切失败归一为 `ToolExecution.status` 取值。仅编程错误（如 binding 与 invocation 的 tool_id 不一致）抛错 |

## 4.2 权限闸接口（本任务冻结形状，TOOL-005 实现）

```text
interface PermissionGate:
    evaluate(defn: ToolDefinition,
             inv: ToolInvocation,
             snapshot: PermissionSnapshot) -> PermissionDecision

PermissionDecision:
    decision: str        # allow / confirm_required / deny
    level: PermissionLevel
    reason: str
    confirm_prompt: str | None
    scope_required: tuple[str, ...]
```

**占位实现约定**：`v24_tool_permission_enabled` 为 off 时，`evaluate` 恒返回 `decision="allow"`, `reason="permission_layer_off"`。TOOL-005 开启该子闸后替换为真实七步判定，**接口形状不变**。

## 4.3 校验器接口

```text
interface ParamValidator:
    validate(defn: ToolDefinition,
             params: dict,
             ctx: ToolContext) -> ValidationReport
    register_semantic(name: str,
                      fn: Callable[[dict, ToolContext], list[str]]) -> None
```

| 项 | 内容 |
|---|---|
| **Input** | 工具声明 + 待校验参数 + 执行上下文 |
| **Output** | `ValidationReport`（`passed` + 分类错误 + `normalized`） |
| **纪律** | 纯函数、零 IO；`normalized` 必须幂等（对已规范化参数再规范化结果不变） |

## 4.4 归一器接口

```text
interface ObservationNormalizer:
    normalize(defn: ToolDefinition,
              raw: CapabilityResult,
              meta: ExecutionMeta) -> ToolResult

ExecutionMeta:
    tool_id: str
    duration_ms: float
    sensitive_param_names: tuple[str, ...]
```

| 项 | 内容 |
|---|---|
| **Input** | 工具声明 + V9 原始结果 + 执行元数据 |
| **Output** | `ToolResult`（结构化 effects / observations / failure_kind / usage / redacted） |
| **失败形态** | 归一自身异常时**不抛错**，降级为 `{status: raw.status, observations: {}, raw_error: "normalize_failed"}`，并记录日志 |

## 4.5 健康度接口

```text
interface ToolHealthTracker:
    record_outcome(tool_id: str, *, ok: bool, failure_kind: str | None) -> None
    is_tripped(tool_id: str, now: datetime) -> bool
    snapshot(tool_id: str | None = None) -> dict[str, ToolHealth]
```

## 4.6 语义校验器接口

```text
interface SemanticValidator:
    name: str
    validate(params: dict, ctx: ToolContext) -> list[str]
```

---

# 5. Implementation Plan

## Step 1 — 参数校验层

1. 实现 `ParamValidator.validate`：结构校验按 `ToolParameter` 声明逐项执行（类型 / 枚举 / 范围 / 长度 / 正则 / 格式 / 未知字段），产出分类错误码。
2. 实现 `normalized` 规范化：去空白、字符串化、时间统一 ISO 8601、枚举值归一。
3. 实现语义校验器注册表与五个内置校验器；`location_exists` / `object_in_inventory` 在 `ToolContext` 字段缺失时降级放行并记录。
4. 单测：结构码集全覆盖、规范化幂等、语义校验器各一正例一负例、上下文缺失降级。

## Step 2 — 归一器与健康度

1. 实现 `ObservationNormalizer.normalize`：按 §2.2 映射表把 `CapabilityResult` 转 `ToolResult`；**保留全部 V9 旧键**（双写兼容）。
2. 实现敏感参数脱敏（由 `ToolParameter.sensitive` 驱动），脱敏字段名记入 `redacted`。
3. 实现 `ToolHealthTracker`：连续失败计数、熔断、冷却、半开；有界滑动窗。
4. 单测：映射表逐行对照、旧键保留断言、脱敏、归一异常降级、熔断与半开时序（注入时钟）。

## Step 3 — 执行器编排与 action_engine 接线

1. 实现 `ToolExecutor.run` 五段短路；权限段按占位约定（off → allow）。
2. 扩展 `action_engine.execute_plan`：`v24_tool_system_enabled` on 时改走 `ToolExecutor`；off 时保持 V9 原路径（逐字节一致）。
3. 扩展 `action_engine.integrate_result`：优先读 `ToolResult.effects`，旧键兜底。
4. 落 `steps[]` 新增三字段；`duration_ms` 从 usage 提升为顶层。
5. 单测：五段短路顺序、**前置段失败零外部调用**（打桩断言 DB 与网络）、状态映射表逐行、`steps[]` 形状快照、Flag off 逐字节一致。
6. 回归：Flag 全 off 时既有行动域测试零修改通过。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 五段短路顺序固定：resolve → permission → validate → invoke → normalize/record；任一前置段失败**不再进入后续段**。
- 任一前置段失败路径**零外部调用**（DB 写与网络调用均打桩断言为 0）。
- 结构校验八类错误码各有测试；语义校验五类各有测试。
- `normalized` 幂等：对已规范化参数再规范化结果完全一致；等价形式（时间 / 空白 / 枚举）被统一。
- `ToolResult` 归一映射表逐行通过；`effects` / `observations` 结构化产出正确。
- 脱敏：`sensitive=True` 参数在 `steps[].params` 中不可见，字段名记入 `redacted`。
- 熔断：连续失败达阈值 → `tripped=True`；冷却后半开；`ToolRegistry.effective_status` 返回 `disabled`；重启归零。
- 归一自身异常时降级为 `raw_error="normalize_failed"` 且不抛错。

## 6.2 Integration Acceptance

- `CapabilityExecutor.run` 被**复用而非复制**（代码重复度断言：`executor.py` 内不出现 `asyncio.wait_for` 的超时逻辑重写）。
- 超时与异常归一行为与 V9 逐字节一致（同一输入下 `CapabilityResult` 对照测试）。
- `action_records.steps[]` 落库形状快照通过，含 `tool_id` / `permission` / `validation` / `duration_ms`。
- `integrate_result` 新键优先、旧键兜底：人为构造仅含旧键的 result，投递路径仍工作。
- **Flag 全 off 时**：`steps[].result` 为 V9 原始形态，`execute_plan` 走原路径，既有行动域测试零修改通过。
- `transition_action` 与 `ActionRecord` 状态机**零改动**（diff 断言）。
- 本任务不新增表、不新增迁移（迁移目录 diff 断言）。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `binding.tool_id` 与 `invocation.tool_id` 不一致 | 抛错（编程错误，不归一为业务失败） |
| E2 | 工具在解析后被熔断（执行前状态翻转） | 执行前重新判状态 → `unavailable`，不执行 |
| E3 | `params` 含未声明字段且 `strict=True` | `unknown_param` 错误，`status=invalid` |
| E4 | `params` 含未声明字段且 `strict=False` | 忽略该字段，继续执行 |
| E5 | `due_at` 为过去时间 | `future_datetime` 语义校验失败 → `invalid` |
| E6 | `ToolContext` 未提供 `locations`（TOOL-007 未完成） | `location_exists` 降级放行并记录，不误拒 |
| E7 | `CapabilityResult.payload` 同时含 `world_event_id` 与 `deferred_world_op` | 前者进 effects + observations；后者留在 payload（outbox 依赖，不进 observations） |
| E8 | `CapabilityResult.status="unavailable"`（如 `search` 空壳） | `ToolResult.status="unavailable"`，`failure_kind=unavailable`，**不重试** |
| E9 | `CapabilityResult.status="timeout"` | `failure_kind=timeout`，交由既有重试退避；`health` 计一次失败 |
| E10 | 归一器遇到未知 payload 键 | 忽略未知键（不抛错），已知键按映射表处理 |
| E11 | 参数中含超长字符串（10k 字符） | `length_violated` 或 `content_over_budget` 拦截，不触达能力 |
| E12 | 敏感参数值为空字符串 | 不脱敏（无内容），`redacted` 不含该字段 |
| E13 | 熔断冷却期内再次失败 | `tripped` 保持 True，冷却计时不重置 |
| E14 | 同一工具并发两次执行（per-user 写锁外的场景） | 健康度计数按调用顺序累加；不引入并发控制（沿用 V9 per-user 写锁语义） |
