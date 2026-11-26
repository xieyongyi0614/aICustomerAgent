# TOOL-002 Task Detail — Tool Registry

> 上游：[../architecture.md](../architecture.md) §4.2（Tool Registry）、§5.2（ToolDefinition）、§7.8（Flag 设计）；[../tasks.md](../tasks.md) TOOL-002
> 状态：设计稿（未实现）
> 范围红线：**只做声明与发现**，不做执行、不做授权判断、不做参数校验；不新建任何表；运行期不增删注册表（代码注册，同 V9 纪律）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-002 |
| **Task Name** | Tool Registry |
| **Priority** | P0 |
| **Dependencies** | TOOL-001 |
| **建议提交** | `feat: V2.4.0 工具注册表与内置声明` |

## 1.1 Goal

交付工具的**声明与发现唯一权威**。实现模块级单例注册表，建立五个命名空间与四态生命周期，落地注册期七项校验，并把 V9 既有六个 Capability 声明为可治理工具（**只声明，不实现新能力**）。

本任务结束后，系统应能回答"有哪些工具、每个长什么样、属于哪个命名空间、当前什么状态、最近健康度如何"，并能向决策层输出 LLM 可读的工具描述。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/registry.py`：`ToolRegistry` 单例 + `get_tool_registry()` + `register_builtin_tools()`。
- 落地注册期七项校验（§2.3）。
- 把 V9 六个 Capability 声明为 ≥ 9 个 `ToolDefinition`（映射表见 §2.4）。
- 实现 `describe()` / `list()` / `namespaces()` / `health()` / `record_outcome()`。
- 单测：快照稳定性、七项校验负例、命名空间下限、生命周期过滤、健康度只读/唯一写面。

**不包含（Non-Scope）**

- 工具面投影与选择（TOOL-004）。
- 执行、校验、授权（TOOL-003 / TOOL-005）。
- 通道类工具与外部 API 工具的**真实实现**（TOOL-010 / TOOL-011）；本任务若声明 `channel.*` / `ext.api.*`，仅登记占位声明且状态为 `disabled`。
- 熔断触发逻辑（TOOL-003）；本任务只提供 `record_outcome()` 写面与 `health()` 读面。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/registry.py` | 新增 | 注册表单例、七项校验、查询面、健康度读写 |
| `app/services/tool/__init__.py` | 新增 | 包声明 |
| `app/services/action/registry.py` | 复用不改 | 提供 `Capability` 与 `get_capability_registry()`，本任务只读它做绑定校验 |

**结构（对齐 V9 `CapabilityRegistry` 同款工程标准）**

```text
ToolRegistry（模块级单例，运行期不增删）
├── _tools      : dict[str, ToolDefinition]       # tool_id → 声明
├── _bindings   : dict[str, ToolBinding]          # tool_id → (capability, action, definition)
├── _health     : dict[str, ToolHealth]           # tool_id → 内存态健康度
├── _namespaces : dict[str, list[str]]            # namespace → tool_id 列表（索引）
└── 惰性构建：首次 get_tool_registry() 时 register_builtin_tools()（同 get_capability_registry）
```

**门控**：`v24_tool_system_enabled` 为 off 时**不构建**注册表，`get_tool_registry()` 返回 `None`；调用方（TOOL-004 起）在总闸关闭时走 V9 原路径。

## 2.2 数据结构

复用 TOOL-001 定义的 `ToolDefinition` / `ToolBinding` / `ToolHealth`；本任务新增两个**查询投影结构**（值对象，不落库）：

