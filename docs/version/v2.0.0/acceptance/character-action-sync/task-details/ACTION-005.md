# ACTION-005 Task Detail — Context 与历史同步

> 上游：[../tasks.md](../tasks.md) ACTION-005 ｜ 架构：[../architecture.md](../architecture.md) §5/§10 ｜ 依赖：ACTION-004
> Priority：**P1** ｜ 层级：Integration（闭合回路）

---

## Background

即使 ACTION-004 已把世界改对了，如果**下一轮角色看不到**刚发生的变化，回路仍然是断的：角色会继续把 6 个鸡蛋当成 6 个（因为它的"记忆"来自 Context），审查报告里的"编造"会以另一种形式复现。

现状是：

- `run_world_update`（第 8 步）会把**用户消息解释器**的 `notes` 写进 `world.notes`（`world_engine.py`：`refreshed.notes = bounded_notes(notes, max(64, world_context_char_budget // 4))`）；
- `context_selector.build_world_context` 把 `world.notes` 放进 `WorldContext.notes`，`render_world_section` 渲染进【当前世界】段（预算 600，`world_context_char_budget`）；
- 但 `world.notes` 是**每轮覆盖**的（下一轮第 8 步会重写），且**不包含角色自己做过的事**。

因此需要两层：
1. **持久历史**（可查询、跨轮、跨重启）：已 applied 的动作落成 `WorldEvent(type=character_action)`（ACTION-004 已落，本 Task 负责读）；
2. **本轮摘要**（即时、面向下一轮）：把角色动作摘要追加进 `world.notes`，与解释器 notes **合并而非覆盖**。

## Objective

让下一轮角色知道"最近发生的世界变化"，输出形如：

```text
最近世界变化：
- 消耗鸡蛋 ×2
- 做出鸡蛋卷
- 牛奶移到厨房
```

具体目标：

- 从 `character_action` 事件派生**有界**的最近变化清单；
- 与 `world.notes`（解释器 notes）**共存**，不互相覆盖、不重复；
- 在既有【当前世界】段内渲染，**不新增 prompt 段标题**，不突破既有预算；
- 总闸关闭时渲染**逐字节不变**（golden 不变量）；
- 意外收益：事件被既有 Memory 2.0 摄取通道消费（见下）。

## Existing Architecture

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `world_engine.run_turn_update` | 把解释器 `notes` 写入 `world.notes`（`bounded_notes`） | **不修改**；CAS 在其之后**追加**自身 notes |
| `models/world.py` `World.notes: list[str]` | 每轮覆盖的短摘要 | **不修改**；CAS 追加（读-改-写，同锁内） |
| `models/world.py` `bounded_notes(notes, max_chars)` | 有界截断 | **复用** |
| `models/world.py` `WorldContext` | 含 `time/location/environment/nearby_objects/inventory/salient_events/notes` | **加性扩展**：新增 `recent_world_changes: list[str]`（默认空，向后兼容） |
| `services/world/context_selector.py` `build_world_context(...)` | 组装 `WorldContext` | **加性扩展**：按 `character_action` 事件派生 `recent_world_changes` |
| `services/world/context_selector.py` `render_world_section(ctx, budget=600)` | 渲染 guide_line + inventory + event_lines + note_lines + env，按预算顺序截断 | **加性扩展**：插入"最近世界变化"行块（在 note_lines 位置附近），参与同一预算 |
| `world_repository.list_events(world_id, statuses, limit)` | 已有只读查询 | **复用**；按 `type=character_action` 过滤、按时间倒序取最近 N |
| `world_repository.save_event` / `WorldEvent` | 事件落库 | 复用（ACTION-004 已落） |
| `world_repository.save_world` | 保存 `world.notes` | 复用 |
| `post_process._run_memory_ingest_v2` → `memory_sources.fetch_completed_world_events` → `memory_ingest.ingest_from_world_event` | 已完成的世界事件会被摄取为记忆候选（幂等键跨轮收敛） | **零改动受益**：角色自主动作事件将自然进入记忆通道 |
| `settings.world_context_char_budget`（600） / 总预算 12000 | 既有预算 | **不修改** |

### 时序说明（为什么本节录不会当轮进 Memory）

`post_process.STEP_HANDLERS` 顺序为：`memory_extract`（第 5 步）**先于** `world_update`（第 8 步）与 `character_action_sync`（第 9 步）。故本轮新落的 `character_action` 事件**不会当轮**被摄取，而由**下一轮的摄取通道经幂等键补扫收敛**（`_run_memory_ingest_v2` 的既有注释已明确此设计）。本 Task 不改变该时序，也不直接调用 Memory。

## Data Model

