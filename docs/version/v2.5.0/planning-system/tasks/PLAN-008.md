# PLAN-008 Task Detail — World Simulation Integration

> 上游：[../architecture.md](../architecture.md) §7.4（与 World Simulation 集成）、§6.7（⑨ 世界广播）、§2.3（红线 5）、§7.1（集成总则）、§9.7 Q5 / Q9；[../tasks.md](../tasks.md) PLAN-008
> 状态：设计稿（未实现）
> 范围红线：**世界事实只经预读注入规划；计划永不直接修改世界状态**；`services/planning/` 零 `world_repository` 导入；零 `character_state` / `personality_state` / `relationship_*` 写入；`WorldIntentSubmitter` 本版本仍 `WIRED=False`。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-008 |
| **Task Name** | World Simulation Integration |
| **Priority** | P1 |
| **Dependencies** | PLAN-005, PLAN-006 |
| **Phase** | Phase 3 系统集成 |
| **建议提交** | `feat: V2.5.0 计划与世界的读写契约接线` |

## 1.1 Goal

钉死计划与世界的读写契约：

1. **反向（World → Plan）预读装配**：九类世界事实进 `PlanContext`，全部逐段可降级。
2. **正向（Plan → World）三条合法路径**：只读世界 / 延迟写世界 / 提交世界意图（**本版本仍不接线**）。
3. **Character 域边界铁律**：`character_goals` 仅经 `goal_repository` 改状态；其余 Character 域表一律不可写。
4. **Event System 集成**：计划达成与放弃经既有 `event_bridge.register_goal_event` 广播；计划修订**不广播**；**不新增 `world_events.type`**。
5. **静态扫描护栏**：`services/planning/` 零 `world_repository` 导入。

## 1.2 Scope

**包含**

- 九类世界事实进 `PlanContext` 的装配接线与逐段降级（`world_engine` 只读接口）。
- 计划写世界的**唯一合法通道**验证：`deferred_world_op` → `action_repository.save_record_with_outbox` → `outbox_consumer._apply_world_op` → `world_engine`。
- 合法世界操作白名单的边界用例（白名单外无调用路径）。
- 终态广播接线：`event_bridge.register_goal_event(outcome="completed"/"abandoned")`；**修订不广播**的负例。
- Character 域边界铁律的静态扫描断言。
- `WorldIntentSubmitter` 的未接线断言与记录（Q5）。
- Q9（计划完成对 Character State 的间接影响）的记录。

**不包含（Non-Scope）**

- `world_engine` / `world_repository` / `outbox_consumer` / `event_bridge` 的**任何改动**（V8 / V2.3.0 冻结）。
- 世界表结构（零迁移）。
- `world_events.type` 值域扩展（**永不**）。
- 关系域写入路径的扩张（Q9 需与 V8.5 / V2.2 一并评估，推后续版本）。
- 记忆沉淀（PLAN-009）。
- 反思证据窗（PLAN-010）。
- 自治 `plan_facts`（PLAN-007）。

## 1.3 本任务解决什么问题

关闭架构 §1.3 断层 **B7 的世界侧**并守住 architecture §2.3 红线 5：

| 问题 | 风险 | 本任务的守卫 |
|---|---|---|
| 计划层为了「让步骤生效」直写 `worlds` / `world_events` | 绕过世界唯一写面，破坏 V8 一致性（幂等键、崩溃重放、事件配额） | `G-WORLD` 静态断言：`services/planning/` 零 `world_repository` 导入 |
| 计划层直接改 `character_state` / `relationship_*` 来表达「陪伴感」 | 绕过 V8.5 关系演进与 V2.2 情绪通道，性格/关系数据失真 | 边界表断言：零直写；关系域效果只经工具 `effects(kind=relationship)` |
| 计划终态不广播 | 角色「完成了一件事」在世界侧不可见，既有事件升级链路看不见 | 终态经 `event_bridge.register_goal_event` 广播 |
| 为计划新增世界事件类型 | 需改 `world_events.type` 值域 → 迁移 + 打破既有升级链路匹配 | **不新增**，复用既有 `goal_completed` |

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **World Simulation（V8 / V2.3.0）** | **核心交互面**：`world_engine` 读写函数、`outbox_consumer`、`event_bridge`、`trigger_router`、`world_brief` |
| **Tool System V2.4.0** | 世界效果由工具 `effects(kind=world)` 产生；`WorldIntentSubmitter`（`WIRED=False`）为预留解耦点 |
| **Action Engine（V9 / V2.4.0）** | `integrate_result` 的 world 通道经 outbox 投递（既有） |
| **Memory 2.0 / Reflection** | **不涉及**（属 PLAN-009 / PLAN-010） |
| **Autonomy 2.0** | **不涉及**（属 PLAN-007） |

**关键事实（已核对真实源码）**