### ToolDescriptor（describe 输出项）

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_id` | str | 工具身份 |
| `name` | str | 中文名 |
| `description` | str | ≤ 120 字 |
| `when_to_use` | str? | ≤ 80 字 |
| `namespace` | str | 命名空间 |
| `params` | dict | 参数名 → {type, required, enum?}（由 `ToolSchema.json_shape()` 投影） |
| `side_effects` | tuple[str, ...] | 副作用标记 |
| `status` | str | 生命周期状态 |

### NamespaceIndex

| 字段 | 类型 | 说明 |
|---|---|---|
| `namespace` | str | 命名空间名 |
| `tool_ids` | list[str] | 该命名空间下的工具（按 tool_id 字典序，保证可复现） |
| `enabled_count` | int | 其中 enabled 的数量 |

## 2.3 核心流程

### 注册流程与七项校验

```text
register(definition, capability)
        │
        ├─ 校验 1｜id 格式：^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$
        ├─ 校验 2｜id 唯一：已存在即抛错（V9 register 拒绝重名同款）
        ├─ 校验 3｜命名空间白名单：builtin / channel / world / ext.api / user
        ├─ 校验 4｜capability 可解析：CapabilityRegistry.has(capability, action)
        ├─ 校验 5｜schema 自洽：ActionSchema.required ⊆ input_schema 的 required 参数名
        ├─ 校验 6｜permission 合法：等级 ≥ 命名空间下限（TOOL-001 纯函数）
        └─ 校验 7｜字段长度预算：name ≤ 20 / description ≤ 120 / when_to_use ≤ 80
        │
        ▼
   写入 _tools / _bindings / _namespaces 索引
```

**任一校验失败即抛错并终止注册**（不降级、不静默跳过）——注册是启动期行为，错误必须显式暴露。

### 生命周期状态判定

```text
effective_status(tool_id) -> ToolLifecycle
    1) 代码态为 removed / deprecated → 直接返回
    2) 命中 settings.v24_tool_disabled_ids → disabled
    3) 健康度 tripped（TOOL-003 写入）→ disabled
    4) 否则 → 代码态（enabled / disabled）
```

> 状态判定为**纯函数式叠加**：代码态是基线，运行期禁用与熔断是覆盖层。覆盖层不进 `ToolDefinition`（保持声明不可变）。

### 查询流程

```text
list(namespace=, status=, capability=, tags=) → list[ToolDefinition]
    过滤顺序：namespace → status（经 effective_status）→ capability → tags
    排序：tool_id 字典序（确定性）

describe(surface=None) → list[ToolDescriptor]
    无 surface → 全部 effective_status == enabled 的工具
    有 surface → 仅 surface.tool_ids 内的工具（保持 surface 顺序）
```

## 2.4 内置声明映射（V9 六能力 → ≥9 工具）

| tool_id | 绑定 (capability, action) | 命名空间 | 等级 | side_effects | idempotency | priority |
|---|---|---|---|---|---|---|
| `builtin.reminder.create` | (reminder, create) | builtin | normal | write_world | keyed | 10 |
| `builtin.reminder.cancel` | (reminder, cancel) | builtin | normal | write_world | keyed | 20 |
| `builtin.memory.save` | (memory, save) | builtin | normal | write_memory | keyed | 30 |
| `world.object.create` | (world_action, create) | world | normal | write_world | keyed | 40 |
| `world.object.move` | (world_action, move) | world | normal | write_world | keyed | 50 |
| `world.object.use` | (world_action, use) | world | normal | write_world | keyed | 60 |
| `world.env.query` | (environment_query, query) | world | safe | read | natural | 70 |
| `builtin.search.query` | (search, query) | builtin | safe | read | natural | 80 |
| `builtin.notification.send` | (notification, send) | builtin | sensitive | send_external | keyed | 90 |
| `channel.feishu.send` | (notification, send) | channel | sensitive | send_external | keyed | 100（占位，disabled） |
| `ext.api.*`（预留） | (external_api, call) | ext.api | sensitive | read + send_external | natural | — |

**声明纪律**：

- 本任务只声明，**不改任何 Capability 实现**；`search` / `notification` 仍返回 `unavailable`（TOOL-010 落地）。
- `channel.feishu.send` 在本任务声明为 `status=disabled`，TOOL-010 转 enabled 并接确认流。
- `memory_policy_key` 缺省取 `tool_id`（TOOL-008 消费）。

## 2.5 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/action/registry.py::get_capability_registry()` | 只读调用，做校验 4（capability 可解析）与绑定解析 | 零改动 |
| `services/action/registry.py::Capability` Protocol | `ToolBinding.capability/action` 指向它；**不修改 Protocol** | 零改动 |
| `models/action.py::ActionSchema` | 只读其 `required` 做校验 5；**不修改** | 零改动 |
| `core/settings/tool.py` | 读总闸与 `v24_tool_disabled_ids` | 零改动（TOOL-001 已建） |
| `application/action_engine.py::_build_snapshot` | TOOL-003 起会注入 `registry`；本任务不接线 | 零改动 |
| `decision_pipeline._CAPABILITY_TYPE_HINTS` | 本任务不改；TOOL-004 处理 tool_id → goal type 解析 | 零改动 |

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 理由 |
|---|---|---|
| Table | 无新增 | 工具权威定义是代码；建 `tool_registry` 表会引入双源不一致问题 |
| Field | 无新增 | 声明为内存态；运行期禁用走 settings（非 DB） |
| Index | 无新增 | 命名空间索引为内存 dict，非 DB 索引 |
| Migration | 无 | — |

