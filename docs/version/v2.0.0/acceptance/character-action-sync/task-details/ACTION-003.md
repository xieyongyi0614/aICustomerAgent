# ACTION-003 Task Detail — Action Validation

> 上游：[../tasks.md](../tasks.md) ACTION-003 ｜ 架构：[../architecture.md](../architecture.md) §7/§9 ｜ 依赖：ACTION-001, ACTION-002
> Priority：**P0** ｜ 层级：Core（写入链唯一权威裁决点）

---

## Background

审查报告给出的核心反例是：用户问「鸡蛋没了吗」，角色答「没了」，而库存 6 个；追问「做鸡蛋卷用了多少个」，答「只用了一个」——**系统从未记账，纯属想象**。这说明仅靠 prompt 引导语（`context_selector.py:119`"以本清单为准，不得凭空捏造或增减"）无法阻止 LLM 造事实（报告 §3 结论：**需要系统侧强制**）。

本 Task 就是系统侧强制的落点：**执行前的确定性裁决**。

**为什么引擎已经会校验，还要单独设校验闸？**
`world_engine.consume_object` 内部已会检查 `consumable` / `quantity` 并返回 `ConsumeResult`。但引擎的检查是**最终安全网**（防脏写），回答不了「为什么这条没生效」「是对象不存在还是数量不够」。校验闸是**可归因的决策点**，且能在写入前就把明显不可能的动作拦掉，避免引擎在"半合法"输入上留下部分副作用。两者职责不同，必须都在。

## Objective

为每个候选 `WorldAction` 给出 `validated` 或 `rejected(reason)`：

- **失败零变更**：任何拒绝都不得修改 World（INV-3）；
- 覆盖任务清单要求的四类检查：**对象是否存在 / 数量是否足够 / 是否允许 consume / 位置是否合理**，外加容量、重复、去重；
- **轮内顺序一致**：同轮多条动作按文本顺序对"中间状态（working view）"校验，杜绝"两条都通过但实际只够一条"。

## Existing Architecture

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `world_engine.consume_object(user_id, object_ref, quantity)` | 已返回结构化 `ConsumeResult{ok, error, object, previous_quantity}`；错误码 `ConsumeError`（`OBJECT_NOT_FOUND`/`NOT_CONSUMABLE`/`INSUFFICIENT_QUANTITY`/`INVALID_QUANTITY`）；失败不部分扣除 | **不修改**；校验闸的错误码与之对齐，引擎作为二次保险 |
| `world_engine.find_object_by_name` / `_find_inventory_object` | 按 `id` 或 `name`/`aliases` 匹配活跃实体 | **不修改**；复用其匹配语义 |
| `world_engine.move_object` | 要求 `location_id ∈ HOME_LOCATIONS`；对象必须 `ACTIVE` | **不修改**；校验闸前置同样的白名单 |
| `world_engine.create_object` | 受 `settings.world_active_entities_limit` 限流（超限返回 `None`）；`category` 由调用方给 | **不修改**；校验闸前置容量判断 |
| `character/asuna/world.py` `HOME_LOCATIONS` | 层级地点白名单：`home` / `home.living_room` / `home.kitchen` / `home.bedroom` / `home.balcony` / `home.kitchen.fridge` / `home.kitchen.cabinet` / `home.bathroom` | **⚠️ 无餐桌/桌面节点**（见「已知缺口」） |
| `services/world/locations.py` `resolve_location_alias` | 别名 → location_id，未命中 `None` | **不修改**；复用 |
| `services/world/context_selector.py` `build_world_context` | 已产出 `inventory`（含 `consumable`/`quantity`/`location_id`） | **不修改**；作为快照来源之一 |
| `world_repository.list_objects` / `count_active_objects` / `list_events` | 只读查询 | **不修改**；快照与去重窗口读取 |
| `models/scene.py` `SceneState` | V3 叙事场景（`location`/`current_action`/`pending_action`） | **只读 advisory**（位置合理性线索、指代消解），永不作权威依据 |

### 已知缺口：`HOME_LOCATIONS` 无餐桌节点