- `app/application/world_engine.py` 的只读接口：`build_time_context(user_id, provider=None)`、`get_location_context(user_id)`、`get_objects_by_location(user_id, location_id)`、`list_active_events(user_id)`、`collect_facts(user_id, provider=None)`、`build_context(user_id, session_id=None, trace=None)`、`get_full_state(user_id)`、`find_object_by_name`、`get_world`、`list_active_objects`。
- `world_engine` 的写接口（合法世界操作）：`create_event`、`cancel_events_by_type`、`create_object`、`move_object`、`apply_object_action`、`set_environment`、`set_location`、`advance_time`、`consume_object`、`discard_object`、`complete_events_by_type`（后若干经既有能力调用，不在计划层的白名单内直接出现）。
- `app/application/outbox_consumer.py`：`consume_pending(limit=50, now=None)` / `_apply_outbox_row(row)` / `_apply_world_op(action_id, op)` / `_restore_datetimes(args)`——**`_apply_world_op` 的幂等键 = `action_id`**（即 `ActionRecord.id`）。
- `app/repositories/action_repository.py::save_record_with_outbox(...)`：同事务写 `action_records` + outbox 行。
- `app/services/world/event_bridge.py`：`register_goal_event(user_id, goal_id, description, outcome)` / `register_interest_event(...)` / `on_insight_created(...)` / `register_character_event_listeners()` / `_register_world_op(...)` / `_enabled()`。
- `app/services/world/world_brief.py::build_world_brief(...)`（`_time_line` / `_place_line` / `_situations_line` / `_events_line`），受 `world_brief_char_budget` 约束。
- `app/repositories/world_simulation_repository.py::get_active_situation(user_id, dimension)`。
- `app/character/asuna/scene_profiles.py::scene_profile_for(location_id)`。
- `app/services/tool/world_intent.py::WorldIntentSubmitter`（TOOL-007 冻结形状，`WIRED=False`）。
- 迁移链头 0046。

## 2.2 为什么需要本任务

architecture §7.1 集成总则的第一条是：**计划只编排，不裁决；结果只回填，不直写。**

世界是这条纪律最容易被违反的地方——因为「让计划产生效果」的直觉做法就是直接改世界。但 V8 已经把世界的写入收敛为唯一路径（outbox + 幂等键 + 崩溃重放），绕过它会同时破坏：一致性、幂等、事件配额、既有升级链路。

本任务的价值是把这条纪律变成**可判定的静态与运行时断言**，并把「计划对世界的三种合法交互方式」固化下来。

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 九类世界事实进 `PlanContext` 的装配接线 | 装配表 + 用例 |
| R2 | 世界事实逐段可降级（`world_enabled=False` 时空包 + `degraded`） | 契约 + 用例 |
| R3 | 正向三条合法路径的契约固化与验证 | 路径表 + 用例 |
| R4 | 合法世界操作白名单的边界用例（白名单外无调用路径） | 用例集 |
| R5 | 计划写世界全部经 outbox（幂等与崩溃重放续走） | 断言 |
| R6 | 终态广播接线（达成 / 放弃）+ **修订不广播**负例 | 接线 + 用例 |
| R7 | `G-WORLD` 静态扫描断言 | 静态测试 |
| R8 | Character 域边界铁律断言 | 边界表 + 静态断言 |
| R9 | `WorldIntentSubmitter` 未接线断言（Q5 记录） | 断言 + 记录 |
| R10 | Q9（计划完成对 Character State 的间接影响）记录 | 文档留痕 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | `world_engine` / `world_repository` / `outbox_consumer` / `event_bridge` 的改动 | **永不**（V8 冻结） |
| N2 | `world_events.type` 值域扩展 | **永不** |
| N3 | 世界表结构变更 | 零迁移（全版本） |
| N4 | 关系域写入路径扩张（Q9） | 推后续版本（需与 V8.5 / V2.2 一并评估） |
| N5 | `WorldIntentSubmitter` 的接线（Q5） | 推后续版本（本版本仍 `WIRED=False`） |
| N6 | 工具效果的产生（`effects(kind=world)` 的构造） | V2.4.0 / PLAN-005 执行链 |
| N7 | 记忆沉淀 | PLAN-009 |
| N8 | 反思证据窗 | PLAN-010 |
| N9 | 自治 `plan_facts` | PLAN-007 |

## 3.3 职责边界一句话

