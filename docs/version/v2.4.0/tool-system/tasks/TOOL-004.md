# TOOL-004 Task Detail — Tool Calling Pipeline

> 上游：[../architecture.md](../architecture.md) §4.1（Tool Decision Layer）、§6（调用流程）、§7.8（Flag 设计）、§8.6（管理面）；[../tasks.md](../tasks.md) TOOL-004
> 状态：设计稿（未实现）
> 范围红线：**不新增 chat_pipeline / post_process 步骤**（只增强既有步骤内部）；不新建决策管线（复用 V2.1 五段管线）；工具面投影为纯函数、零 IO、零 LLM。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-004 |
| **Task Name** | Tool Calling Pipeline |
| **Priority** | P0 |
| **Dependencies** | TOOL-002, TOOL-003 |
| **建议提交** | `feat: V2.4.0 工具调用链与工具面投影` |

## 1.1 Goal

交付**从用户消息到工具结果的完整调用链**。实现工具面投影（按 Run Profile / 日时段 / 场景 / 关系阶段 / 世界可用性 / 工具状态六维裁剪）、工具选择器（意图 → 工具绑定的确定性解析）、把工具面接入既有决策管线的 capability 候选，以及计划装配在总闸开启时改走注册表解析。

同任务交付**管理面调试端点**（工具清单 / 单工具详情 / 工具面投影含裁剪原因 / 执行台账投影），使整条链路的每一步都可被观察与排障。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/surface.py`：`ToolSurfaceResolver` / `ToolSelector` / `ToolSurfacePolicy`。
- 新增 `app/services/tool/context.py`：`ToolContext` 结构定义（**本任务为结构所有者**；世界事实填充由 TOOL-007 完成）。
- 扩展 `app/services/action/planner.py`：`assemble_plan` 在总闸开启时经 `ToolRegistry.resolve` 取绑定。
- 扩展 `app/services/decision_pipeline.py`：capability 候选携带 tool_id；`_CAPABILITY_TYPE_HINTS` 支持 tool_id 解析（默认映射兜底）。
- 扩展 `app/application/post_process.py`：第 9 步内部增强（**步骤数与序列不变**）。
- 扩展 `app/api/v1/debug.py` + `app/api/v1/schemas.py`：6 个调试端点。
- 角色资产 `app/character/asuna/tool.py`：工具面投影的场景与关系规则（纯数据）。

**不包含（Non-Scope）**

- 真实权限判定（TOOL-005）——本任务工具面投影**不读权限**，权限闸在执行器内（TOOL-003 占位 → TOOL-005 真实）。
- 自治侧实传 `capabilities`（TOOL-006）。
- 世界事实装配（TOOL-007）——本任务只定义 `ToolContext` 结构并接受可空世界字段。
- 工具实现体（TOOL-010）。
- prompt 中工具清单的渲染（本任务只提供 `describe()` 消费面；是否进 prompt 由 TOOL-010 的角色资产裁决，避免与 V2.3.0 prompt 预算冲突，见 Q5）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/surface.py` | 新增 | 工具面解析器 / 选择器 / 投影策略 |
| `app/services/tool/context.py` | 新增 | `ToolContext` 值对象（结构所有者） |
| `app/character/asuna/tool.py` | 新增 | 投影规则资产（Run Profile / 日时段 / 场景 / 关系阶段） |
| `app/services/action/planner.py` | 扩展 | 计划装配经注册表解析 |
| `app/services/decision_pipeline.py` | 扩展 | capability 候选带 tool_id |
| `app/application/post_process.py` | 扩展 | 第 9 步内部增强 |
| `app/api/v1/debug.py` / `schemas.py` | 扩展 | 6 个只读调试端点 |

**调用链全景**

```text
chat_pipeline（既有 10 步，形状不变）
   ├─ 第2步 world_engine.build_context（既有）
   ├─ ...（既有步骤全部不变）
   └─ post_process 第9步 run_action_planning（内部增强）
            │
            ▼
      ToolSurfaceResolver.resolve(run_kind, ctx) → ToolSurface
            │
      decision_pipeline.run_pipeline(capabilities=surface.tool_ids, ...)  ← 前台侧
            │  六维评分 + 四闸（既有）
            ▼
      ToolSelector.select(intent, surface) → ToolBinding
            │
            ▼
      action_engine.run_action_planning（既有编排）
            │  assemble_plan 经 ToolRegistry.resolve
            ▼
      ToolExecutor.run（TOOL-003）
```

