# ACTION-001 Task Detail — WorldAction 基础模型

> 上游：[../tasks.md](../tasks.md) ACTION-001 ｜ 架构：[../architecture.md](../architecture.md) §6 ｜ 依赖：无
> Priority：**P0** ｜ 层级：Foundation（唯一契约前置）

---

## Background

角色回复里的行为（「我用了两个鸡蛋」）目前没有任何结构化载体。三层（Character / Action / World）之间如果要传值，必须有一个**双方都认识的值对象**；否则 Action Layer 只能把原文丢给 World Layer，等于让引擎去解析自然语言——违反「World Layer 不做自然语言推理」的边界（[../architecture.md](../architecture.md) §4.1）。

既有模型都不适配：

| 既有模型 | 为何不复用 |
|---|---|
| `models/action.py` `ActionIntent` / `ActionRecord` | 是**用户祈使**行动的模型，`ActionType` 为闭合字面量（无 consume），语义与"角色叙事行为提案"不同；改它属对 V9 的非必要改造 |
| `models/world.py` `WorldObject` | 描述世界**状态**（是什么），不描述**意图**（要做什么） |
| `models/scene.py` `PendingAction` | V3 叙事场景内的动作字符串，无类型、无数量、无校验语义 |
| `models/world.py` `WorldUpdateResult` | 是**解释器内部**的输出结构，字段与世界迁移强耦合（moves/state_actions/creations），不是动作契约 |

因此需要一个**新的纯数据契约**：`WorldAction`。它是本模块的地基，其余四个 Task 全部围绕它展开。

## Objective

建立 `WorldAction` 值对象与 `WorldActionStatus` 生命周期状态机，并沉淀 Character 层的**叙事行为词表资产骨架**（只有设定、没有逻辑），使：

- 三条链路（既有解释器 / V9 行动 / 本模块）之间**不共享实现、只共享出口**；
- 每条动作可被序列化、可被判状态、可被幂等去重、可被 trace。