> **世界怎么变由世界侧（`world_engine`）决定；计划只把「想让它怎么变」写进 outbox，然后什么都不做。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 本任务的关系 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/context.py`（PLAN-003） | 已有 | 补齐九类世界事实的装配（World 源） | → `world_engine` / `world_brief` / `world_simulation_repository` / `scene_profiles`（**只读**） |
| `app/services/planning/observer.py`（PLAN-005） | 已有 | 终态广播接线（调既有 `event_bridge.register_goal_event`） | → `services/world/event_bridge.py`（既有函数） |
| `app/application/world_engine.py` | V8 / V2.3.0 既有 | **零改动** | — |
| `app/application/outbox_consumer.py` | 既有 | **零改动**；计划产生的 `deferred_world_op` 经它消费 | — |
| `app/repositories/world_repository.py` | 既有 | **计划层禁止导入** | — |

**分层纪律（静态断言强制）**
- `app/services/planning/` 零 `world_repository` 导入（G-WORLD）。
- `app/services/planning/` 零 `world_engine` 写函数调用（只调只读函数）。
- `app/services/planning/` 零 `character_state` / `personality_state` / `relationship_state` / `relationship_events` 写入。

### 4.1.2 Component 划分

```text
反向（World → Plan）：预读装配（app/services/planning/context.py）
├── 时间 / 日时段        ← world_engine.build_time_context
├── 天气 / 环境          ← world_engine.collect_facts
├── 地点 / 可用动作      ← world_engine.get_location_context
├── 库存 / 附近物        ← world_engine.get_objects_by_location
├── 显著事件             ← world_engine.list_active_events + event_impact.evaluate_batch
│                            （EventImpact.goal_opportunity 为规划素材）
├── 用户处境             ← world_simulation_repository.get_active_situation
├── 场景画像             ← scene_profiles.scene_profile_for
├── 世界简报             ← world_brief.build_world_brief（≤ world_brief_char_budget）
└── WorldContext 完整切片 ← world_engine.build_context
     ★ 逐段可降级；world_enabled=False → 全空包 + degraded += ["world_disabled"]
     ★ 只读：不得触发 build_context 内部的 run_turn_update 等写路径

正向（Plan → World）：三条合法路径
├── ① 只读世界       ：world_engine.get_*（无副作用）
├── ② 延迟写世界     ：deferred_world_op → action_repository.save_record_with_outbox
│                       → outbox_consumer._apply_world_op → world_engine.create_event 等
└── ③ 提交世界意图   ：WorldIntentSubmitter（TOOL-007 冻结形状，WIRED=False）★ 本版本不接线

Event System 集成（app/services/planning/observer.py）
├── 计划达成 → event_bridge.register_goal_event(outcome="completed")
├── 计划放弃 → event_bridge.register_goal_event(outcome="abandoned")
└── 计划修订 → 不广播（内部结构变化，非世界事件）
```

### 4.1.3 数据流：九类世界事实的装配

```text
assemble(goal, run, now)
    │
    ├─ world_enabled ?
    │     ├─ False → world = {}, world_brief = None, world_context = None,
    │     │           situations = [], scene = None
    │     │           degraded += ["world_disabled"]
    │     └─ True  →
    │           ① build_time_context(user_id, provider)      → 时段 / 当前块
    │           ② collect_facts(user_id, provider)           → 天气 / 环境 / 时段
    │           ③ get_location_context(user_id)              → 地点 / 可用动作
    │           ④ get_objects_by_location(user_id, loc_id)   → 库存 / 附近物
    │           ⑤ list_active_events(user_id)
    │                + event_impact.evaluate_batch(...)      → 显著事件 + goal_opportunity
    │           ⑥ get_active_situation(user_id, dimension)   → 用户处境
    │           ⑦ scene_profile_for(location_id)             → 场景画像（tone / affordances）
    │           ⑧ build_world_brief(..., budget=world_brief_char_budget) → 简报
    │           ⑨ build_context(user_id, session_id, trace)  → WorldContext 完整切片
    │               ★ 只读：不得触发 run_turn_update 等写路径
    │
    └─ 逐段失败 → 空包 + degraded 登记；不抛错、不阻塞