## 2.2 数据结构

### ToolContext（本任务为结构所有者）

| 字段 | 类型 | 来源 | 可空 |
|---|---|---|---|
| `user_id` | str | 调用方 | 否 |
| `character_id` | str | 默认 `asuna` | 否 |
| `now` | datetime | 调用方 | 否 |
| `settings` | Any | 全局 settings | 否 |
| `run_kind` | str | Run Profile | 否 |
| `run_id` | str? | `loop_runs.id` | 是 |
| `source` | str | conversation / autonomy / event_driven | 否 |
| `world` | dict | 世界事实（TOOL-007 填充） | 是（默认 `{}`） |
| `inventory` | list[str] | 库存物品名（TOOL-007） | 是（默认 `[]`） |
| `situations` | list[dict] | 活跃用户处境（TOOL-007） | 是（默认 `[]`） |
| `scene` | dict | 场景画像（TOOL-007） | 是（默认 `{}`） |
| `relationship` | dict | `{stage, tension}`（TOOL-007） | 是（默认 `{}`） |
| `authorized_recipients` | list[str] | 已授权收件人（TOOL-005 填充） | 是（默认 `[]`） |

**纪律**：`ToolContext` 是**只读预读快照**，对齐 V9 `planner.GateSnapshot` 的"调用方预读、闸门内零 IO"范式。工具实现体禁止自行读仓储（TOOL-007 静态扫描强制）。

### ToolSurface

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_kind` | str | 投影所用 Run Profile |
| `tool_ids` | tuple[str, ...] | 有序（按 priority → tool_id 字典序） |
| `excluded` | tuple[dict, ...] | `{tool_id, reason}` 裁剪清单 |
| `surface_hash` | str | sha1(规范化输入 + tool_ids)[:16]，同输入同输出 |

### SurfaceRule（投影规则，角色资产）

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_kind` | str | 规则适用 Profile |
| `exclude_namespaces` | tuple[str, ...] | 整命名空间剔除 |
| `exclude_tags` | tuple[str, ...] | 按标签剔除 |
| `max_tools` | int? | 覆盖全局上限 |
| `reason` | str | 裁剪原因文案（进 `excluded[].reason`） |

**规则资产内容（按 architecture §4.1 投影规则表）**

| 维度 | 规则 |
|---|---|
| Run Profile | `autonomous_tick` → 剔除 `channel` 命名空间；`event_driven` → 只保留 `side_effects ⊆ {read}` |
| 日时段 | `late_night`（V2.3.0 `PartOfDay`）→ 剔除 `channel.*` 与标签 `social` |
| 场景 | 场景画像 `tone_bias` 为放松型 → 放开标签 `ambient`；工作型 → 剔除标签 `ambient` |
| 关系阶段 | `stage` 低于 `friend` → 剔除标签 `intimate` |
| 世界可用性 | `settings.world_enabled=False` → 剔除 `world` 命名空间 |
| 工具状态 | `effective_status != enabled` → 剔除（原因含 disabled / deprecated / tripped） |

## 2.3 核心流程

### 工具面投影（纯函数）

```text
resolve(run_kind, ctx) -> ToolSurface
   │
   ├─ 取候选全集：ToolRegistry.list()（effective_status == enabled）
   ├─ 按 6 维规则逐条过滤，每条命中记录 {tool_id, reason}
   ├─ 排序：priority 升序 → tool_id 字典序（确定性 tiebreak）
   ├─ 截断：v24_tool_surface_max_tools（超出者进 excluded，reason="surface_limit"）
   └─ 计算 surface_hash
```

**零 IO / 零 LLM 断言**：全部输入来自 `ToolContext` 与注册表内存态；无 DB 查询、无网络、无 LLM 调用。

### 工具选择（纯函数）