审查报告里的「我把牛奶拿到桌上」需要目标地点 `table/dining`，而现有 `HOME_LOCATIONS` 与 `LOCATION_ALIASES` 中**不存在**该节点。按设计纪律（宁缺毋滥、不造地点），校验应判 `LOCATION_UNRESOLVED` 并拒绝，**不得**凭空创建地点。

**待评审决策（本 Task 记录，不自行决定）**：

| 方案 | 说明 | 代价 |
|---|---|---|
| A. 本阶段不做 | MOVE 到桌面一律拒绝并 trace | 功能缺失，但零风险、零资产变更 |
| B. 新增静态节点 | 在 `HOME_LOCATIONS` / `LOCATION_ALIASES` 增加 `home.dining_area`（如"餐桌/桌面/饭桌"） | 唯一的角色资产变更；需同步评估对既有地点上下文/回归的影响 |

> 若选 B，该改动归属本 Task 或 ACTION-004 的资产变更子项，且必须与 `LOCATION_ALIASES`、`HOME_LOCATIONS` 双表同步。

## Data Model

### ValidationContext（只读快照）

| 字段 | 来源 | 说明 |
|---|---|---|
| `world_id` / `user_id` | `world_engine.get_world` | 世界身份 |
| `current_location` | `world.current_location` | CREATE 默认落点、位置合理性 |
| `objects` | `world_repository.list_objects(world_id)` | 活跃实体全量（名称/别名/数量/位置/可消耗/状态） |
| `active_count` | `count_active_objects` | 容量判断 |
| `entity_limit` | `settings.world_active_entities_limit` | 容量阈值 |
| `recent_dedupe_keys` | `world_repository.list_events(statuses=["completed"], limit=N)` → `payload.dedupe_key` | 有界跨轮去重窗口 |
| `scene_advisory` | `SceneState`（只读） | 位置/指代线索 |

### ValidationResult

| 字段 | 说明 |
|---|---|
| `action` | 原候选（回填 `target.object_id` / `target.location_id` 等） |
| `status` | `validated` 或 `rejected` |
| `reason` | 拒绝原因枚举（ACTION-001 `WorldActionReason`，本 Task 追加 `AMBIGUOUS_TARGET` 并回填枚举） |
| `detail` | 有界人类可读说明（进 trace，不进 prompt） |

### Working View（轮内中间状态）

| 内容 | 说明 |
|---|---|
| `remaining_quantity: dict[object_id, float]` | 初始 = 快照数量；每个 accepted CONSUME 递减 |
| `created_entities: list[{synthetic_id, name}]` | 每个 accepted CREATE 登记，供同轮后续 MOVE/CONSUME 引用 |
| `location_overrides: dict[object_id, location_id]` | 每个 accepted MOVE 更新 |

## Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 快照装配 | `user_id` | `ValidationContext` | 读一次世界；失败 → 空上下文（后续全判 `WORLD_UNAVAILABLE`） |
| 校验入口 | `list[WorldAction]`、`ValidationContext` | `list[ValidationResult]` | 按文本顺序逐条裁决 |
| 对象解析 | 名称/别名、快照 | 唯一实体 或 `None`/多义 | 复用既有匹配语义；多义 → `AMBIGUOUS_TARGET` |
| 地点解析 | 地点文本 | `location_id` 或 `None` | 复用 `resolve_location_alias` + `HOME_LOCATIONS` 白名单 |
| 可达性判定 | 对象位置、目标位置、`current_location`、`scene_advisory` | bool | 见「可达性策略」 |
| 幂等判定 | `dedupe_key`、轮内接受集、`recent_dedupe_keys` | bool | 命中即 `DUPLICATE` |

### 可达性策略（location 是否合理）

统一规则（**可配置，默认宽松**），对 MOVE 与 CONSUME 生效：

```text
可达 ⇔ 对象所在位置 ∈ 角色当前位置的子树
     或 角色当前位置 ∈ 对象所在位置的子树
     或 角色当前位置与对象所在位置同属一个房间簇（如 home.kitchen 与 home.kitchen.fridge）

不可达 → 拒绝（LOCATION_UNREACHABLE），不改世界
```

- 判据优先用 **`world.current_location`**（世界事实）；`scene_state.location` 仅作 advisory（当两者冲突时以世界为准，并记 trace）。
- 默认宽松档：容器（fridge/cabinet）与所属房间（kitchen）视为同簇，避免"在厨房拿冰箱里的东西"被误拒。