```

## 4.2 Core Model

本任务**不新增模型**。下表为世界侧的读写契约。

### 4.2.1 反向：九类世界事实 → `PlanContext` 字段

| # | 世界事实 | 读取入口（既有） | 进 `PlanContext` 的字段 | 降级形态 |
|---|---|---|---|---|
| 1 | 时间 / 日时段 | `world_engine.build_time_context` | `world.part_of_day` / `budget` 中的时段约束 | 空包 |
| 2 | 天气 / 环境 | `world_engine.collect_facts` | `world.weather` | 空包 |
| 3 | 地点 / 可用动作 | `world_engine.get_location_context` | `world.location`（并进 `ToolContext.world` 供语义校验） | 空包 |
| 4 | 库存 / 附近物 | `world_engine.get_objects_by_location` | `world_context.inventory` | 空包 |
| 5 | 显著事件 | `world_engine.list_active_events` + `event_impact.evaluate_batch` | `world.active_events` + `EventImpact.goal_opportunity`（规划素材） | 空列表 |
| 6 | 用户处境 | `world_simulation_repository.get_active_situation` | `situations` | 空列表 |
| 7 | 场景画像 | `scene_profiles.scene_profile_for` | `scene`（`tone_bias` / `topic_affordances`） | `None` |
| 8 | 世界简报 | `world_brief.build_world_brief` | `world_brief`（prompt 素材） | `None` |
| 9 | 完整世界切片 | `world_engine.build_context` | `world_context`（含库存 / 附近物） | `None` |

**降级纪律**：任一源失败 → 空包 + `degraded` 登记；`world_enabled=False` → 九项全空 + `degraded` 含 `world_disabled`。

### 4.2.2 正向：三条合法路径（与 V2.4.0 §7.3 同构）

| # | 形态 | 场景 | 路径 | 本版本 |
|---|---|---|---|---|
| ① | **只读世界** | 步骤「查天气」（`world.env.query`） | 直接调 `world_engine.get_*`（只读，无副作用） | ✅ 可用 |
| ② | **延迟写世界** | 步骤「创建提醒」（`builtin.reminder.create`） | 产出 `deferred_world_op={op:"create_event", args:[...]}` → `action_repository.save_record_with_outbox`（幂等键 = `record.id`，同一事务）→ `outbox_consumer._apply_world_op` → `world_engine.create_event` | ✅ 可用 |
| ③ | **提交世界意图（供世界侧裁决）** | 计划想「整理房间」但世界侧需按日程/场景裁决 | `services/tool/world_intent.py::WorldIntentSubmitter`（TOOL-007 冻结形状） | ❌ **`WIRED=False`，仍不接线**（Q5） |

### 4.2.3 合法世界操作白名单（均出自 `world_engine`）

| 操作 | 用途 |
|---|---|
| `create_event` | 创建世界事件（提醒 / 面试 / 考试等） |
| `cancel_events_by_type` | 按类型取消事件 |
| `create_object` | 创建物品 |
| `move_object` | 移动物品 |
| `apply_object_action` | 对物品施加动作（吃 / 用等） |
| `set_environment` | 设置环境（经既有能力，不新增） |
| `set_location` | 设置地点（经既有能力，不新增） |

**边界纪律**：白名单外**无调用路径**；`services/planning/` 不直接调用上述任何一个——它们只由 `outbox_consumer._apply_world_op` 按 `deferred_world_op.op` 分派。

### 4.2.4 Character 域边界铁律（评审红线）

| 域 | Planning 可否写 | 实际写法 | 断言 |
|---|---|---|---|
| `character_goals` | ✅ **仅状态** | `goal_repository.set_status` / `finish_goal`（迁移表守卫） | 静态：零 `UPDATE` 语句 / 零直构 `GoalRow` |
| `character_state` | ❌ | — | 静态：零写入 |
| `personality_state` | ❌ | — | 静态：零写入 |
| `relationship_state` / `relationship_events` | ❌ | 经工具效果 `effects(kind=relationship)` → `relationship_bridge`（既有通道） | 静态：零直写；运行时：关系变化必有对应 `ToolEffect` |
| `worlds` / `world_entities` / `world_events` | ❌ | `deferred_world_op` → outbox → `world_engine` | 静态：零 `world_repository` 导入 |
| `memories` | ❌ | 经 `memory_policy` R1~R8（PLAN-009） | 静态：零写入 |

### 4.2.5 Event System 集成表

| 事件 | 产生方式 | 类型 / 来源 | 本版本 |
|---|---|---|---|
| 计划达成 | `event_bridge.register_goal_event(user_id, goal_id, description, outcome="completed")` | `world_events`（`EventSource.CHARACTER`，既有） | ✅ 接线 |
| 计划放弃 | 同上（`outcome="abandoned"`） | 同上 | ✅ 接线 |
| 计划修订 | **不广播**（内部结构变化，非世界事件） | — | ✅ 负例断言 |
| 计划步骤产生世界副作用 | 由工具效果自动产生（`create_event` / `move_object` 等，经 outbox） | 既有 | ✅ 既有 |
| 计划需要世界裁决 | `WorldIntentSubmitter`（预留） | — | ❌ 未接线 |

> **不新增 `world_events.type`**：终态广播复用既有 `goal_completed` 类型（`v23_event_escalation_types` 默认值已含 `goal_completed`），从而**自动获得既有的重要事件升级链路**（`trigger_router.evaluate_event_escalation`）。

### 4.2.6 出站幂等与崩溃重放（复用 V9 机制）

| 项 | 机制 |
|---|---|
| 幂等键 | `ActionRecord.id`（`outbox_consumer._apply_world_op(action_id, op)` 以其为幂等键） |
| 事务 | `action_repository.save_record_with_outbox` 同事务写 `action_records` + outbox 行 |
| 消费 | `outbox_consumer.consume_pending(limit, now)` |
| 崩溃重放 | 重启后续走（幂等键保证不重复应用） |

## 4.3 State Machine

本任务**不新增状态机**。下为世界写入的既有生命周期在计划链路中的体现。

### 4.3.1 `deferred_world_op` 生命周期（既有）

```text
工具执行产出 deferred_world_op
        │
        ▼
action_repository.save_record_with_outbox（同事务）
        ├─ action_records 行（含 deferred_world_op）
        └─ outbox 行（幂等键 = ActionRecord.id）
        │
        ▼
outbox_consumer.consume_pending → _apply_outbox_row → _apply_world_op(action_id, op)
        │
        ├─ 已应用过（幂等键命中）→ 跳过（不重复副作用）
        └─ 未应用 → world_engine.<op>(*args) → 标记已应用