## Existing Architecture

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/models/action.py` | V9 `ActionIntent` / `ActionRecord` / `make_dedupe_key` / `normalize_core_params` / `transition_action` | **不修改**；仅参考其状态机纪律与幂等键风格 |
| `app/models/world.py` | `WorldObject` / `ConsumeError` / `ConsumeResult` | **不修改**；错误码风格对齐 `ConsumeError` |
| `app/services/world/interpreter.py` | `WorldUpdateResult` dataclass（世界迁移提案） | **不修改**；作为"既有链路"参照 |
| `app/character/asuna/action.py` | `ACTION_TRIGGER_LEXICON` / `OBJECT_CATEGORY_KEYWORDS` / `infer_object_category` | **不修改**；新增叙事词表放在同目录（见下） |
| `app/character/asuna/world.py` | `HOME_LOCATIONS` / `LOCATION_ALIASES` / `OBJECT_CREATION_HINTS` | **不修改**；地点/物品词表复用 |

**放置约定**（沿既有工程惯例）：纯数据与纯函数进 `app/models/`；角色静态词表进 `app/character/asuna/`。

## Data Model

### WorldAction（值对象）

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `action_id` | str | ✅ | 候选唯一标识（`wa_{uuid8}`），用于 trace 与事件关联 |
| `action_type` | `ActionType` | ✅ | `CREATE` / `MOVE` / `CONSUME`（第一阶段仅此三值） |
| `actor` | `Actor` | ✅ | 行为主体；本阶段恒为 `character`（预留 `user` / `autonomy`） |
| `target` | `TargetRef` | ✅ | 目标实体引用（见下） |
| `quantity` | float \| null | ⭕ | `CONSUME` 数量；`CREATE` 数量（默认 1）；`MOVE` 为 null |
| `source` | `ActionSource` | ✅ | 来源通道：`character_reply` / `user_message` / `autonomy` / `manual` |
| `metadata` | dict | ⭕ | 附加事实（见下）；有界、可序列化 |
| `status` | `WorldActionStatus` | ✅ | 生命周期状态，初始恒为 `candidate` |
| `dedupe_key` | str | ✅ | 幂等键（见「幂等」节） |
| `turn_ref` | `TurnRef` | ✅ | `{session_id, turn_id, ordinal}`，归属轮次与轮内序号 |
| `created_at` | datetime | ⭕ | 构造时间 |

### 枚举

| 枚举 | 取值 |
|---|---|
| `ActionType` | `CREATE` · `MOVE` · `CONSUME` |
| `Actor` | `character` · `user` · `autonomy` |
| `ActionSource` | `character_reply` · `user_message` · `autonomy` · `manual` |
| `WorldActionStatus` | `candidate` · `validated` · `rejected` · `applied` · `failed` · `skipped` |
| `WorldActionReason` | 校验拒绝原因枚举（定义于此，供 ACTION-003 使用）：`DISABLED` · `UNSUPPORTED_TYPE` · `LOW_CONFIDENCE` · `OBJECT_NOT_FOUND` · `NOT_CONSUMABLE` · `INSUFFICIENT_QUANTITY` · `INVALID_QUANTITY` · `LOCATION_UNRESOLVED` · `LOCATION_UNREACHABLE` · `DUPLICATE_ENTITY` · `ENTITY_LIMIT` · `NO_OP` · `DUPLICATE` · `WORLD_UNAVAILABLE` · `ENGINE_FAILED` |

### TargetRef

| 字段 | 说明 |
|---|---|
| `name` | 从叙事中提取的对象名（resolve 前唯一必需字段） |
| `object_id` | 校验通过后回填的真实实体 id（`world_entities.id`） |
| `category` | `CREATE` 时推断的类目（复用 `infer_object_category`） |
| `location_id` | `MOVE` 的目标地点（`HOME_LOCATIONS` key）；`CREATE` 时的落点 |
| `location_from` | `MOVE` 的原地点（回填，用于审计与事件） |
| `aliases_hint` | 可选，叙事中的别名线索 |

### metadata（有界字典）

| 键 | 说明 |
|---|---|
| `evidence` | 触发该动作的原文片段（≤N 字） |
| `span` | 在 `ai_reply` 中的字符区间 `[start, end]` |
| `channel` | `lexicon` / `llm_assist` |
| `confidence` | `high` / `medium` / `low`（提取通道给出） |
| `unit` | 单位（如 `piece` / `kg`），来自既有实体或默认 |
| `before` / `after` | 执行前后快照（ACTION-004 回填）：quantity / state / location_id |
| `recipe_ref` | **预留**，未来 Cooking/Recipe 关联 |

### Character 层词表资产（骨架，仅数据）

| 资产 | 内容 |
|---|---|
| `NARRATIVE_ACTION_VERBS` | 叙事动词 → 动作类型（如 `用了/吃掉/喝了` → CONSUME；`做好/煮了/盛了/端出` → CREATE；`拿到/放到/搬到` → MOVE） |
| `NARRATIVE_QUANTITY_WORDS` | 中文数字与量词（`一/两/二/…/半`、`个/枚/杯/碗/盒/块`） |
| `NARRATIVE_NOISE_PATTERNS` | 疑问/假设/未来/复述守卫模式 |
| `NARRATIVE_OBJECT_NOUNS` | 可识别物品名词（与既有库存名/别名、`OBJECT_CREATION_HINTS` 合并使用） |

## Interfaces

> 以下为**概念契约**，描述对外可见的能力与语义，不含实现。

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 构造候选 | 动作类型 / 主体 / 目标 / 数量 / 来源 / metadata / 轮次引用 | `WorldAction(status=candidate)` | 提取器唯一的产出形式 |
| 状态迁移 | 当前状态 + 迁移事件 | 新状态 或 `None` | 纯函数；非法迁移返回 `None`（沿 V8/V9 纪律） |
| 生成幂等键 | 动作核心字段 | `dedupe_key` | 纯函数；语序无关、内容敏感 |
| 规范化核心字段 | 字段字典 | 规范化字典 | 去空白、字符串化、按键排序（对齐 `normalize_core_params`） |
| 判定终态 | 状态 | bool | 供编排层决定是否继续处理 |

**模型层守卫**：`action_type` 必须属于三值；`target.name` 非空；`quantity` 若给出必须 > 0；`actor` / `source` 必须属于枚举。构造期即拒绝非法值（fail-fast），避免脏值流入校验与引擎。

## Processing Flow

```text
Action Extractor（ACTION-002）
        │  逐条构建
        ▼
WorldAction(status=candidate)
        │
        ├──► 序列化进 trace（可观测）
        ├──► 参与轮内去重集合
        ▼
Action Validator（ACTION-003）──► validated | rejected
        ▼
World Engine（ACTION-004）──► applied | failed
```

本 Task 只交付「构造 + 迁移 + 幂等键 + 词表骨架」四件事实，不含任何 IO。

## State Transition

```text
                    ┌───────────────┐
                    │   candidate   │  ← 唯一合法初始态
                    └───────┬───────┘
        ┌───────────────────┼───────────────────┬──────────────┐
        │ validate_pass     │ validate_reject   │ skip         │
        ▼                   ▼                   ▼              │
   ┌───────────┐      ┌───────────┐       ┌──────────┐          │
   │ validated │      │ rejected  │(终)   │ skipped  │(终)      │
   └─────┬─────┘      └───────────┘       └──────────┘          │
      engine_ok │  engine_fail                                  │
        ▼       ▼                                              │
  ┌─────────┐ ┌────────┐                                      │
  │ applied │ │ failed │(终)                                  │
  │  (终)   │ └────────┘                                      │
  └─────────┘
