# ACTION-004 Task Detail — World Engine Mutation

> 上游：[../tasks.md](../tasks.md) ACTION-004 ｜ 架构：[../architecture.md](../architecture.md) §5/§7/§9 ｜ 依赖：ACTION-001, ACTION-003
> Priority：**P0** ｜ 层级：Core（写入链唯一出口）

---

## Background

前三道闸只产出"候选"与"裁决"。本 Task 负责**唯一一次真正改变世界**的落笔，且必须落到**既有 World Engine** 上——这是本模块最重要的复用约束，也是"不创建第二套 World 系统"（[../architecture.md](../architecture.md) §4.4）的执行点。

值得强调的是：任务书要求的 `CONSUME` **不需要新造能力**。`world_engine.consume_object(user_id, object_ref, quantity)` 早已存在，返回结构化 `ConsumeResult{ok, error, object, previous_quantity}`，并已实现 `consumable` 校验、数量充足性校验与"失败不部分扣除"。本 Task 的工作是**把 `WorldAction` 接到这些既有函数上**，而不是发明新账本。

## Objective

对每条已 `validated` 的 `WorldAction`：

- 经**既有引擎函数**写入世界：`CREATE → create_object`、`MOVE → move_object`、`CONSUME → consume_object`；
- **按文本顺序**执行，使同轮后续动作可引用前序动作产物；
- 执行后**回读校验**（确认落库），并把 before/after 快照写入结果；
- 失败即 `failed`，**不部分扣除、不补偿写入**；
- 成功后落一条 `WorldEvent(type=character_action)` 作为可查询历史（供 ACTION-005 与 Memory 2.0 消费）。

## Existing Architecture

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `world_engine.create_object(user_id, name, category, location_id, quantity, aliases, unit, consumable, **properties)` | 受 `world_active_entities_limit` 限流；`consumable` 缺省按类目（food/drink → True）；`state` 由 `object_initial_state` 取 | **不修改**；直接调用 |
| `world_engine.move_object(user_id, object_id, location_id)` | 要求 `location_id ∈ HOME_LOCATIONS`、对象 `ACTIVE`；更新 `last_action_at` 并落库 | **不修改**；直接调用 |
| `world_engine.consume_object(user_id, object_ref, quantity)` | **已是统一 Consume API**；按 `consumable` + 数量扣减；`remaining==0` 时 state 置 `empty`；返回 `ConsumeResult` | **不修改**；直接调用 |
| `world_engine.apply_object_action(user_id, object_id, action, portions)` | 走 V8 物品状态机；`eat` 按 `default_portions` 折算，**非精确数量** | **不使用**（见下"为何不用 eat"） |
| `repositories/world_repository.save_event` / `models/world.WorldEvent` | 事件落库；`type` 为自由字符串；`source` 为 `EventSource` 枚举 | 复用 `save_event`；`type="character_action"`；`source` 见下"事件来源" |
| `world_repository.prune_events_before` | 按 `world_event_retention_days` 清理 completed/cancelled/expired | 复用（动作事件自动随保留策略清理） |
| `world_engine.create_event(...)` | 创建即 `SCHEDULED`，占用 `world_active_events_limit` | **不使用**（见下"为何不用 create_event"） |
| `settings.world_active_entities_limit` / `world_event_retention_days` | 既有配置 | 复用 |
| `application/post_process.py` per-user 写锁 | `run_post_process` 持锁 | 本 Task 天然在锁内 |

### 为何 CONSUME 不用 `apply_object_action(..., "eat")`

`apply_object_action` 的 `eat` 迁移按 `default_portions` 折算（food 类 `default_portions=5`，即 `1/5` 个），且要求状态机 from-state 匹配（food 的 `eat` 只在 `cut`/`eaten` 之后）。这与"我用了两个鸡蛋"的**精确数量语义**不符，且会因状态机前置条件失败而静默不生效。

**决策**：CONSUME 一律走 `consume_object`（精确数量、独立校验、结构化结果）。`apply_object_action` 保持只服务于"状态迁移"类动作（V8/V9 既有用途）。

### 为何事件不用 `create_event(...)`