```

**计划层的唯一动作**：产出 `deferred_world_op`（由工具的 `effects(kind=world)` 承载）。**计划层不参与上述任何一步的调用。**

### 4.3.2 计划终态 → 世界事件的状态映射

| 计划终态 | 目标终态 | 广播 | 事件类型 |
|---|---|---|---|
| 全部步骤 `done` | `completed` | ✅ `register_goal_event(outcome="completed")` | `goal_completed`（既有） |
| 达修订预算 / `on_failure=abort` | `failed` | ❌ **不广播**（失败不是世界事实） | — |
| `check_abandonment` 双信号 → 放弃 | `abandoned` | ✅ `register_goal_event(outcome="abandoned")` | `goal_completed`（既有，语义由 `outcome` 承载） |
| 计划修订（产生新版） | 不变 | ❌ **不广播** | — |

---

# 5. System Interaction

## 5.1 与 Autonomy

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `world_facts` 进 `PolicySnapshot` | 既有（V8 / V2.3.0） | **零改动** |
| `plan_facts` | PLAN-007 | **不涉及** |
| 世界事实驱动的主动性 | 既有（`_apply_world_adjustments` / `WORLD_PROACTIVE_EVENT_TYPES`） | **零改动** |

**为什么不涉及**：世界事实进自治策略是既有能力；本任务只做「世界事实进**规划**」这一条（新），以及「计划终态**广播回世界**」这一条（新）。

## 5.2 与 Tool System

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 世界效果的产生 | 工具 `effects(kind=world)`（V2.4.0 既有） | **消费**（不新造） |
| `WorldIntentSubmitter` | TOOL-007 冻结形状，`WIRED=False` | **断言仍为 `WIRED=False`**（Q5 记录） |
| 工具面裁剪（`world_unavailable` / `world_disabled`） | 既有 | **零改动**（PLAN-006 已断言） |

**为什么不动工具侧**：工具是唯一执行面（红线：不绕过工具治理）。计划表达世界意图的唯一方式就是**让工具产出世界效果**，而不是自己动手。

## 5.3 与 World Simulation（本任务核心）

| 关注点 | 既有（V8 / V2.3.0，零改动） | 本任务 |
|---|---|---|
| 唯一写面 | `world_engine` 的四张世界表写函数 | **只读消费 + 经 outbox 间接写** |
| 幂等键机制 | `ActionRecord.id`（`_apply_world_op` 入参） | **未改**（断言） |
| 崩溃重放 | `consume_pending` 续走 | **未改**（断言） |
| 事件唯一事实源 | `world_events` + `event_bridge` | **未改**；新增接线只调既有 `register_goal_event` |
| `world_events.type` 值域 | 既有（含 `goal_completed`） | **未扩**（断言） |
| 世界不写 Character 域 | 既有铁律 | **未改** |

## 5.4 与 Memory

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 世界事件 → 记忆 | 既有 `ingest_from_world_event`（V2.0） | **零改动** |
| 计划终态记忆 | PLAN-009 | **不涉及** |

**为什么不涉及**：`deferred_world_op` 经 outbox 创建的世界事件由既有 `ingest_from_world_event` 通道处理（内存侧既有能力）；计划终态的记忆候选是另一条独立通道（PLAN-009）。

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `world/event_bridge.py::on_insight_created` | 既有三个反思消费者之一 | **零改动**（监听器注册行为不变） |
| 计划证据窗 | PLAN-010 | **不涉及** |

**边界**：本任务新增的 `register_goal_event` 调用**不改变** `on_insight_created` 的行为；PLAN-010 新增第四个消费者时须回归验证既有三个（PLAN-010 §10.2 已列）。

## 5.6 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配的其他五源 | 不涉及 | PLAN-003（本任务补齐 World 源的九项） |
| 计划生成 / 拆解 | 不涉及 | PLAN-003 / PLAN-004 |
| 工具治理 | 不涉及 | PLAN-006 |
| 记忆沉淀 | 不涉及 | PLAN-009 |
| 反思证据窗 | 不涉及 | PLAN-010 |
| 自治 `plan_facts` | 不涉及 | PLAN-007 |
| 调试端点 | 不涉及 | PLAN-011 |

---

# 6. API / Interface Design

本任务不新增公开接口；下表为被本任务接线 / 加固的契约。

## 6.1 世界只读接口（反向装配，`PlanContext` 的 World 源）

```text
interface WorldReadForPlanning:                 # 全部为既有函数，只读
    build_time_context(user_id, provider) -> TimeContext
    collect_facts(user_id, provider) -> dict
    get_location_context(user_id) -> LocationContext
    get_objects_by_location(user_id, location_id) -> list[WorldObject]
    list_active_events(user_id) -> list[WorldEvent]
    build_world_brief(..., budget) -> WorldBrief
    build_context(user_id, session_id, trace) -> WorldContext
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 只调只读函数；**不得**触发 `build_context` 内部的 `run_turn_update` 等写路径 | 打桩断言（零写） |
| D2 | 九类事实各有「可用 / 不可用」两态 | 逐项用例 |
| D3 | 逐段降级：空包 + `degraded` 登记，不抛错、不阻塞 | 用例 |
| D4 | `world_enabled=False` → 九项全空 + `degraded` 含 `world_disabled` | 用例 |
| D5 | `world_brief` 长度 ≤ `world_brief_char_budget` | 预算断言 |

