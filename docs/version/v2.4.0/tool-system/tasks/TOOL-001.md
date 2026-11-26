# TOOL-001 Task Detail — Tool Core Model

> 上游：[../architecture.md](../architecture.md) §5（数据模型设计）、§7.8（Flag 设计）、§9.2（权限等级）；[../tasks.md](../tasks.md) TOOL-001
> 状态：设计稿（未实现）
> 范围红线：**纯值对象 + 配置骨架**，零 IO、零执行、零治理逻辑；不新建任何表；不改动既有 `Capability` / `ActionSchema` / `CapabilityResult` 语义。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-001 |
| **Task Name** | Tool Core Model |
| **Priority** | P0 |
| **Dependencies** | 无 |
| **建议提交** | `feat: V2.4.0 工具域模型与配置骨架` |

## 1.1 Goal

建立工具域的**唯一类型契约与配置骨架**，为后续 11 个任务提供不可变的值对象与纯函数。本任务结束后，工具域应当能回答"一个工具长什么样、它属于哪个命名空间、当前什么生命周期状态、它的权限画像是什么"，但**还不能执行任何东西**。

同时把 V2.4.0 的全部开关与参数一次性定义完毕（一个总闸 + 九个业务子闸 + 九个参数），并接入既有 enablement 启用链校验——后续任务只从本任务定义的配置读取，不得自行散落新开关。

## 1.2 Scope

**包含**

- 新增 `app/models/tool.py`：工具域值对象全集 + 两个纯函数（生命周期状态机、权限等级排序）。
- 新增 `app/core/settings/tool.py`：`ToolSettings(BaseSettings)`，10 个 Flag + 9 个参数，并按其 settings 包既有组装方式并入全局 Settings。
- 扩展 `app/core/settings/enablement.py`：新增 v24 子闸串行链校验（照抄 v23 段模式）。
- 扩展 `app/models/action.py`：`GATE_REASONS` 值域 +3（`permission_denied` / `invalid_params` / `pending_confirmation`）。
- 单元测试：值对象序列化往返、状态机全枚举、配置默认值、启用链校验。

**不包含（Non-Scope）**