`create_event` 强制 `status=SCHEDULED` 并计入活跃事件配额（`world_active_events_limit` 默认 20）。角色动作事件是**已发生的历史**，应为 `COMPLETED`，且不应挤占"待办事件"配额。

**决策**：在 `world_engine` 内新增一个薄函数 `record_character_action_event(...)`，内部复用 `WorldEvent` 模型与 `world_repository.save_event`，直接以 `status=COMPLETED`、`completed_at=now` 落库。**不新增表、不新增列、不改事件状态机**。

### 事件来源（`EventSource`）

`models/world.py` 的 `EventSource` 现为 `USER_MENTION` / `MANUAL` / `AUTONOMY`，**没有"角色"取值**。

| 方案 | 说明 | 建议 |
|---|---|---|
| A. 复用 `AUTONOMY` | 语义上角色自主动作接近"自主"，零模型改动 | 可用 |
| B. 新增 `CHARACTER` 值 | 语义精确（区别"用户提到"与"角色做出"）；枚举以文本存储，旧行不受影响，属**加性变更** | **建议（需评审确认）** |

> 本 Task 默认按 **B** 设计，并在实现评审时确认；若评审保守，回退 A，功能等价、仅可读性下降。

## Data Model

### MutationOutcome（每条动作的执行结果）

| 字段 | 说明 |
|---|---|
| `action_id` | 对应 `WorldAction.action_id` |
| `status` | `applied` 或 `failed` |
| `engine_fn` | 实际调用的引擎函数名（`create_object`/`move_object`/`consume_object`） |
| `engine_error` | 引擎返回的错误码（如 `ConsumeError.INSUFFICIENT_QUANTITY`）或 `None` |
| `object_id` / `name` | 变更后的实体标识 |
| `before` | `{quantity, state, location_id}` 或 `null`（CREATE 无 before） |
| `after` | `{quantity, state, location_id}` |
| `world_event_id` | 落库的事件 id（供 ACTION-005 引用） |

### WorldEvent（`type = character_action`）payload 契约

| 键 | 说明 |
|---|---|
| `action_type` | `CREATE` / `MOVE` / `CONSUME` |
| `actor` | 恒为 `character` |
| `target_name` / `object_id` | 对象标识 |
| `quantity` | 数量（MOVE 为 null） |
| `before` / `after` | 数量/状态/位置快照 |
| `location_from` / `location_to` | MOVE 专用 |
| `dedupe_key` | 幂等键（ACTION-005 与幂等窗口使用） |
| `session_id` / `turn_id` | 归因 |

- `title`：人类可读一句话（如「消耗鸡蛋 ×2」「做出面」「牛奶移到厨房」），供上下文渲染。
- `importance`：按动作映射（如 CREATE=`normal`、CONSUME=`low`、MOVE=`low`），避免污染显著性事件排序。
- `status`：`completed`；`completed_at` = 执行时刻；`due_at` = null。

## Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 执行入口 | `list[WorldAction(validated)]`、`user_id`、`turn_ref` | `list[MutationOutcome]` | 按输入顺序逐条执行 |
| 动作 → 引擎映射 | `WorldAction` | 引擎调用 | 见映射表 |
| 事件落库 | `MutationOutcome` + `WorldAction` | `WorldEvent.id` | 复用 `save_event`，`status=completed` |
| 回读校验 | `MutationOutcome` | bool | 读一次世界确认落库结果与 `after` 一致 |

### 动作 → 引擎映射

| action_type | 引擎调用（既有） | 参数来源 | 结果判定 |
|---|---|---|---|
| `CREATE` | `create_object(user_id, name, category, location_id, quantity, unit, consumable)` | `target.name`；`infer_object_category(name)`；`target.location_id` 或 `world.current_location`；`quantity` 缺省 1 | 返回非 `None` → applied；`None` → failed（容量/世界不可用） |
| `MOVE` | `move_object(user_id, object_id, location_id)` | `target.object_id`（ACTION-003 回填）；`target.location_id` | 返回非 `None` → applied |
| `CONSUME` | `consume_object(user_id, object_ref, quantity)` | `target.name` 或 `object_id`；`quantity` | `ConsumeResult.ok=True` → applied；否则 failed（带 `error`） |

## Processing Flow