## 6.2 世界写入接口（正向路径，**计划层不直调**）

```text
# 计划层产出的唯一"写世界"表达
deferred_world_op = {"op": <白名单 op>, "args": [...]}
    # 由工具的 effects(kind=world) 承载

# 消费链（既有，计划层不参与调用）
action_repository.save_record_with_outbox(record)      # 同事务写 action_records + outbox
outbox_consumer.consume_pending(limit, now)            # 批次消费
outbox_consumer._apply_outbox_row(row)                 # 单行
outbox_consumer._apply_world_op(action_id, op)         # 幂等键 = action_id
world_engine.<op>(*args)                               # 白名单七 op
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D6 | `services/planning/` **零** `world_repository` 导入 | 静态断言（G-WORLD） |
| D7 | `services/planning/` **零** `world_engine` 写函数调用 | 静态断言 |
| D8 | 计划写世界**全部**经 outbox | 运行时断言：世界表变更前必有对应 outbox 行 |
| D9 | 白名单外 op 无调用路径 | 负例用例 |
| D10 | 消费幂等与崩溃重放续走行为与 V9 一致 | 幂等键机制未改断言 |

## 6.3 事件广播接口

```text
# 终态广播（唯一新增接线）
event_bridge.register_goal_event(user_id: str, goal_id: str, description: str, outcome: str) -> bool
    # outcome ∈ {"completed", "abandoned"}
    # 内部经 _register_world_op → outbox → world_events（既有链路）
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D11 | 只调既有 `register_goal_event`，不新增事件写入路径 | 静态断言 |
| D12 | `world_events.type` 值域未扩（复用 `goal_completed`） | 值集快照对照 |
| D13 | 计划修订**不广播** | 负例断言（修订后 `world_events` 无新增行） |
| D14 | 终态广播可被既有升级链路消费 | 用例：`trigger_router.evaluate_event_escalation` 可识别 |
| D15 | 广播失败不回滚计划终态 | 用例（与 V9「投递失败不回滚执行」同款纪律） |

## 6.4 Character 域边界断言

| # | 断言 | 判定方式 |
|---|---|---|
| E1 | `services/planning/` 零 `character_state` 写入 | 静态 |
| E2 | `services/planning/` 零 `personality_state` 写入 | 静态 |
| E3 | `services/planning/` 零 `relationship_state` / `relationship_events` 写入 | 静态 |
| E4 | 关系域效果只经工具 `effects(kind=relationship)` → `relationship_bridge` | 运行时：关系变化必有对应 `ToolEffect` |
| E5 | `character_goals` 只经 `goal_repository` 状态写面 | 静态（PLAN-001 已列，本任务复核） |

## 6.5 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| 世界只读接口异常 | `world_engine` 只读函数 | 捕获 → 空包 + `degraded` 登记；不阻塞规划 |
| outbox 投递失败 | `save_record_with_outbox` | 不回滚执行（V9 既有纪律）；下一轮 `consume_pending` 续走 |
| `_apply_world_op` 内异常 | 世界写函数 | outbox 行保留（幂等键未标记）→ 重放续走；只 log |
| 广播失败（`register_goal_event` 返回 `False` / 抛错） | `event_bridge` | 只 log；**不回滚计划终态**（D15） |
| `WorldIntentSubmitter` 调用尝试 | 计划层 | 不应发生（`WIRED=False`）；断言零调用 |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 世界写入复用既有四张世界表；outbox 复用既有 outbox 表；事件复用 `world_events` |
| 新列 | 无 | `deferred_world_op` 存 `action_records`（既有列，V9 既有）；`plan_facts` 与世界无关 |
| 新索引 | 无 | 本任务不引入新查询维度 |
| 改 CHECK | 无 | `world_events.type` 值域未扩；`EventSource` 值集未扩（复用 `CHARACTER`） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面（全部为既有）**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| 世界副作用 | `worlds` / `world_entities` / `world_events` | `world_engine`（经 `outbox_consumer._apply_world_op`） | ❌ |
| outbox 行 | outbox 表 | `action_repository.save_record_with_outbox` | ❌ |
| 世界事件（终态广播） | `world_events` | `event_bridge.register_goal_event` → outbox → `world_engine.create_event` | ❌ |
| 计划状态 / 步骤 | `goal_plans` | `goal_repository.update_plan_progress` | ❌ |
| 目标终态 | `character_goals` | `goal_repository.set_status` / `finish_goal` | ❌ |

> **计划层对世界的直接写入量 = 0**。这是本任务的核心断言（G-WORLD），也是 architecture §2.3 红线 5 的可判定形态。

---

# 8. Implementation Plan

## Step 1 — 九类世界事实装配

1. 在 `context.py` 的 World 源补齐九项装配（§4.2.1 表），全部经既有只读入口。
2. `event_impact.evaluate_batch` 产出的 `goal_opportunity` 并入 `world.active_events`。
3. `world_brief` 受 `world_brief_char_budget` 预算约束。
4. **只读断言**：`build_context` 调用不得触发 `run_turn_update` 等写路径（打桩断言零写）。
5. 单测：九项各有「可用 / 不可用」两态；`world_enabled=False` 时全空 + `degraded` 含 `world_disabled`。