- 工具注册表实现（TOOL-002）。
- 任何执行、校验、授权、归一逻辑（TOOL-003 / TOOL-005）。
- `CapabilityResult` / `ActionSchema` / `Capability` Protocol 的**任何改动**——它们是 V9 既有契约，本任务只在其之上声明新类型。
- `.env.example` 段落补写（收口至 TOOL-012）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/models/tool.py` | 新增 | 值对象与纯函数；无 IO | 仅依赖 `pydantic` / 标准库 |
| `app/core/settings/tool.py` | 新增 | Flag 与参数声明 + 参数自校验 | 依赖 `_shared` |
| `app/core/settings/enablement.py` | 扩展 | v24 串行链校验 | 读 settings |
| `app/models/action.py` | 扩展 | `GATE_REASONS` 值域 | 无新依赖 |

**分层纪律**：`models/tool.py` 与 `models/action.py` 同级，属纯值对象层——**禁止** import `app.repositories` / `app.services` / `app.application`。该约束由静态扫描测试强制（见 §6.3）。

## 2.2 数据结构

### ToolDefinition（工具声明，代码资产，不落库）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | str | ✅ | 点分命名空间唯一 id，如 `builtin.reminder.create` |
| `name` | str | ✅ | 人类可读中文名，≤ 20 字 |
| `description` | str | ✅ | 工具做什么，≤ 120 字 |
| `when_to_use` | str | ⭕ | 何时该用，≤ 80 字 |
| `when_not_to_use` | str | ⭕ | 何时不该用，≤ 80 字 |
| `namespace` | str | ✅ | `builtin` / `channel` / `world` / `ext.api` / `user` |
| `capability` | str | ✅ | 绑定的 Capability 名 |
| `action` | str | ✅ | 绑定的 Capability 动作名 |
| `input_schema` | ToolSchema | ✅ | 输入契约 |
| `output_schema` | ToolSchema | ⭕ | 输出契约，缺省按 ToolObservation 通约处理 |
| `permission` | PermissionProfile | ✅ | 权限画像 |
| `status` | ToolLifecycle | ✅ | 四态之一 |
| `version` | str | ✅ | 语义化版本 |
| `side_effects` | tuple[str, ...] | ✅ | `read` / `write_world` / `write_memory` / `send_external` / `irreversible` |
| `idempotency` | str | ✅ | `natural` / `keyed` / `none` |
| `timeout_seconds` | float | ⭕ | 覆盖全局执行超时 |
| `error_map` | dict[str, str] | ⭕ | 异常类 → failure_kind，默认 `transient` |
| `tags` | tuple[str, ...] | ⭕ | 工具面投影筛选用 |
| `priority` | int | ✅ | 一词多工具时的排序位，默认 100 |
| `memory_policy_key` | str | ⭕ | 记忆边界表键，默认取 `id` |
| `observability_fields` | tuple[str, ...] | ⭕ | 允许进台账的 payload 白名单键 |

### ToolParameter / ToolSchema

| ToolParameter 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | snake_case 参数名 |
| `type` | str | `string` / `integer` / `number` / `boolean` / `datetime` / `enum` / `object` / `array` |
| `required` | bool | 是否必填 |
| `description` | str | ≤ 60 字 |
| `enum` | tuple | `type=enum` 时的值集 |
| `default` | Any | 默认值 |
| `min` / `max` | number | 数值范围 |
| `min_length` / `max_length` | int | 长度范围 |
| `pattern` | str | 正则 |
| `format` | str | `iso8601` / `email` / `url` / `location_id` / `memory_id` |
| `sensitive` | bool | 是否脱敏 |
| `source_hint` | str | `user_message` / `world_fact` / `memory` / `default` |

| ToolSchema 字段 | 类型 | 说明 |
|---|---|---|
| `parameters` | list[ToolParameter] | 参数声明 |
| `strict` | bool | 是否拒绝未声明字段，默认 True |
| `semantic_validators` | tuple[str, ...] | 语义校验器名（实现在 TOOL-003） |

### PermissionProfile

| 字段 | 类型 | 说明 |
|---|---|---|
| `level` | str | `safe` / `normal` / `sensitive` / `dangerous` |
| `scope` | tuple[str, ...] | `self` / `world` / `memory` / `channel:<name>` / `external:<host>` |
| `confirm` | str | `never` / `first_time` / `always` / `out_of_scope` |
| `rate_limit` | dict? | `{per_window, window_seconds}` |
| `requires_online` | bool | 是否要求用户在线 |
| `audit` | bool | 是否强制审计（dangerous 恒 True） |
| `scope_grant_ref` | str? | 授权来源引用 |
| `override_reason` | str? | 等级下调时的显式理由（评审单列） |

### 运行期值对象

| 模型 | 关键字段 | 落库 |
|---|---|---|
| `ToolBinding` | `tool_id` / `capability` / `action` / `definition` | ❌ |
| `ToolInvocation` | `tool_id` / `params` / `rationale` / `source` / `intent` / `goal_id` / `dedupe_key` / `run_id` / `surface_hash` | ❌（进 record.params） |
| `ToolExecution` | `index` / `tool_id` / `capability` / `action` / `params` / `status` / `permission` / `validation` / `result` / `started_at` / `duration_ms` | ✅ `action_records.steps` |
| `ToolResult` | `status` / `effects` / `observations` / `failure_kind` / `error` / `usage` / `redacted` / `raw_error` | ✅ 同上 |
| `ToolEffect` | `kind` / `ref` / `detail` / `reversible` | ✅ 同上 |
| `ToolObservation` | `untrusted` / `source_tool` / 业务键值对 | ✅ 同上 |
| `ToolSurface` | `run_kind` / `tool_ids` / `excluded` / `surface_hash` | ❌（进 trace） |
| `ToolHealth` | `consecutive_failures` / `last_failure_at` / `last_success_at` / `failure_rate_window` / `tripped` | ❌（内存态） |

### 枚举值域

| 枚举 | 取值 |
|---|---|
| `ToolLifecycle` | `enabled` / `disabled` / `deprecated` / `removed` |
| `ToolExecutionStatus` | `succeeded` / `failed` / `timeout` / `unavailable` / `denied` / `invalid` / `pending_confirmation` |
| `ToolFailureKind` | `transient` / `permanent` / `timeout` / `unavailable` / `denied` / `invalid` |
| `ToolEffectKind` | `world` / `memory` / `relationship` / `note` / `external` |
| `PermissionLevel` | `safe` / `normal` / `sensitive` / `dangerous` |

## 2.3 核心流程

### 纯函数一：ToolLifecycle 状态机

```text
         register
            │
            ▼
      ┌───────────┐  disable   ┌────────────┐  enable   ┌───────────┐
      │  enabled  │───────────►│  disabled  │──────────►│  enabled  │
      └─────┬─────┘            └────────────┘           └───────────┘
            │ deprecate                    │ deprecate
            ▼                              ▼
      ┌─────────────────────────────────────────────┐
      │                deprecated                   │
      │  不进新工具面；已存在的待执行引用可继续执行     │
      └────────────────┬────────────────────────────┘
                       │ retire
                       ▼
                    removed