```text
validated 动作（文本顺序）
        │
   逐条：
        ├─(1) 读取 before 快照（只读：get_object / find_object_by_name）
        ├─(2) 调用对应引擎函数
        ├─(3) 判定结果
        │        applied ← 非 None / ok=True
        │        failed  ← None / ok=False（携带 engine_error）
        ├─(4) 读取 after 快照（回读校验，确认落库）
        ├─(5) 产出 MutationOutcome
        └─(6) applied → record_character_action_event(...) 落 WorldEvent(completed)
               并登记 world_event_id；failed → 仅 trace
        │
   返回 outcomes（成功动作按原顺序）
        │
   ACTION-005 接管：合并 notes + 供下一轮 Context
```

**顺序语义**：一条回复含 `CREATE 面` + `CONSUME 鸡蛋 2` 时，按文本顺序先 CREATE 再 CONSUME（互不相干）；若为 `CREATE 煎蛋卷` 后 `CONSUME 煎蛋卷 1`，则必须 CREATE 在前，否则 CONSUME 会因对象不存在而失败——故**必须保序**（不并行、不重排）。

## State Transition

- `WorldAction`：`validated → applied`（`engine_ok`）／`validated → failed`（`engine_fail`），终态（[ACTION-001](ACTION-001.md)）。
- 被复用的**世界状态迁移**（既有，不新增）：
  - CREATE：新实体 `status=active`，`state=object_initial_state(类目)`，`quantity=给定值`。
  - MOVE：`location_id` 迁移；`last_action_at` 更新。
  - CONSUME：`quantity` 扣减；扣至 0 时 `state="empty"`（由 `consume_object` 既有行为决定，不新增语义）。
- **不引入**新的物品状态机；烹饪类状态留给未来 Cooking Phase。

## Error Handling

| 情形 | 处理 | 世界影响 |
|---|---|---|
| 引擎返回 `None`（CREATE 超容量 / MOVE 地点不符 / 对象不可用） | `failed`，`engine_error=ENGINE_FAILED` | 无 |
| `ConsumeResult.ok=False` | `failed`，携带 `ConsumeError` 原码 | 无（引擎保证不部分扣除） |
| 引擎抛异常 | 捕获 → `failed`，log + trace | 无（单次调用内失败） |
| 回读校验不一致 | 以**世界实际读回值**为准记录 `after`，并 trace 告警 | 以世界为准（世界是 SoT） |
| 事件落库失败 | log + trace；**不回滚**已生效的世界变更 | 世界已正确，仅历史缺失 |
| 世界不可用 | 全部 `failed`（理论上 ACTION-003 已拦） | 无 |

**硬约束**：失败动作**不得**执行任何补偿写（不"加回"、不"改回"）。世界是"发生过即成立"。

## Idempotency

- **幂等键随事件落库**：`WorldEvent.payload.dedupe_key` = `WorldAction.dedupe_key`，使 ACTION-003 的有界窗口去重可跨轮生效。
- **引擎函数本身非幂等**（`consume_object` 调两次扣两次），因此幂等**不能**由引擎承担，必须由 ACTION-003 在写入前完成。
- **重放语义**：同轮重放（同 session/turn/ordinal → 同 `dedupe_key`）→ ACTION-003 判 `DUPLICATE` → 不触达本 Task。
- **保证范围（诚实声明）**：本阶段保证"同轮 + 有界近期窗口"幂等；**跨进程崩溃后的强幂等不保证**。强幂等依赖 P5/LIFE-004 已铺设的 `background_jobs`（迁移 0029）与 `outbox_events`（迁移 0030）——本 Task 通过 `dedupe_key` + `source` 字段为该演进预留接入点（届时可将世界写入改为经 outbox 投递，幂等键 = `action_id`）。
- **事件的幂等**：`record_character_action_event` 以 `dedupe_key` 作为写入前的存在性检查（查近期窗口），避免重复事件累积（ACTION-005 验收要求）。

## Transaction Boundary

