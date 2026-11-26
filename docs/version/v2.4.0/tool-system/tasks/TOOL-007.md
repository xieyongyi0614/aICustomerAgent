# TOOL-007 Task Detail — World Simulation Integration

> 上游：[../architecture.md](../architecture.md) §7.3（Tool 与 World Simulation 集成）、§4.1（Tool Decision Layer）、§9.5（安全不变量）；[../tasks.md](../tasks.md) TOOL-007
> 状态：设计稿（未实现）
> 范围红线：**工具永不直接修改世界状态**；世界唯一写面仍是 `world_engine`；世界域与角色域的表结构零改动；不新增维护步。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-007 |
| **Task Name** | World Simulation Integration |
| **Priority** | P1 |
| **Dependencies** | TOOL-004, TOOL-005 |
| **建议提交** | `feat: V2.4.0 工具与世界读写契约` |

## 1.1 Goal

钉死工具与世界的**读写契约**，把 architecture §7.3 散落的规则收敛为可执行、可扫描、可测试的三件事：

1. **读**：工具所需的世界事实由调用方**预读注入** `ToolContext`，工具实现体零仓储读取。
2. **写**：工具写世界一律经延迟投递唯一路径（`deferred_world_op` → outbox → 消费器 → `world_engine`），**永不直写**。
3. **守**：交付静态扫描护栏，使"工具直写世界"在 CI 阶段即被拦截，而非依赖评审自觉。

同时预留 `world.intent.submit`（角色意图提交给世界侧裁决）接口，为"角色想做什么"与"世界允许什么"提供正确的解耦点。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/world_context.py`：世界事实预读装配（填充 TOOL-004 定义的 `ToolContext` 世界字段）。
- 扩展 `application/action_engine.py::_build_snapshot`：装配世界事实并注入 `ToolContext`。
- 新增静态扫描护栏测试：工具实现体禁止导入世界仓储 / 角色状态 / 关系域。
- 扩展 `app/services/tool/surface.py`：世界可用性维度规则接入（`world_enabled=False` 时剔除 `world` 命名空间）。
- 预留 `world.intent.submit` 接口（**只冻结形状，不实现**）。
- 扩展 `outbox_consumer`：确认工具产生的世界操作走既有消费路径（**零新增消费逻辑**）。
- 单测：预读降级、outbox 唯一路径、静态扫描、语义校验器的世界事实供给。

**不包含（Non-Scope）**

- 世界侧模拟逻辑（V2.3.0 已交付，零改动）。
- 工具实现体（TOOL-010）。
- 多世界 / 多角色并发仲裁（architecture §10 留后续版本）。
- `world.intent.submit` 的**实际消费**（需世界侧新增裁决逻辑，留后续版本）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/world_context.py` | 新增 | 世界事实预读装配（只读） |
| `app/application/action_engine.py` | 扩展 | `_build_snapshot` 注入世界事实 |
| `app/services/tool/surface.py` | 扩展 | 世界可用性维度规则 |
| `app/application/outbox_consumer.py` | 复用不改 | 工具产出的世界操作走既有消费路径 |
| `app/services/tool/world_intent.py` | 新增 | `world.intent.submit` 接口形状（占位，不接线） |
| `tests/v24/test_tool_world_guard.py` | 新增 | 静态扫描护栏 |

**读写契约图**

```text
                    ┌─────────────────── 读路径（预读注入）───────────────────┐
                    │                                                          │
调用方（action_engine._build_snapshot）                                       │
    │  world_engine.get_world / list_active_objects / list_active_events      │
    │  world_engine.get_objects_by_location / build_time_context             │
    │  world_simulation 读取（daily_plans 当前块 / user_situations active）    │
    │  scene 画像 / 关系阶段（既有只读）                                        │
    ▼                                                                          │
ToolContext{world, inventory, situations, scene, relationship}  ──────────────┘
    │
    │  工具实现体只读 ToolContext，禁止自行查库
    ▼
                    ┌─────────────────── 写路径（延迟投递）───────────────────┐
                    │                                                          │
ToolResult.effects(kind="world")                                              │
    │  → payload.deferred_world_op = {op, args}                              │
    ▼                                                                          │
action_repository.save_record_with_outbox(幂等键 = action_id)                  │
    ▼                                                                          │
outbox_consumer._apply_world_op  →  getattr(world_engine, op)(*args)           │
    ▼                                                                          │
world_engine（唯一写面）→ world_repository（落库）  ───────────────────────────┘
```

## 2.2 数据结构

### 世界事实段（`ToolContext.world`）