```

非法迁移返回 `None`（与 `models/action.py::transition_action`、V8 物品状态机同款纪律）。

### 纯函数二：权限等级排序与下限判定

```text
等级序：safe(0) < normal(1) < sensitive(2) < dangerous(3)

namespace_floor(namespace) → PermissionLevel
   builtin → normal      world → normal
   channel → sensitive   ext.api → sensitive
   user    → dangerous

resolve_level(declared, namespace, override_reason) → PermissionLevel
   若 declared >= floor        → declared
   若 declared <  floor 且 override_reason 非空 → declared（并在审计中标记降级）
   若 declared <  floor 且 override_reason 为空 → 拒绝（抛错）
```

### 字段长度预算校验

`ToolDefinition` 在构造时校验 `name ≤ 20` / `description ≤ 120` / `when_to_use ≤ 80` / `when_not_to_use ≤ 80` / `ToolParameter.description ≤ 60`，超限即拒绝——这些字段会进 `describe()` 描述面与 prompt，必须预算化。

## 2.4 与已有系统交互

| 既有设施 | 本任务的关系 | 是否改动 |
|---|---|---|
| `app/models/action.py` | 复用 `ActionIntent` / `ActionRecord` 作为 `ToolInvocation` 的承载；`GATE_REASONS` 扩 3 值 | 仅值域扩展 |
| `app/models/action.py::CapabilityResult` | `ToolResult` 是它的**语义强化版**，二者在 TOOL-003 建立映射；本任务只声明 `ToolResult` | 零改动 |
| `app/services/action/registry.py::Capability` | `ToolDefinition.capability/action` 指向它，解析在 TOOL-002 | 零改动 |
| `app/core/settings/_shared.py` | `ToolSettings` 继承 `BaseSettings` + `DOMAIN_MODEL_CONFIG`，模式照抄 `experience.py` / `world_simulation.py` | 零改动 |
| `app/core/settings/enablement.py` | 追加 v24 段校验，模式照抄 v23 段 | 增量追加 |
| 全局 `Settings` | `ToolSettings` 并入组装（与 `WorldSimulationSettings` 同款） | 增量追加 |

**与 `CapabilityResult` 的字段级映射预案**（本任务只登记，实现于 TOOL-003）：

| V9 `CapabilityResult` | V2.4.0 `ToolResult` | 策略 |
|---|---|---|
| `status`（4 值） | `status`（7 值，超集） | 扩展值域 |
| `payload`（自由 dict） | `effects` + `observations`（结构化） | 旧键保留双写一个版本窗口 |
| `payload["failure_kind"]` | 顶层 `failure_kind` | 旧位置保留 |
| `payload["deferred_world_op"]` | 不进 `observations` | 原样保留（outbox 依赖） |
| `usage` | `usage`（追加 tool_id / external_calls） | 增量 |

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 理由 |
|---|---|---|
| Table | 无新增 | `ToolDefinition` 是**代码资产**（同 V2.3.0 RoutineAsset 纪律：声明式资产不落库）。落库会引入"库中定义与代码不一致"的双源问题 |
| Field | 无新增 | 值对象全部为内存态；持久化需求由 `action_records.steps`（TOOL-003）与 `trigger_registry`（TOOL-005）承接 |
| Index | 无新增 | 同上 |
| Migration | 无 | 不生成迁移文件；`GATE_REASONS` 是 Python 值域，非 DB 约束 |

**运行期状态的落点裁决**（本任务定义，后续任务遵守）：

| 状态 | 落点 | 理由 |
|---|---|---|
| 代码态（enabled / deprecated / removed） | `ToolDefinition.status` | 随版本发布 |
| 运行期禁用（风控 / 熔断） | settings `v24_tool_disabled_ids` + 内存态 | 与 `v23_event_escalation_types` 同款形态 |
| 健康度 | 进程内存态 | 与 `_ACTION_FACTS_CACHE` / `_topic_buckets` 同款惯例，重启归零 |
| 执行台账 | `action_records.steps`（既有） | 见 TOOL-003 |

---

# 4. API / Interface Design

本任务的"接口"是**模型层契约**，非 HTTP 端点。

## 4.1 值对象接口

```text
model ToolDefinition:
    id / name / description / when_to_use / when_not_to_use
    namespace / capability / action
    input_schema / output_schema
    permission / status / version
    side_effects / idempotency / timeout_seconds / error_map
    tags / priority / memory_policy_key / observability_fields

    # 派生只读属性
    is_read_only() -> bool            # side_effects == ("read",)
    is_irreversible() -> bool
    effective_timeout(global_default: float) -> float