```text
select(intent: ActionIntent, surface: ToolSurface) -> ToolBinding | None
   │
   ├─ 按 ACTION_TOOL_MAP（action_type → tool_id 候选集）取候选
   ├─ 与 surface.tool_ids 取交集（不在面上的工具不可选）
   ├─ 交集空 → 返回 None（工具不可用，等价于 V9 capability_unavailable）
   ├─ 交集多条 → priority 升序 → tool_id 字典序取首（确定性）
   └─ resolve 为 ToolBinding
```

**`ACTION_TOOL_MAP` 落点**：扩展既有 `app/character/asuna/action.py::ACTION_CAPABILITY_MAP` 的用法——保留原表（V9 兼容），新增 `ACTION_TOOL_MAP` 作为工具身份映射（action_type → tool_id 候选集，值域为元组以支持一词多工具）。总闸 off 时只读原表。

### 决策管线接线

```text
decision_pipeline.run_pipeline(
    stack            = goal_stack,           # 既有
    snapshot         = agent_state_context,  # 既有
    capabilities     = surface.tool_ids,     # ★ 前台侧本任务接入
    world_impacts    = ...,                  # 既有（V2.3.0）
    world_schedule   = ...,                  # 既有（V2.3.0）
)
    → collect_candidates 产出 capability 候选（P3），payload = {tool_id, type}
    → score_candidates 六维评分（goal_alignment 由 tool_id 解析 goal type）
    → run_risk_gates 四闸（既有）
    → select() 确定性 tiebreak
```

**前台铁律不变**：前台 `chat_response` 候选（P0）恒胜出，工具候选只参与评分与审计（`decision_records`），不改变前台回复行为——与 V2.1 收编时的差异语义一致。

### 计划装配接线

```text
planner.assemble_plan(intent, snapshot, now, goal_id)
    if v24_tool_system_enabled:
        binding = ToolRegistry.resolve(ToolSelector.select(intent, surface))
        if binding is None → 返回 None（既有 capability_unavailable 语义）
        schema = binding.definition.input_schema
        校验（V9 弱校验 + TOOL-003 双层校验在 executor 内）
        → ActionPlan(steps=[ActionStep(index=0, capability=binding.capability,
                                        action=binding.action, params=...)])
    else:
        ← V9 原路径（ACTION_CAPABILITY_MAP 直查表）
```

**关键**：`ActionStep` 结构**不变**（V9 既有），tool_id 由 `ToolExecutor` 在 `steps[].result` 中回填——**不给 `ActionStep` 加字段**，避免改动 V9 模型。

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/decision_pipeline.py` | `capabilities` 参数（已存在）首次被前台实传；`_CAPABILITY_TYPE_HINTS` 支持 tool_id 前缀解析 | 增量 |
| `services/action/planner.py::assemble_plan` | 总闸 on 时经注册表解析；off 时原路径 | 分支 |
| `services/action/planner.py::GateSnapshot` | 复用其"预读"范式；`ToolContext` 与它并列注入 | 增量（可选加字段） |
| `application/post_process.py::run_action_planning` | 第 9 步内部：装配 `ToolContext` + 算工具面 + 传 `capabilities` | 增量 |
| `application/chat_pipeline.py` | **零改动**（步骤数与序列不变） | 零改动 |
| `app/character/asuna/action.py` | 保留 `ACTION_CAPABILITY_MAP`；新增 `ACTION_TOOL_MAP` | 增量 |
| `app/api/v1/debug.py` | 追加 6 个只读端点，风格对齐 WS-018 | 增量 |
| `app/services/tool/registry.py` | 只读消费 `list()` / `resolve()` / `describe()` | 零改动 |

---

# 3. Database Changes

**本任务无 DDL 变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 工具面是运行期值对象，不落库 |
| Field | 无新增列 | 工具面投影结果落 `runtime_traces.steps`（既有 JSON 列），不新增列 |
| Index | 无新增 | — |
| Migration | **无** | — |

**观测落点**：工具面投影结果（`surface_hash` / `tool_ids` / `excluded`）经既有 `trace.record()` 写入 `runtime_traces.steps`，与 V2.3.0 WS-018 的观测通道同构——**不新建观测表**。

---

# 4. API / Interface Design

## 4.1 工具面接口

```text
interface ToolSurfaceResolver:
    resolve(run_kind: str, ctx: ToolContext) -> ToolSurface