## Processing Flow

```text
candidates（文本顺序）
        │
   装配一次快照（ValidationContext）── 失败 → 全部 WORLD_UNAVAILABLE
        │
   逐条（i = 1..n）：
        ├─ G0 总闸/世界可用 ──────────────► WORLD_UNAVAILABLE / DISABLED
        ├─ G1 类型受支持（三值） ─────────► UNSUPPORTED_TYPE
        ├─ G2 置信度门（LLM 通道）────────► LOW_CONFIDENCE
        ├─ G3 幂等（轮内 + 近期窗口）──────► DUPLICATE
        ├─ G4 类型专属检查（见下）─────────► 具体原因
        │      CREATE: 名称/类目/落点白名单/同名实体/容量
        │      MOVE:   对象存在&ACTIVE / 目标白名单 / 非 NO_OP / 可达
        │      CONSUME:对象存在&ACTIVE / consumable / 数量>0 / 数量充足 / 可达
        ├─ 通过 → status=validated；回填 object_id/location_id
        │        并更新 Working View（扣数量 / 登记新实体 / 改位置）
        └─ 拒绝 → status=rejected(reason)；**不更新 Working View**
```

**要点**：Working View 只在 accepted 时更新；拒绝的动作对后续候选零影响。这样「库存 1、两条各消耗 1」时，第 2 条看到剩余 0 → `INSUFFICIENT_QUANTITY`。

## State Transition

本 Task 完成 `WorldAction` 生命周期的第一段迁移（详见 [ACTION-001](ACTION-001.md) §状态迁移）：

| 当前 | 事件 | 目标 |
|---|---|---|
| `candidate` | `validate_pass` | `validated` |
| `candidate` | `validate_reject` | `rejected`（终态） |

拒绝原因与检查项一一对应：

| reason | 触发 |
|---|---|
| `DISABLED` / `WORLD_UNAVAILABLE` | 总闸关 / 世界不可用 |
| `UNSUPPORTED_TYPE` | 动作类型不在三值内 |
| `LOW_CONFIDENCE` | LLM 通道且置信度低于阈值 |
| `OBJECT_NOT_FOUND` | 名称/别名无匹配活跃实体 |
| `AMBIGUOUS_TARGET` | 多个活跃实体同名（需回填 ACTION-001 枚举） |
| `NOT_CONSUMABLE` | 目标 `consumable=False` |
| `INVALID_QUANTITY` | 数量缺失或 ≤ 0 |
| `INSUFFICIENT_QUANTITY` | Working View 剩余量 < 请求量 |
| `LOCATION_UNRESOLVED` | 地点文本无法解析为 `HOME_LOCATIONS` 成员 |
| `LOCATION_UNREACHABLE` | 可达性策略判定不可达 |
| `DUPLICATE_ENTITY` | CREATE 的名称与既有活跃实体同名 |
| `ENTITY_LIMIT` | 活跃实体数达 `world_active_entities_limit` |
| `NO_OP` | MOVE 目标位置 == 当前位置 |
| `DUPLICATE` | 幂等键命中轮内接受集或近期窗口 |

## Error Handling

| 情形 | 处理 |
|---|---|
| 快照装配失败 | 全部候选判 `WORLD_UNAVAILABLE`，不尝试任何写入 |
| 单条检查抛异常 | 该条判 `rejected`（`detail` 记异常摘要），**不影响其余条** |
| 对象解析多义 | `AMBIGUOUS_TARGET`（宁缺毋滥，不猜） |
| 数量为非数值（"若干"） | `INVALID_QUANTITY`（不猜数量） |
| 引擎与校验结论不一致（理论不应发生） | 以引擎为准，`failed` + trace（ACTION-004 负责） |
| 任何未预期异常 | 捕获 → 全量 `rejected`，World 零变更 |

## Idempotency