## Step 2 — 正向路径契约固化

1. 确认计划层产出世界表达的唯一形态是 `deferred_world_op`（由工具 `effects(kind=world)` 承载）。
2. 确认消费链（`save_record_with_outbox` → `consume_pending` → `_apply_world_op` → `world_engine.<op>`）**零改动**。
3. 白名单七 op 的边界用例：白名单外 op 被拒（负例）。
4. 幂等与崩溃重放：重复 `consume_pending` 不产生第二条世界副作用；中断后重启续走。
5. 单测：D8 / D9 / D10 三条可判定。

## Step 3 — `WorldIntentSubmitter` 未接线断言（Q5）

1. 断言 `services/tool/world_intent.py::WorldIntentSubmitter` 的 `WIRED` 仍为 `False`。
2. 断言 `services/planning/` 零 `WorldIntentSubmitter` 调用。
3. 冻结形状的 schema 测试通过（TOOL-007 既有契约未被改动）。
4. 记录 Q5 评估结论：计划对世界的改动可由 `deferred_world_op` 覆盖，故仍不接线；接线评估推后续版本。

## Step 4 — 终态广播接线

1. 在 `PlanObserver.settle` 的目标终态为 `completed` 时调 `event_bridge.register_goal_event(outcome="completed")`。
2. 目标终态为 `abandoned` 时调同函数（`outcome="abandoned"`）。
3. 目标终态为 `failed` 时**不广播**。
4. 断言 `world_events.type` 值域未扩（复用 `goal_completed`）。
5. 断言广播可被 `trigger_router.evaluate_event_escalation` 消费。
6. 单测：达成 / 放弃各一例；失败不广播；修订不广播（负例）；广播失败不回滚终态。

## Step 5 — 静态扫描护栏（G-WORLD）

1. 扫描 `app/services/planning/`：零 `world_repository` 导入。
2. 扫描 `app/services/planning/`：零 `world_engine` 写函数调用（白名单只读函数之外一律禁止）。
3. 扫描 `app/services/planning/`：零 `character_state` / `personality_state` / `relationship_state` / `relationship_events` 写入。
4. 扫描 `app/services/planning/`：零 `WorldIntentSubmitter` 调用。
5. 单测：四条扫描断言可判定。

## Step 6 — 关系域通道验证（Q9 记录）

1. 断言关系域效果只经工具 `effects(kind=relationship)` → `relationship_bridge`（既有通道）；运行时断言：关系变化必有对应 `ToolEffect`。
2. 记录 Q9：计划完成 → `goal_completed` 事件 → `event_bridge` → 世界事件。**是否应同时产生关系域信号**（如「陪用户完成了一件事」）涉及 `relationship_*` 写入面扩张，需与 V8.5 / V2.2 一并评估；本版本**不做**，仅在本文档与验收记录中留痕。

## Step 7 — 回归