| 键 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `location` | str | `worlds.current_location` | 当前地点 id |
| `location_name` | str | `LocationRegistry` | 中文名 |
| `weather` | str | `worlds.environment.weather` | 天气 |
| `part_of_day` | str | `TimeContext` | 日时段（V2.3.0） |
| `current_block` | dict? | `daily_plans` 当前 active 块 | `{activity, location_id, part_of_day}` |
| `active_events` | list[dict] | `world_events`（scheduled/active） | `{type, title, due_at}`，≤ 5 条 |
| `world_enabled` | bool | settings | 供投影规则判定 |

### 库存与处境段

| 字段 | 类型 | 来源 | 上限 |
|---|---|---|---|
| `inventory` | list[str] | `list_active_objects` | 20 个物品名 |
| `situations` | list[dict] | `user_situations`（active） | 3 条 `{dimension, summary, intensity}` |
| `scene` | dict | `SceneProfile` 资产（V2.3.0） | `{location_id, tone_bias, topic_affordances}` |
| `relationship` | dict | `relationship_state`（只读投影） | `{stage, tension}` |

### WorldIntent（接口预留）

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | str | 意图主体 |
| `intent_type` | str | `tidy_room` / `move_location` / `start_activity` 等 |
| `target` | str? | 目标对象或地点 |
| `reason` | str | 意图来源摘要（≤ 80 字） |
| `created_at` | datetime | — |

## 2.3 核心流程

### 世界事实预读（逐段降级）

```text
build_world_facts(user_id, ctx) -> dict
   ├─ world_enabled off → 返回 {"world_enabled": False}（其余键缺省）
   ├─ 逐段读取，每段独立 try：
   │    ① world 基本信息（地点 / 天气）
   │    ② TimeContext（日时段）
   │    ③ 当前日程块（daily_plans active）
   │    ④ 活跃事件（≤5）
   │    ⑤ 库存（≤20）
   │    ⑥ 活跃处境（≤3）
   │    ⑦ 场景画像
   │    ⑧ 关系阶段投影
   └─ 任一段失败 → 该段缺省 + 日志，**不抛出**（World 旁路纪律）
```

**降级语义**：缺省字段的消费方（语义校验器、投影规则）必须按"信息不足 → 保守不误判"处理，而非"缺失即拒绝"。这是 V8 "世界永远是旁路，失败只降级"纪律的延续。

### 世界写入唯一路径

```text
工具产出世界效果（三条合法形态）
  ① 只读世界      → 直接读 ToolContext（零副作用）
  ② 延迟写世界    → payload.deferred_world_op = {op, args}（本任务保障的唯一写路径）
  ③ 提交世界意图  → world.intent.submit（接口预留，本版本不实现）

写入执行（全部沿用 V9 既有）
  action_repository.save_record_with_outbox(record, payload, idempotency_key=record.id)
        ▼
  outbox_consumer.consume_pending（既有）
        ▼
  _apply_world_op：getattr(world_engine, op_name)(*args)
        · 未知 op → 抛错（进入重试 / 死信）
        · 返回 None（容量上限 / 世界不可用）→ 抛错（进入重试 / 死信）
        · create_event 成功 → 打 outbox_action_id 指纹（重放幂等护栏）
```

**本任务对 outbox 的改动为零**——工具产出的 `deferred_world_op` 与 V9 行动产出形态完全一致，消费路径原样复用。

### 静态扫描护栏

```text
扫描目标：app/services/tool/**  +  各工具实现体所在模块
禁止导入：
    app.repositories.world_repository
    app.repositories.character_state_repository
    app.repositories.personality_state_repository
    app.repositories.relationship_*_repository
    app.repositories.world_simulation_repository（写面）
禁止调用：
    world_engine 中带副作用的函数（create_/move_/set_/apply_/discard_/consume_/expire_）
允许：
    world_engine 只读函数（get_/list_/build_/find_）
```

实现方式：AST 解析 + 函数名白/黑名单（比正则更可靠，能区分 import 与调用）。

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `application/world_engine.py` | 只读函数用于预读；写函数仅被 `outbox_consumer` 调用 | **零改动** |
| `application/world_engine.py::build_context` | 不被本任务复用（它是 prompt 装配，本任务要结构化事实） | 零改动 |
| `application/world_engine.py::collect_facts` | 语义不同（那是自治事实包），本任务不复用但结构参照 | 零改动 |
| `services/world/locations.py` | 地点名解析（预读用） | 只读 |
| `services/world/daily_plan.py` | 当前块读取 | 只读 |
| `services/world/user_situation.py` | 活跃处境读取 | 只读 |
| `services/world/scene_profiles.py` | 场景画像读取 | 只读 |
| `application/outbox_consumer.py::_apply_world_op` | 工具产出世界操作的唯一消费入口 | **零改动** |
| `repositories/world_repository.py` | 仅被 `world_engine` 使用；工具层禁止导入 | 零改动 |
| `application/action_engine.py::_build_snapshot` | 注入世界事实到 `ToolContext` | 增量 |
| `services/tool/surface.py` | 世界可用性维度规则 | 增量 |
| V2.3.0 世界域六表 | 结构零改动 | 零改动 |