### `WorldContext` 加性字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `recent_world_changes` | `list[str]` | 有界的"最近世界变化"人类可读行（默认空列表；字段缺省不影响既有调用方） |

### 行格式（渲染契约）

| action_type | 行格式 |
|---|---|
| `CONSUME` | `消耗{name} ×{qty}` |
| `CREATE` | `做出{name}` |
| `MOVE` | `{name}移到{地点名}`（用 `location_name` 转中文名） |

- 去数量为 1 时可省略 `×1`（与既有 inventory 行风格对齐）。
- 行内容取自 `WorldEvent.title`（ACTION-004 已生成人类可读 title），本 Task 负责**选取与排序**，不重新生成语义。
- 强约束：**行内容必须来自事件 payload/title，不得由 LLM 生成**（否则又引入一次幻觉源）。

### `World.notes` 合并约定

| 来源 | 内容 |
|---|---|
| 解释器 notes | 用户消息引发的世界变化（既有，如"鸡蛋已从冰箱取出"） |
| CAS notes | 角色动作摘要（本 Task 追加） |

合并规则：读当前 `world.notes` → 追加 CAS 行 → 去重（精确相等）→ `bounded_notes` 截断 → `save_world`。

## Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 最近变化派生 | `world_id`、limit、时间窗口 | `list[str]` | 从 `character_action` 事件派生；失败 → 空列表 |
| Context 装配扩展 | 既有 `build_world_context` 参数 | `WorldContext`（含 `recent_world_changes`） | 纯函数，无 IO 增量（事件由调用方传入或内部只读查询） |
| 渲染扩展 | `WorldContext`、预算 | 渲染文本 | 在既有【当前世界】段内插入行块，参与同一预算 |
| notes 合并 | 现有 notes、CAS 行 | 合并后 notes | 幂等、有界 |
| 事件窗口查询 | `world_id`、窗口大小 | `list[WorldEvent]` | 复用 `list_events` + `type` 过滤 |

## Processing Flow

```text
【本轮，post_process 第 9 步尾部】
ACTION-004 outcomes(applied)
        │
        ├─(1) 生成 CAS notes 行（来自 WorldEvent.title）
        ├─(2) 读 world.notes（第 8 步解释器写入）→ 追加 → 去重 → bounded_notes → save_world
        └─(3) trace：recent_lines 条数 / 被预算截断数

【下一轮，前台 build_context】
world_engine.build_context(user_id)
        │
        ├─(1) list_events(world_id, statuses=["completed"], limit=N) → 过滤 type=character_action
        ├─(2) 取最近 K 条 → 派生 recent_world_changes（有界）
        ├─(3) build_world_context(...) 填充 WorldContext.recent_world_changes
        └─(4) render_world_section：guide → inventory → 最近世界变化 → events → notes → env（同一预算内截断）
                │
                └──► LLM 看到真实数量 + 刚发生过的事
```

### 渲染顺序与预算

在既有顺序中插入，保持"最重要优先"的截断语义：

```text
【当前世界】
{时间/位置 head}
家里的物品、数量、位置与可消耗状态以本清单为准，不得凭空捏造或增减。   ← 既有 guide_line
{库存行}                                                          ← 既有 inventory
最近世界变化：                                                     ← 新增（本 Task）
  - 消耗鸡蛋 ×2
  - 做出鸡蛋卷
{事件行}                                                          ← 既有 salient events
{notes 行}                                                        ← 既有（解释器 notes）
{环境行}                                                          ← 既有
```

- 全部计入同一 `budget`（默认 600 / `world_context_char_budget`），**不得突破**。
- 与 `note_lines` 精确重复的行**只渲染一次**（以"最近世界变化"优先）。
- 条数上限 `v2_character_action_sync_context_lines`（默认 3）。

## State Transition

本 Task 不改变任何实体的状态机。它维护的是一条**派生视图的生命周期**：

| 视图 | 生命周期 | 权威性 |
|---|---|---|
| `WorldEvent(type=character_action)` | 持久（受 `world_event_retention_days` 保留策略） | 历史投影，**不可**作为当前状态读 |
| `WorldContext.recent_world_changes` | 轮级（每次 `build_context` 重建） | 派生视图 |
| `world.notes` | 轮级（每轮第 8 步覆盖 + 第 9 步追加） | 派生视图 |

**硬规则**：三者的信息来源都是 `world_events`；**任何代码不得**以"历史发生过 X"推断"现在 X 还在"——当前状态只能读 `world_entities`（[../architecture.md](../architecture.md) §4.5）。

## Error Handling