**反模式警示（评审红线）**：若实现阶段出现"把工具定义写进数据库以便动态管理"的方案，即为设计违背——工具定义的权威来源必须是代码，运行期可变部分只允许"禁用清单"这一薄覆盖层。

---

# 4. API / Interface Design

## 4.1 注册表接口

```text
interface ToolRegistry:
    # 写入面（仅注册期）
    register(definition: ToolDefinition, capability: Capability) -> None
    unregister(tool_id: str) -> None

    # 解析面
    resolve(tool_id: str) -> ToolBinding | None
    get(tool_id: str) -> ToolDefinition | None
    has(tool_id: str, *, enabled_only: bool = True) -> bool

    # 查询面
    list(*, namespace: str | None = None,
              status: str | None = None,
              capability: str | None = None,
              tags: tuple[str, ...] | None = None) -> list[ToolDefinition]
    namespaces() -> dict[str, NamespaceIndex]
    describe(*, surface: ToolSurface | None = None) -> list[ToolDescriptor]

    # 健康度面
    health(tool_id: str | None = None) -> dict[str, ToolHealth]
    record_outcome(tool_id: str, *, ok: bool, failure_kind: str | None) -> None

    # 生命周期判定
    effective_status(tool_id: str) -> ToolLifecycle
```

**Input / Output**

| 方法 | Input | Output | 失败形态 |
|---|---|---|---|
| `register` | `ToolDefinition` + `Capability` | `None` | 抛 `ValueError` / `SettingsError`（含失败校验项与原因） |
| `resolve` | `tool_id` | `ToolBinding` 或 `None` | 未注册返回 `None`（不抛错） |
| `list` | 四维过滤 | `list[ToolDefinition]` | 无匹配返回空列表 |
| `describe` | 可选 `ToolSurface` | `list[ToolDescriptor]` | 空 surface 返回空列表 |
| `health` | 可选 `tool_id` | `dict[tool_id, ToolHealth]` | 未注册返回空 dict |
| `record_outcome` | `tool_id` + `ok` + `failure_kind` | `None` | 未注册工具静默忽略（不抛错，防打断执行链） |

## 4.2 单例入口

```text
get_tool_registry() -> ToolRegistry | None
    # v24_tool_system_enabled 为 off → None（调用方走 V9 原路径）
    # 首次调用惰性构建：ToolRegistry() + register_builtin_tools(registry)

register_builtin_tools(registry: ToolRegistry) -> None
    # 按 §2.4 映射表逐条 register；仅在总闸开启时被调用
```

## 4.3 健康度结构

```text
ToolHealth:
    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    failure_rate_window: list[bool] = []      # 有界滑动窗（供 TOOL-003 熔断）
    tripped: bool = False
```

**写面唯一性**：`record_outcome()` 是健康度的唯一写入方法；`health()` 只读。熔断的**触发判定**在 TOOL-003，本任务只提供存储与读写。

---

# 5. Implementation Plan

## Step 1 — 注册表骨架与七项校验