**与 V2.3.0 世界模拟的关系**：本任务**只消费** V2.3.0 的产出（`daily_plans` 当前块、`user_situations`、`TimeContext`、`SceneProfile`），不修改其任何逻辑。世界模拟的维护步序列、事件 SoT、幂等键机制全部零改动。

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 世界事实为运行期预读结果；世界域六表（`worlds` / `world_entities` / `world_events` / `world_snapshots` / `daily_plans` / `user_situations`）结构零改动 |
| Field | 无新增列 | `ToolContext` 为内存态；`WorldIntent` 接口预留，本版本不落库 |
| Index | 无新增 | 预读全部走既有查询函数与其既有索引 |
| Migration | **无** | — |

**反模式警示（评审红线）**：若实现阶段出现"为工具新建世界状态表"或"为 `world.intent.submit` 新建意图表"的方案，即为设计违背。意图提交在后续版本落地时应写入既有 `world_events`（`type=character_intent`，属世界域合法写入），**不新建表**。

---

# 4. API / Interface Design

## 4.1 世界事实装配接口

```text
interface WorldContextBuilder:
    build(user_id: str, *, now: datetime, settings: Any) -> dict
        # 返回 ToolContext 的世界字段集合
        # 逐段降级：任一段失败只缺省该段，不抛出
    build_inventory(user_id: str, limit: int = 20) -> list[str]
    build_situations(user_id: str, limit: int = 3) -> list[dict]
    build_scene(user_id: str) -> dict
    build_relationship(user_id: str) -> dict
```

| 项 | 内容 |
|---|---|
| **Input** | `user_id` + 时刻 + settings |
| **Output** | 世界事实 dict（键集见 §2.2） |
| **失败形态** | **不抛异常**——逐段降级，失败段缺省并记日志 |
| **纪律** | 只调用 `world_engine` / `services/world/*` 的**只读**函数 |

## 4.2 世界意图接口（预留，本版本不实现）

```text
interface WorldIntentSubmitter:
    submit(intent: WorldIntent, ctx: ToolContext) -> str
        # 返回世界事件 id
        # ⚠ 本版本只冻结形状：调用即返回 unavailable，不产生任何写入
```

| 项 | 内容 |
|---|---|
| **Input** | `WorldIntent` + `ToolContext` |
| **Output** | 世界事件 id（本版本恒为 unavailable 占位） |
| **纪律** | 未接线必须在调试端点可见（`status: not_wired`），防止"看着有其实没有" |

## 4.3 静态扫描接口（测试层）

```text
interface WorldWriteGuard:
    scan_tool_modules(root: str) -> list[Violation]
        # Violation: {file, line, kind, detail}
    assert_no_world_write(violations: list[Violation]) -> None   # 非空即测试失败
```

## 4.4 投影规则增量接口

```text
ToolSurfacePolicy.should_exclude(defn, ctx, rule) -> str | None
    # 新增世界可用性分支：
    #   ctx.world.get("world_enabled") is False 且 defn.namespace == "world"
    #   → 返回 "world_disabled"
```

---

# 5. Implementation Plan

## Step 1 — 世界事实预读装配

1. 实现 `WorldContextBuilder` 的八段预读，逐段独立降级。
2. 复用 V2.3.0 既有只读函数（`locations` / `daily_plan` / `user_situation` / `scene_profiles`），不新写查询。
3. 注入 `ToolContext`（在 `action_engine._build_snapshot` 中调用）。
4. 单测：八段各一成功一失败用例；全部失败时返回可用（非空）结构；世界 off 时的形态。

## Step 2 — 世界写入唯一路径与静态护栏

1. 验证工具产出 `deferred_world_op` 经既有 outbox 路径落库（端到端测试，不改消费器）。
2. 实现 `WorldWriteGuard`：AST 解析工具模块，检出禁止导入与禁止调用。
3. 在 `surface.py` 接入世界可用性维度规则。
4. 单测：outbox 幂等与崩溃重放续走；静态扫描对人为注入的违规代码能捕获；只读函数不被误报。