| 层级 | 边界 |
|---|---|
| **单动作** | **原子**。每个引擎函数内部各开 `SessionLocal()` 并 `commit()`，单实体单行的写入天然原子。 |
| **整轮** | **非原子**。第 k 条失败不回滚第 1..k−1 条。这是**有意设计**：世界状态是历史事实，回滚会制造新的不一致（"做过的事被撤销"需另立语义，本阶段不做）。 |
| **事件写入** | 与实体写入**不在同一事务**（分属不同表、不同 session）。故存在"实体已变、事件未落"的极小窗口；该窗口由 `failed`/trace 兜底，并由回读校验暴露。 |
| **并发** | 由 `post_process` 的 per-user 写锁保证同用户轮内串行；本 Task **不得**自行开任务绕开锁。 |

**补偿策略**：无自动补偿。异常由 **trace + 幂等** 双保险：trace 保证可归因，幂等保证重放安全。

## Observability

- 逐条 trace：`{action_type, engine_fn, status, engine_error, object_id, before, after, world_event_id}`（经 `bound_extra` 有界）。
- 汇总：`applied / failed` 计数 + 失败原因直方图（与 ACTION-003 的 rejected 分开统计，语义不同：rejected=校验拒绝，failed=引擎失败）。
- 必须能回答：「这条动作调了哪个引擎函数？改动前后是什么？落了哪条事件？」
- 落库的 `WorldEvent` 本身即可通过既有 debug API / `list_events` 反查。

## Testing

| 类型 | 用例 |
|---|---|
| Unit（映射） | 三类动作各断言调用到正确引擎函数，参数逐字段核对 |
| Unit（判定） | 引擎返回 `None` → failed；`ConsumeResult.ok=False` → failed 且带原错误码 |
| Integration | 库存 6 + `CONSUME 2` → 落库后 quantity=4，`ConsumeResult.ok=True` |
| Integration | `CREATE 面` → `world_entities` 出现活跃实体，且 `context_selector` 的 inventory 立即可见 |
| Integration | `MOVE 牛奶 → home.kitchen` → `location_id` 变更且 `before/after` 正确 |
| 顺序 | `CREATE 煎蛋卷` + `CONSUME 煎蛋卷 1` 保序执行，后者成功 |
| 非原子 | 3 条中第 2 条引擎失败 → 第 1、3 条仍生效；第 2 条世界零变更 |
| Idempotency | 同 `dedupe_key` 重放 → 不产生第二条事件、不二次扣减 |
| FailureInjection | 引擎抛异常 / 事件落库失败 → 世界状态正确、trace 有记录、无补偿写 |
| 回归 | 总闸关闭时，本 Task 零调用；世界与 prompt 字节级不变 |

## Acceptance Criteria

1. `CONSUME 鸡蛋 2` 于库存 6 → 执行后库存 4，`ConsumeResult.ok=True`，并落一条 `character_action` 事件。
2. `CREATE 面` → `world_entities` 出现该活跃实体，可被同轮后续动作与下一轮 Context 引用。
3. `MOVE 牛奶 → home.kitchen` → `location_id` 变更且事件 payload 含 `location_from`/`location_to`。
4. 引擎失败时该动作判 `failed`，**库存与状态零变化**（无部分扣除）。
5. 一条回复含 CREATE + CONSUME 时按文本顺序执行，结果可追溯。
6. 世界中不存在"由回复文本直接产生"的实体——全部可归因到具体引擎调用与事件。
7. 总闸关闭时，本 Task 零执行、零写入。

## Implementation Constraints

- **唯一出口**：只能调用 `world_engine` 的公开写函数；**禁止**直接 `world_repository.save_object` 修改实体状态。
- 不修改 `create_object` / `move_object` / `consume_object` / `apply_object_action` 的既有语义与签名（version-boundary Preserve）。
- 不新增表、不新增迁移；事件复用 `world_events` 与 `save_event`。
- CONSUME **必须**走 `consume_object`（精确数量），**不得**用 `apply_object_action("eat")` 替代。
- 动作执行**必须保序**，禁止并发/重排。
- 失败**不得**补偿写；不得吞掉引擎错误码（必须进 trace 与 `MutationOutcome`）。
- 若采纳 `EventSource.CHARACTER`，属**加性变更**，需在实现评审明确；否则复用 `AUTONOMY`。
- 不添加代码注释，用命名表达意图。