1. 实现 `ToolRegistry` 类与三个内部索引（`_tools` / `_bindings` / `_namespaces`）。
2. 实现七项校验为**独立私有函数**（每项可单测），`register` 按序短路。
3. 实现 `resolve` / `get` / `has` / `unregister`。
4. 单测：七项校验各一正例一负例；重复注册抛错；未注册 `resolve` 返回 `None`。

## Step 2 — 查询面与健康度面

1. 实现 `list`（四维过滤 + 字典序排序）、`namespaces()`、`describe()`（含 `ToolDescriptor` 投影）。
2. 实现 `effective_status`（代码态 + settings 覆盖 + 熔断覆盖三层叠加）。
3. 实现 `health()` / `record_outcome()`（有界滑动窗，窗口长度由常量控制）。
4. 单测：过滤组合、快照稳定性（同一版本 `describe()` 逐字节可复现）、状态叠加优先级、健康度重启归零。

## Step 3 — 内置声明与单例入口

1. 按 §2.4 映射表实现 `register_builtin_tools`（≥ 9 条声明 + `channel.feishu.send` 占位）。
2. 实现 `get_tool_registry()` 惰性单例（总闸 off 返回 `None`）。
3. 单测：总闸 off 时不构建；on 时工具集快照稳定；`channel.feishu.send` 声明为 disabled；命名空间下限生效（`user.*` 声明 normal 被拒）。
4. 回归：Flag 全 off 时既有测试零失败。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 注册表为模块级单例；`get_tool_registry()` 总闸 off 返回 `None`、on 时返回同一实例（惰性构建只发生一次）。
- 七项校验各有负例测试，失败即抛错且错误信息包含失败项与原因（可读中文）。
- ≥ 9 个内置工具声明齐备，`resolve` 均可回指到真实 Capability 与 action。
- `describe()` 输出包含 tool_id / name / description / 参数投影 / 副作用 / 状态，且同一代码版本逐字节可复现。
- `effective_status` 三层叠加优先级正确：熔断 > 运行期禁用 > 代码态。
- `health()` 只读、`record_outcome()` 为唯一写入面；重启归零。
- `namespaces()` 返回五个命名空间索引，`tool_ids` 按字典序。

## 6.2 Integration Acceptance

- 校验 4 通过 `get_capability_registry()` 真实解析，不使用硬编码能力名列表。
- 校验 5 与 `ActionSchema.required` 真实对齐：人为制造矛盾（required 含未声明参数）被拒。
- `ToolDefinition.permission.level` 与命名空间下限联动（TOOL-001 纯函数被真实调用）。
- **Flag 全 off 时全量既有测试零修改通过**；`CapabilityRegistry` 行为零变化（对照测试）。
- 本任务不改动 `services/action/registry.py` / `models/action.py`（diff 断言）。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 重复注册同一 `tool_id` | 抛错，提示重复 |
| E2 | `tool_id` 为单段（如 `reminder`）或含大写/连字符 | 格式校验拒绝 |
| E3 | 命名空间为未声明值（如 `plugin`） | 白名单校验拒绝 |
| E4 | `capability` 存在但 `action` 不在其 `actions` 中 | 校验 4 拒绝 |
| E5 | `input_schema` 缺少 `ActionSchema.required` 中的参数 | 校验 5 拒绝 |
| E6 | `user.*` 命名空间声明 `level="normal"` 且无 override_reason | 校验 6 拒绝 |
| E7 | `description` 超 120 字 | 校验 7 拒绝 |
| E8 | `v24_tool_disabled_ids` 命中某工具 | 该工具 `effective_status == disabled`，不进 `describe()` |
| E9 | `record_outcome` 传入未注册 tool_id | 静默忽略，不抛错（不打断执行链） |
| E10 | `describe(surface=...)` 传入含未注册 tool_id 的 surface | 忽略未注册项，不抛错（防御性） |
| E11 | 总闸 off 时调用 `get_tool_registry()` | 返回 `None`，且不触发 `register_builtin_tools`（副作用断言） |
| E12 | `unregister` 后重新 `register` 同 id | 允许（测试与热修场景），健康度重置 |