## Step 3 — 世界意图接口预留与语义校验供给

1. 冻结 `WorldIntentSubmitter` 接口形状（占位实现返回 unavailable）。
2. 在调试端点暴露 `not_wired` 状态。
3. 打通 `location_exists` / `object_in_inventory` 两个语义校验器的世界事实供给（TOOL-003 已建校验器，本任务供数据）。
4. 单测：接口 schema 测试；语义校验器端到端；`world.intent.submit` 调用零写入（打桩断言）。
5. 回归：V2.3.0 世界侧测试零失败。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- `WorldContextBuilder.build` 八段预读全部生效；任一段失败只缺省该段，整体不抛出。
- 世界事实键集与 §2.2 一致（location / weather / part_of_day / current_block / active_events / inventory / situations / scene / relationship）。
- 各段有界：`active_events ≤ 5` / `inventory ≤ 20` / `situations ≤ 3`。
- `location_exists` 与 `object_in_inventory` 语义校验器有真实世界事实供给，正例通过、负例拦截。
- 世界可用性投影规则生效：`world_enabled=False` 时 `world.*` 工具被裁剪（reason=`world_disabled`）。
- `WorldIntentSubmitter.submit` 恒返回 unavailable 占位且**零写入**（打桩断言 DB 写为 0）。

## 6.2 Integration Acceptance

- **静态扫描护栏生效**：`app/services/tool/**` 与工具实现体零禁止导入、零禁止调用；人为注入违规代码时测试失败（自测护栏本身有效）。
- **世界写入唯一路径**：工具产生的世界效果全部经 `deferred_world_op` → outbox → `world_engine`；无任何工具实现体直接调用 `world_repository`。
- outbox 幂等与崩溃重放续走行为与 V9 逐字节一致（消费器零改动，diff 断言）。
- V2.3.0 世界侧测试**零失败**；世界域六表结构零改动（模型 diff 断言）。
- `world_engine` 零 diff；`outbox_consumer` 零 diff。
- 维护步序列零改动（`life_loop` diff 断言）——本任务不新增维护步。
- **Flag 全 off 时**：`ToolContext` 不被装配，`_build_snapshot` 行为与 V2.3.0 一致；既有测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `world_enabled=False` | 预读返回 `{"world_enabled": False}`，其余键缺省；`world.*` 工具被裁剪 |
| E2 | 用户尚无世界记录（`get_world` 返回 None） | 世界段缺省，不抛错；不触发世界创建（**不得隐式 `ensure_world`**） |
| E3 | `daily_plans` 无 active 块（如 V2.3.0 日程未启用） | `current_block` 缺省为 None；消费方保守处理 |
| E4 | 库存为空（无物品） | `inventory=[]`；`object_in_inventory` 对任意 object 判失败（正确行为） |
| E5 | 地点 id 在 `LocationRegistry` 中不存在 | `location_name` 回退为原始 id；`location_exists` 判失败 |
| E6 | 世界事件数超上限 | 截断为 5 条（按重要性 → due_at 确定性排序） |
| E7 | 工具产出未知 `op` 名 | `_apply_world_op` 抛错 → outbox 重试 → 死信（既有行为，不特殊处理） |
| E8 | 工具产出 `op` 但世界不可用（返回 None） | 抛错 → 重试 / 死信；工具侧已返回 `succeeded` 时不回滚（V9 纪律：投递失败不回滚执行） |
| E9 | 同一 action 重放（outbox 崩溃恢复） | `create_event` 打 `outbox_action_id` 指纹，不产生第二条事件（既有幂等护栏） |
| E10 | 场景画像缺失（V2.3.0 `v23_scene_expansion_enabled` off） | `scene` 缺省为空 dict；投影规则不做场景维度裁剪（保守） |
| E11 | 关系状态读取失败 | `relationship` 缺省为空 dict；关系维度裁剪降级为不裁剪 |
| E12 | 工具实现体在函数内动态 import 世界仓储 | 静态扫描捕获（AST 扫描覆盖函数内 import） |
| E13 | 工具实现体通过 `getattr` 间接调用写函数 | 静态扫描按函数名黑名单检出；无法检出的间接调用由运行期断言兜底（写前校验调用栈模块） |
| E14 | `world.intent.submit` 被真实调用 | 返回 unavailable；调试端点显示 `not_wired`；零 DB 写 |
| E15 | 多用户并发预读 | 无共享可变状态（纯读），并发安全 |