model ToolParameter:
    name / type / required / description / enum / default
    min / max / min_length / max_length / pattern / format
    sensitive / source_hint

model ToolSchema:
    parameters: list[ToolParameter]
    strict: bool = True
    semantic_validators: tuple[str, ...] = ()
    json_shape() -> dict              # 供 describe() 与决策层消费的投影

model PermissionProfile:
    level / scope / confirm / rate_limit
    requires_online / audit / scope_grant_ref / override_reason

model ToolBinding:
    tool_id / capability / action / definition

model ToolInvocation:
    tool_id / params / rationale / source / intent / goal_id
    dedupe_key / run_id / surface_hash

model ToolExecution:
    index / tool_id / capability / action / params / status
    permission / validation / result / started_at / duration_ms

model ToolResult:
    status / effects / observations / failure_kind
    error / usage / redacted / raw_error

model ToolEffect:
    kind / ref / detail / reversible

model ToolObservation:
    untrusted / source_tool / facts

model ToolSurface:
    run_kind / tool_ids / excluded / surface_hash

model ToolHealth:
    consecutive_failures / last_failure_at / last_success_at
    failure_rate_window / tripped
```

**Input / Output 约定**

| 模型 | 构造输入 | 输出形态 |
|---|---|---|
| `ToolDefinition` | 代码声明（注册期） | `model_dump(mode="json")` 供 `describe()` |
| `ToolInvocation` | 决策层产出 | 序列化后进 `action_records.params` |
| `ToolResult` | 归一器产出（TOOL-003） | 序列化后进 `action_records.steps[].result` |
| `ToolSurface` | 工具面解析器产出（TOOL-004） | 只读，进 `runtime_traces.steps` |

## 4.2 纯函数接口

```text
transition_tool_lifecycle(status: ToolLifecycle, event: str) -> ToolLifecycle | None
    # event ∈ {enable, disable, deprecate, retire}
    # 非法迁移返回 None

permission_level_rank(level: PermissionLevel) -> int          # safe=0 … dangerous=3

namespace_permission_floor(namespace: str) -> PermissionLevel

resolve_permission_level(
    declared: PermissionLevel,
    namespace: str,
    override_reason: str | None,
) -> PermissionLevel
    # 低于命名空间下限且无 override_reason → 抛 SettingsError
```

## 4.3 配置接口

```text
class ToolSettings(BaseSettings):
    # 总闸
    v24_tool_system_enabled: bool = False
    # 子闸
    v24_tool_permission_enabled: bool = False
    v24_tool_schema_validation_enabled: bool = False
    v24_tool_observation_enabled: bool = False
    v24_tool_surface_enabled: bool = False
    v24_tool_memory_enabled: bool = False
    v24_tool_reflection_enabled: bool = False
    v24_tool_channel_enabled: bool = False
    v24_tool_external_api_enabled: bool = False
    v24_tool_user_defined_enabled: bool = False
    # 参数
    v24_tool_disabled_ids: str = ""
    v24_tool_surface_max_tools: int = 12
    v24_tool_breaker_threshold: int = 3
    v24_tool_breaker_cooldown_seconds: int = 300
    v24_tool_confirm_timeout_hours: int = 24
    v24_tool_confirm_ttl_reuse: bool = True
    v24_tool_audit_retention_days: int = 180
    v24_tool_ext_manifest_path: str = ""
    v24_tool_ext_allowed_hosts: str = ""

    def disabled_tool_ids(self) -> frozenset[str]     # csv 解析
    def allowed_ext_hosts(self) -> frozenset[str]     # csv 解析