interface ToolSelector:
    select(intent: ActionIntent, surface: ToolSurface) -> ToolBinding | None

interface ToolSurfacePolicy:
    policy_for(run_kind: str) -> SurfaceRule
    should_exclude(defn: ToolDefinition,
                   ctx: ToolContext,
                   rule: SurfaceRule) -> str | None      # 返回裁剪原因，None 表示保留
```

| 方法 | Input | Output | 失败形态 |
|---|---|---|---|
| `resolve` | Run Profile + `ToolContext` | `ToolSurface` | 注册表为 `None`（总闸 off）→ 返回空 surface，调用方走 V9 原路径 |
| `select` | 意图 + 工具面 | `ToolBinding` 或 `None` | 交集为空 → `None`（不抛错） |
| `should_exclude` | 声明 + 上下文 + 规则 | 原因字符串或 `None` | 规则缺失 → `None`（不排除） |

## 4.2 调试端点（管理面）

| 方法 | 路径 | 用途 | 门控 |
|---|---|---|---|
| GET | `/api/v1/debug/tools` | 工具清单（声明 + 状态 + 健康度） | 总闸 |
| GET | `/api/v1/debug/tools/{tool_id}` | 单工具详情（schema / permission / 最近执行） | 总闸 |
| GET | `/api/v1/debug/tools/surface?run_kind=` | 工具面投影结果（含裁剪原因） | 总闸 + `v24_tool_surface_enabled` |
| POST | `/api/v1/debug/tools/{tool_id}/disable` | 运行期禁用（风控） | 总闸 |
| POST | `/api/v1/debug/tools/{tool_id}/enable` | 恢复 | 总闸 |
| GET | `/api/v1/debug/tools/executions?user_id=` | 执行台账（从 `action_records.steps` 投影） | 总闸 |

**Input / Output**

| 端点 | Input | Output |
|---|---|---|
| `/debug/tools` | 无 | `[{tool_id, name, namespace, status, side_effects, health}]` |
| `/debug/tools/{id}` | path 参数 | `{definition, permission, recent_executions[]}` |
| `/debug/tools/surface` | `run_kind`（query，可选 `user_id`） | `{run_kind, tool_ids, excluded[], surface_hash}` |
| `/disable` / `/enable` | path 参数 | `{tool_id, effective_status}` |
| `/debug/tools/executions` | `user_id`（query，必填） | `[{record_id, tool_id, status, permission, duration_ms, effects[]}]` |

**门控行为（对齐 WS-018 惯例）**：总闸 off → 返回 `200 {"enabled": false}`；写类端点（disable / enable）在总闸 off 时返回 `403`。

## 4.3 决策管线接口（增量）

```text
decision_pipeline.collect_candidates(
    ...,
    capabilities: list[str] | None = None,      # 既有参数，值语义从"能力名"扩展为"tool_id"
) -> list[Candidate]
    # capability 候选 payload = {"tool_id": <id>, "type": <由 tool_id 解析的 goal type>}

resolve_goal_type_from_tool_id(tool_id: str) -> str
    # 优先查 ACTION_TOOL_TYPE_HINTS；未命中回退 _CAPABILITY_TYPE_HINTS 的旧映射