- **轮内**：已 `validated` 的 `dedupe_key` 进入接受集；后续同键候选判 `DUPLICATE`。
- **跨轮（有界窗口）**：读取最近 `world_events(type=character_action)` 的 `payload.dedupe_key` 集合；命中判 `DUPLICATE`。窗口大小由配置决定（如最近 50 条 / 最近 1 小时）。
- **保证范围**：覆盖"同轮重复提取""相邻轮重复同步"；**不覆盖**进程崩溃后的强幂等（依赖 P5 `background_jobs`/`outbox_events`，见 [ACTION-004](ACTION-004.md)）。
- **与提取的分工**：提取只做字面去重，语义级幂等由本 Task 负责。

## Transaction Boundary

- 本 Task **只读**：装配一次快照，全部检查在内存完成；**零写库**。
- 快照在读锁外获取（`post_process` 的 per-user 写锁保证轮内串行，故无需额外锁）。
- 快照是**某一时刻**的世界视图；校验与 ACTION-004 的执行之间存在极小窗口。该窗口由两个因素封死：(1) per-user 写锁使同用户轮内串行；(2) 引擎在写入时**再校验一次**（尤其是 `consume_object` 的数量）。
- 因此"校验通过但执行失败"是罕见路径，且必然落到 `failed` + trace 可归因。

## Observability

- 逐条记录：`{action_type, target.name, quantity, status, reason, engine_fn(未定), before/after(未定)}`；经 `bound_extra` 有界。
- 汇总：`candidates / validated / rejected / reasons 直方图`。
- 必须能回答：「这条为什么没生效？」——精确到 reason + 当时的剩余量或解析结果。
- 拒绝原因**不得**进入 prompt（不污染【当前世界】段）。

## Testing

| 类型 | 用例 |
|---|---|
| Unit（表驱动） | 上表 15 个 reason 各 ≥ 2 例，逐条断言 |
| Unit（顺序） | 库存 1 + 两条 `CONSUME 鸡蛋 1` → 第 1 条 validated、第 2 条 `INSUFFICIENT_QUANTITY` |
| Unit（跨类型顺序） | `CREATE 面` + `CONSUME 面 1` → 后者在 Working View 命中新实体 |
| Unit（地点） | 「牛奶拿到桌上」→ `LOCATION_UNRESOLVED`（缺口验证）；「牛奶拿进厨房」→ validated |
| Unit（多义） | 两个同名活跃实体 → `AMBIGUOUS_TARGET` |
| Integration | 复现审查报告：`CONSUME 鸡蛋 1` 于库存 6 → validated；`CONSUME 鸡蛋 5` 于库存 6 → validated；`CONSUME 鸡蛋 7` → `INSUFFICIENT_QUANTITY` |
| Idempotency | 同轮重放 / 近期窗口内重放 → `DUPLICATE` |
| FailureInjection | 快照装配失败 / 单条抛异常 → 零写入、其余条不受影响 |
| Property | 拒绝集合与 Working View 更新集合互斥；校验后 World 行数/数量逐行不变 |

## Acceptance Criteria

1. 库存 6 个鸡蛋 + `CONSUME 鸡蛋 2` → `validated`；`CONSUME 鸡蛋 5` → `validated`；`CONSUME 鸡蛋 7` → `INSUFFICIENT_QUANTITY`。
2. 不存在的物品（番茄汤）→ `OBJECT_NOT_FOUND`。
3. `consumable=False` 的实体被 CONSUME → `NOT_CONSUMABLE`。
4. `MOVE 牛奶 → 桌上`（无该地点节点）→ `LOCATION_UNRESOLVED`，World 零变更。
5. 同轮两条消耗而库存仅够一条时，仅第一条 `validated`。
6. 校验阶段对 World 的写入次数为 0。
7. 任一拒绝发生后，`world_entities` 逐行与校验前一致。

## Implementation Constraints

- **零写入**：不得调用 `world_engine` 的写函数；对象与地点解析只允许只读能力。
- 不修改 `world_engine` / `interpreter` / `detector` / `models/world.py` 的既有语义；新增校验逻辑放 `app/services/` 层。
- 错误码必须复用/对齐既有 `ConsumeError` 语义，不另造一套并行命名。
- `scene_state` 仅 advisory：位置权威一律以 `world.current_location` 为准。
- 可达性策略必须可配置（宽松档默认），且规则集中在一处，便于后续调整。
- 不含自然语言推理、不含 grounding 校验（另行立项）；不添加代码注释。