1. V2.3.0 / V8 世界侧既有测试零失败（世界唯一写面与事件唯一事实源未被触碰）。
2. 计划写世界的 outbox 幂等 + 崩溃重放行为在世界侧既有测试中零失败。
3. Flag off 时世界侧行为与 V2.4.0 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 九类世界事实装配 | 九项各有「可用 / 不可用」两态 |
| U2 | `world_enabled=False` | 九项全空；`degraded` 含 `world_disabled` |
| U3 | `goal_opportunity` 进规划素材 | `EventImpact.goal_opportunity` 并入 `world.active_events` |
| U4 | `world_brief` 预算 | 长度 ≤ `world_brief_char_budget` |
| U5 | 逐段降级可读 | `degraded` 元素为稳定字符串 |
| U6 | 白名单七 op | 白名单内可应用；白名单外被拒（负例） |
| U7 | 出站幂等 | 重复 `consume_pending` 不产生第二条世界副作用 |
| U8 | `WorldIntentSubmitter.WIRED` | 仍为 `False`（未接线断言） |
| U9 | 广播正例 | 达成 / 放弃各产生一条 `world_events`（`source=character`） |
| U10 | 广播负例 | 计划 `failed` 不广播；计划修订不广播 |
| U11 | `world_events.type` 未扩 | 值集快照对照（复用 `goal_completed`） |
| U12 | 广播失败不回滚 | `register_goal_event` 抛错 → 目标仍为终态 |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **G-WORLD 静态断言** | `app/services/planning/` 零 `world_repository` 导入；零 `character_state` / `personality_state` / `relationship_*` 写入 |
| I2 | 零 `world_engine` 写函数调用 | 静态断言（只读函数白名单之外一律禁止） |
| I3 | 装配零写库 | 打桩断言：`build_context` 未触发 `run_turn_update` 等写路径 |
| I4 | 计划写世界全部经 outbox | 运行时断言：世界表变更前必有对应 outbox 行 |
| I5 | 崩溃重放续走 | 中断后重启 `consume_pending` 续走；幂等键机制未改 |
| I6 | 终态广播可被升级链路消费 | `trigger_router.evaluate_event_escalation` 识别 `goal_completed` |
| I7 | 关系域只经工具效果 | 运行时断言：关系变化必有对应 `ToolEffect(kind=relationship)` |
| I8 | `WorldIntentSubmitter` 冻结形状 | TOOL-007 既有 schema 测试通过 |
| I9 | V2.3.0 / V8 世界侧既有测试零失败 | 世界唯一写面与事件唯一事实源未被触碰 |
| I10 | 零迁移断言 | 迁移链头 `0046`；`world_events.type` 值域未扩 |
| I11 | **Flag off 逐字节一致** | 世界侧行为与 V2.4.0 一致 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」世界读** | 装配 `PlanContext` 的 World 源 | 时间 / 天气 / 地点 / 库存 / 显著事件 / 处境 / 场景 / 简报 / `WorldContext` 九项可追溯 |
| S2 | 计划「查天气」步骤（只读世界） | `world.env.query` 执行 | 无 `deferred_world_op`；世界表零变更；`effects` 为空 |
| S3 | 计划「创建提醒」步骤（延迟写世界） | `builtin.reminder.create` 执行 | 产出 `deferred_world_op={op:"create_event"}`；经 outbox → `world_engine.create_event`；`world_events` 新增一行 |
| S4 | **重规划不重复副作用（G-RETRY 世界侧）** | 含提醒步骤的计划 → 因失败重规划 | `deferred_world_op` 计数不增加；`world_events` 无第二条提醒 |
| S5 | 计划全步达成 | 目标 `completed` | 广播一条 `goal_completed`（`source=character`）；可被升级链路消费 |
| S6 | 计划被放弃 | 目标 `abandoned` | 广播一条（`outcome="abandoned"`） |
| S7 | 计划失败 | 目标 `failed` | **不广播**（负例） |
| S8 | 计划修订 | `version+1` | **不产生任何 `world_events`**（负例） |
| S9 | 世界关闭 | `world_enabled=False` → 规划 | World 源九项全空 + `degraded` 含 `world_disabled`；规划仍可产出计划（若工具面满足） |
| S10 | 世界侧崩溃重放 | outbox 消费中断 → 重启 | 续走；无重复世界副作用 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- **G-WORLD 静态扫描断言**：`app/services/planning/` 零 `world_repository` 导入；零 `character_state` / `personality_state` / `relationship_*` 写入。
- 计划写世界**全部**经 outbox；消费幂等与崩溃重放续走行为与 V9 一致；`outbox_consumer._apply_world_op` 幂等键机制未改。
- 终态广播落 `world_events`（`source=character`）且可被既有升级链路（`trigger_router.evaluate_event_escalation`）消费；`world_events.type` 值域未扩。
- 九类世界事实可进 `PlanContext` 且逐段可降级；`world_enabled=False` 时为空包且 `degraded` 含 `world_disabled`。
- 世界操作白名单外无调用路径（负例：非白名单 op 被拒）。
- `WorldIntentSubmitter` 仍为 `WIRED=False`（未接线断言），冻结形状的 schema 测试通过。
- 关系域效果只经工具 `effects(kind=relationship)` → `relationship_bridge` 通道（零直写断言）。
- 计划修订不产生任何 `world_events`（负例断言）；计划失败不广播。
- Flag off 时世界侧行为与 V2.4.0 逐字节一致。

## 10.2 Integration Acceptance

- V2.3.0 / V8 世界侧既有测试零失败（世界唯一写面与事件唯一事实源未被触碰）。
- 世界事实装配全程只读：`build_context` 不触发 `run_turn_update` 等写路径（打桩断言）。
- 计划层对世界的**直接写入量为 0**（静态 + 运行时断言）。
- `outbox_consumer` / `action_repository.save_record_with_outbox` / `event_bridge` 零改动（diff 为空）。
- 终态广播失败不回滚计划终态（与 V9「投递失败不回滚执行」同款纪律）。
- `event_bridge.on_insight_created`（既有反思消费者）行为不变。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`；`world_events.type` 与 `EventSource` 值集未扩。
- **零新建事件类型 / 零新建世界写面**：终态广播复用既有 `goal_completed` 与 `register_goal_event`；计划层零世界写函数调用。
- **Q5 记录留痕**：`WorldIntentSubmitter` 本版本仍 `WIRED=False`；不接线理由（计划对世界的改动可由 `deferred_world_op` 覆盖）与接线评估时点（推后续版本）写入本文档与验收记录。
- **Q9 记录留痕**：计划完成对 Character State 的间接影响（是否追加关系域信号）在本任务内记录，明确需与 V8.5 / V2.2 一并评估，本版本不做。
- **红线 5 可举证**：`services/planning/` 零 `world_repository` 导入这一条既在 architecture §2.3 有声明，又在本任务有静态断言。
- **文档一致**：本文件与 architecture §7.4 / §6.7 / §2.3 / §7.1 / §9.7 Q5 / Q9 及 tasks.md PLAN-008 Acceptance Criteria 逐条对应，无自相矛盾。