```

**Input**：环境变量 / `.env`。**Output**：只读配置对象 + 两个 csv 解析便捷方法。

---

# 5. Implementation Plan

## Step 1 — 工具域值对象（`app/models/tool.py`）

1. 定义五个枚举值域（ToolLifecycle / ToolExecutionStatus / ToolFailureKind / ToolEffectKind / PermissionLevel）与 `get_args` 导出的 frozenset 常量（对齐 `models/intention.py::_INTENTION_VALUES` 写法）。
2. 按 §2.2 定义全部 pydantic 模型；`ToolDefinition` 加长度预算 validator 与派生属性。
3. 定义两个纯函数（生命周期状态机、权限等级排序与下限判定）。
4. 单测：序列化往返、状态机全枚举（含非法迁移）、等级下限与 override 分支。

## Step 2 — 配置域（`app/core/settings/tool.py` + 全局组装）

1. 实现 `ToolSettings`，默认值全部取安全值；加参数自校验（阈值 > 0、surface 上限 ≥ 1）。
2. 按 settings 包既有方式并入全局 `Settings`。
3. 单测：默认值断言、csv 解析、非法参数 fail-fast。

## Step 3 — 启用链与行动域值域扩展

1. `enablement_violations` 追加 v24 段：任一子闸开启 ⇒ 总闸必须开启；`v24_tool_channel_enabled` ⇒ 总闸 + `feishu_enabled`；`v24_tool_external_api_enabled` ⇒ 总闸。
2. `models/action.py::GATE_REASONS` 追加 `permission_denied` / `invalid_params` / `pending_confirmation`。
3. 静态扫描测试：`models/tool.py` 零 `app.repositories` / `app.services` / `app.application` 依赖。
4. 全量既有测试回归（Flag 全 off，要求零修改通过）。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 全部 12 个值对象可实例化，`model_dump(mode="json")` → `model_validate` 往返一致。
- `transition_tool_lifecycle` 覆盖全部 (状态 × 事件) 组合；非法迁移返回 `None`。
- `permission_level_rank` 严格有序；`namespace_permission_floor` 五个命名空间取值正确。
- `resolve_permission_level` 三分支正确：达标放行、降级带理由放行并标记、降级无理由抛错。
- `ToolDefinition` 长度预算超限被拒（name / description / when_to_use / when_not_to_use / 参数 description 五项各一例）。
- `ToolSchema.json_shape()` 输出稳定且包含参数类型与必填标记。
- `ToolSettings` 全部 Flag 默认 False、参数默认值等于 architecture §7.8 表格值。

## 6.2 Integration Acceptance

- `ToolSettings` 成功并入全局 Settings，可通过 `get_settings()` 读取（与 `WorldSimulationSettings` 同款验证）。
- v24 串行链校验在启动边界生效：违规组合 fail-fast 且原因中文可读（逐条组合测试）。
- `GATE_REASONS` 新增 3 值后，既有行动域测试零失败（值域扩展无破坏）。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.3.0 逐字节一致（若本任务引入任何 prompt 影响即为缺陷）。
- 静态断言：模型层零仓储/服务/应用层依赖。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `ToolDefinition` 声明 `namespace="user"` 但 `permission.level="normal"` | 因低于命名空间下限且无 override_reason → 抛错 |
| E2 | 同上但携带 `override_reason` | 放行，且降级事实可在审计中观察到 |
| E3 | `tool_id` 含非法字符或仅单段（无命名空间） | 构造期拒绝 |
| E4 | `side_effects` 含 `irreversible` 但 `permission.audit=False` | 构造期强制改为 True（不抛错，纠正后放行） |
| E5 | `error_map` 映射到未知 `failure_kind` 值 | 拒绝，提示合法值集 |
| E6 | `v24_tool_surface_max_tools=0` 或负值 | 启动 fail-fast |
| E7 | `v24_tool_disabled_ids` 含空白项 / 重复项 / 未注册 id | 解析时去空白去重；未注册 id 不报错（仅运行期无匹配） |
| E8 | `status="removed"` 的工具试图 `enable` | 状态机返回 `None`（removed 为终态） |
| E9 | `output_schema` 缺省 | 合法，`ToolResult` 按通约处理（不因缺省而报错） |
| E10 | 全部 v24 Flag 为 off 时调用 `ToolSettings.disabled_tool_ids()` | 正常返回空集，不因总闸关闭而抛错 |