| 情形 | 处理 |
|---|---|
| 事件查询失败 | `recent_world_changes` 置空；其余【当前世界】段照常渲染 |
| 事件 payload 缺字段 | 跳过该行（不渲染半截语句） |
| notes 读取/保存失败 | log + trace；**不影响**已生效的世界状态；下一轮仍可从事件派生 |
| 预算不足容纳新块 | 按既有截断语义丢弃新块（保持 guide/inventory 优先） |
| 总闸关闭 | `recent_world_changes` 不派生、不渲染（逐字节等同现状） |
| 任何异常 | 捕获 → 空扩展，聊天与渲染不失败 |

## Idempotency

- **事件不重复**：ACTION-004 在落库前以 `dedupe_key` 检查近期窗口；本 Task 只读，不产生新事件。
- **渲染确定**：同 `WorldContext` 输入 → 同渲染输出（纯函数）；无随机、无时间依赖（时间来自既有 `TimeContext`）。
- **notes 合并幂等**：同轮重复执行合并不产生重复行（精确去重 + 有界）。
- **重复渲染防护**：`recent_world_changes` 与 `notes` 交叉去重。

## Transaction Boundary

- **读侧**（`build_context` / `render_world_section`）：纯只读，前台链路的读取进链部分，无事务写。
- **写侧**（notes 合并）：**一次** `world_repository.save_world`，单行更新，原子。
- **与第 8 步的边界**：CAS 必须在 `run_world_update` **之后**执行，否则解释器 notes 会覆盖 CAS notes。此顺序由 `STEP_HANDLERS` 注册顺序保证（CAS 位于第 9 步位次）。
- **与 ACTION-004 的边界**：notes 合并只在存在 applied 动作时执行；全部被拒/失败时，notes 保持第 8 步结果不变（不写空行）。
- notes 写入失败**不回滚**已生效的世界变更（同 ACTION-004 原则）。

## Observability

- trace：`recent_world_changes` 条数、被预算截断数、notes 合并前后长度、`world_event_id` 列表（bounded）。
- 必须能回答：「下一轮角色实际看到了什么？」——可通过 prompt_snapshots（既有）与 trace 双重验证。
- 禁止把 trace 或拒绝原因写入 prompt。

## Testing

| 类型 | 用例 |
|---|---|
| Unit | 行格式（三类动作 × 有/无数量）；地点名中文化；空事件 → 空列表 |
| Unit（预算） | 事件行很多时，新块在预算内截断且不突破 600；guide/inventory 优先级不被挤掉 |
| Unit（去重） | `recent_world_changes` 与 `notes` 重复行只渲染一次 |
| Integration | 本轮 `CONSUME 鸡蛋 2` → 下一轮 `WorldContext.recent_world_changes` 含「消耗鸡蛋 ×2」，且库存行数量为 4 |
| Integration | 本轮 `CREATE 面` → 下一轮上下文含「做出面」且库存出现该实体 |
| Integration（共存） | 用户消息触发解释器 notes（如"鸡蛋已从冰箱取出"）与角色动作 notes **同时存在** |
| Integration（Memory 受益） | 下一轮 `_run_memory_ingest_v2` 能摄取 `character_action` 事件（幂等，不重复） |
| Regression | 总闸关闭 → `render_world_section` 输出与现状**逐字节一致**；v1 全量 golden 不变 |
| Performance | 事件查询 + 派生 + 渲染 P95 增量 < 5ms |

## Acceptance Criteria

1. 给定本轮消耗鸡蛋 2 个，下一轮 `WorldContext` 含「消耗鸡蛋 ×2」并渲染在【当前世界】段内。
2. 给定本轮 CREATE 一个实体，下一轮上下文含该实体，且库存列表出现**真实数量**。
3. 给定既有用户消息世界迁移（解释器 notes）与本轮角色动作，两类摘要**同时存在**，互不覆盖。
4. 总闸关闭时，【当前世界】渲染逐字节等同现状（golden 不变）。
5. 给定同一 turn 重放，`character_action` 事件不重复累积。
6. 【当前世界】段总长度不超过既有预算，且未新增 `【…】` 段标题。

## Implementation Constraints

- `WorldContext` 的扩展必须是**加性**（默认空、向后兼容），不得删除或改名既有字段。
- **不修改** `render_world_section` 的既有优先级与预算语义；只在既有段内插入行块。
- **不修改** `world_engine.run_turn_update` 与 `interpreter.py`；notes 合并是**追加**，不是替换。
- 渲染内容**不得**由 LLM 生成，必须来自 `WorldEvent` payload/title。
- **不新增 prompt 段标题**；一切内容在既有【当前世界】段内。
- 不直接调用 Memory / Reflection / Relationship；事件被摄取属既有通道的自然受益。
- 不新增表、不新增迁移；不添加代码注释，用命名表达意图。