```

---

# 5. Implementation Plan

## Step 1 — ToolContext 与工具面投影

1. 定义 `ToolContext` 值对象（世界字段全部可空 + 默认空值）。
2. 在 `app/character/asuna/tool.py` 落地 `SurfaceRule` 资产（六维规则）。
3. 实现 `ToolSurfaceResolver.resolve`：过滤 → 排序 → 截断 → 哈希，逐条记录裁剪原因。
4. 单测：六维规则各一正例一负例；`surface_hash` 同输入同输出；上限截断；**零 IO 断言**（打桩 DB 与网络为 0 次调用）。

## Step 2 — 工具选择与计划装配接线

1. 在 `action.py` 新增 `ACTION_TOOL_MAP`（保留 `ACTION_CAPABILITY_MAP` 不动）。
2. 实现 `ToolSelector.select`（交集 + priority + 字典序 tiebreak）。
3. 扩展 `planner.assemble_plan`：总闸 on 走注册表解析，off 走原路径。
4. 单测：选择确定性（重复运行结果一致）、交集为空返回 None、off 路径与 V9 逐字节一致。

## Step 3 — 决策接线、第 9 步增强与调试端点

1. 扩展 `decision_pipeline`：capability 候选带 tool_id；`_CAPABILITY_TYPE_HINTS` 支持 tool_id 解析并保留旧映射兜底。
2. 扩展 `post_process.run_action_planning`：装配 `ToolContext` → 算工具面 → 传 `capabilities`（**不改步骤数与序列**）。
3. 实现 6 个调试端点与响应模型。
4. 单测：工具候选进评分与审计、前台 `chat_response` 仍恒胜出、管线形状快照（步骤数与阶段数对齐 V2.3.0）、端点门控。
5. 回归：Flag 全 off 时 prompt 逐字节一致、`chat_pipeline` / `post_process` 零 diff。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 工具面投影六维规则全部生效，每条裁剪携带可读 reason。
- 同一意图在不同 Run Profile / 日时段 / 关系阶段下投影出**不同工具面**（有可复现用例）。
- `surface_hash` 同输入同输出；工具面排序与截断确定性（重复运行逐字节一致）。
- `ToolSelector.select` 一词多工具时按 priority + tool_id 字典序确定性选择。
- 工具候选进入六维评分并落 `decision_records` 审计（含 scores / gates / won）。
- 调试端点 6 个全部可用，输出结构与 §4.2 一致；执行台账由 `action_records.steps` 正确投影。
- 工具面投影零 IO、零 LLM（打桩断言）。

## 6.2 Integration Acceptance

- `chat_pipeline.py` **零 diff**；`post_process.py` 步骤数与序列与 V2.3.0 一致（形状快照）。
- 前台 `chat_response` 候选仍恒胜出（P0 铁律），工具候选不改变前台回复行为。
- `planner.assemble_plan` 总闸 on/off 两路径均可工作；off 路径与 V9 逐字节一致。
- `ACTION_CAPABILITY_MAP` 保留且行为不变（V9 回归测试零失败）。
- 调试端点风格与 WS-018 一致（门控、响应包裹、`enabled: false` 惯例）。
- **Flag 全 off 时**：prompt 逐字节一致、既有测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 注册表为 `None`（总闸 off） | `resolve` 返回空 surface；调用方走 V9 原路径，不抛错 |
| E2 | 工具面为空（全部被裁） | `select` 返回 `None` → 计划装配返回 `None` → `capability_unavailable` |
| E3 | 某工具同时命中两条裁剪规则 | 记录首条命中原因（短路），不重复记录 |
| E4 | `v24_tool_surface_max_tools=1` 且候选 5 个 | 保留 priority 最小者，其余进 excluded（reason=`surface_limit`） |
| E5 | `ToolContext.world` 为空 dict（TOOL-007 未完成） | 世界相关规则降级为不裁剪（不误裁），记录降级标记 |
| E6 | `run_kind` 为未注册值 | 取默认规则（不裁剪 + 不报错），并记 warning |
| E7 | 同一 action_type 映射到 3 个 tool_id 且全部在面上 | 按 priority 取首，其余不作为候选（不产生重复候选） |
| E8 | `ACTION_TOOL_MAP` 未覆盖某 action_type | 回退 `ACTION_CAPABILITY_MAP` 旧映射；仍无则 `select` 返回 `None` |
| E9 | 调试端点查询未注册 tool_id | 返回 404（读类）而非 500 |
| E10 | 调试端点 disable 未注册 tool_id | 返回 404 并说明；不写入禁用清单 |
| E11 | `/debug/tools/surface` 未传 `run_kind` | 使用默认（`foreground_chat`）并标注 |
| E12 | 执行台账查询无记录的 user_id | 返回空列表（非 404） |
| E13 | 工具面投影过程中某工具声明缺 `tags` | 按"无标签"处理，不因缺省而误裁 |
| E14 | 场景画像含未知 `tone_bias` 值 | 不做场景维度裁剪（保守），记录 warning |