```

| 当前状态 | 事件 | 目标状态 |
|---|---|---|
| `candidate` | `validate_pass` | `validated` |
| `candidate` | `validate_reject` | `rejected` |
| `candidate` | `skip` | `skipped` |
| `validated` | `engine_ok` | `applied` |
| `validated` | `engine_fail` | `failed` |
| 其余任意 | 任意 | `None`（非法，拒绝） |

**不变量**：`rejected` / `applied` / `failed` / `skipped` 为终态；终态不可再迁出。

## Error Handling

| 情形 | 处理 |
|---|---|
| 字段缺失/类型错误 | 模型构造期拒绝（抛校验错误 → 提取器跳过该条并 trace） |
| `action_type` 不在三值内 | 构造期拒绝（`UNSUPPORTED_TYPE` 语义） |
| `quantity ≤ 0` | 构造期拒绝（`INVALID_QUANTITY` 语义） |
| 非法状态迁移 | 返回 `None`，调用方保持原状态并 trace |
| 未知迁移事件 | 返回 `None`（不抛异常，不静默改状态） |

## Idempotency

- **键构成（概念）**：`action_type` + `actor` + `target.canonical_name` + `quantity` + `source` + `session_id` + `turn_id` + `ordinal`，经规范化后串联并取哈希前 16 位（风格对齐 `models/action.py:make_dedupe_key`）。
- **规范化规则**：去首尾空白、内部空白折叠、字符串化、按键排序、忽略 `None`；`quantity` 归一为数值字符串（`2` 与 `2.0` 视为同一）。
- **语义**：**语序无关**（参数顺序不影响键）、**内容敏感**（数量/对象/轮次不同即不同键）。
- **覆盖范围**：同轮内 ordinal 区分同类型重复动作（如两次 `CONSUME 鸡蛋 1` 的键不同，交由 ACTION-003 的库存判定裁决是否都成立）。
- **不负责**：跨进程强幂等（见 [ACTION-004](ACTION-004.md)）。

## Transaction Boundary

**无事务**。本 Task 是纯值对象与纯函数：零 IO、零数据库、零副作用。构造与迁移均可在内存中完成并重复调用。这一"无副作用"属性是后续幂等与可重放的前提（INV-4）。

## Observability

- `WorldAction` 必须可无损序列化（供 trace 的 `bound_extra` 与事件 payload 使用）。
- 建议的 trace 字段：`action_type` / `status` / `reason` / `target.name` / `quantity` / `source` / `channel` / `evidence`。
- 序列化必须**有界**（复用 `models/observability.bound_extra`），避免 evidence 全文膨胀 trace。

## Testing

| 类型 | 用例 |
|---|---|
| Unit（状态机） | 全合法迁移逐条断言；全非法迁移（跨状态、终态迁出、未知事件）返回 `None` |
| Unit（模型守卫） | 空 name / 负数量 / 未知 action_type / 未知 source 一律构造失败 |
| Unit（幂等键） | 参数顺序不同 → 键相同；数量或对象或轮次不同 → 键不同；`2` vs `2.0` → 键相同 |
| Property | 任意迁移序列后状态恒属于合法状态集；终态不再变化 |
| Serialization | `model_dump` → `model_validate` 往返相等 |

## Acceptance Criteria

1. 给定合法动作序列，状态机每次迁移与迁移表逐条一致。
2. 给定非法迁移（含 `applied → validated`），返回 `None` 且无副作用。
3. 给定语义相同/不同参数的两组候选，幂等键的相等性判定符合"语序无关、内容敏感"。
4. 给定 `quantity=0` 或空 name，构造被拒绝且错误可定位。
5. 词表资产能表达三类动作的最小集合（每类 ≥ 3 个动词），且不含任何逻辑分支。

## Implementation Constraints

- 不写提取/校验/执行逻辑；不引入 IO；不建表；不新增迁移。
- **不修改** `models/action.py` 与 `models/world.py` 的任何既有定义（只在 `app/models/` 新增本模块模型文件）。
- 状态机必须是纯函数，不持有状态、不访问数据库（同 V8 `apply_object_action` / V9 `transition_action` 纪律）。
- 词表属**角色资产**，放 `app/character/asuna/`，只有数据定义、无逻辑（同 `character/asuna/action.py` 既有模式）。
- 遵守项目约定：不添加代码注释，用命名表达意图。
