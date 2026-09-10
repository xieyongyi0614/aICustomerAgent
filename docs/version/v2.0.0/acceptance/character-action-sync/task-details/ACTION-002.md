# ACTION-002 Task Detail — AI Reply Action Extraction

> 上游：[../tasks.md](../tasks.md) ACTION-002 ｜ 架构：[../architecture.md](../architecture.md) §5/§7 ｜ 依赖：ACTION-001
> Priority：**P0** ｜ 层级：Core（写入链第一道闸）

---

## Background

`application/post_process.py` 目前 9 个步骤里，只有第 8 步 `run_world_update` 会修改世界，而它吃的是 **`ctx.user_input`**（`world_engine.run_turn_update(ctx.user_id, ctx.user_input)`）。角色回复 `ctx.ai_reply` 被 `run_scene_update`（叙事场景）与 `run_memory_extract`（记忆）读取，**没有任何步骤把它翻译成世界动作**。

这就是审查报告 [household-inventory-review.md](../../../../../household-inventory-review.md) 第 4 条根因的直接体现：「角色自己『用鸡蛋做煎蛋卷』这些自主行为没有任何机制把库存扣减」。本 Task 补齐这条通道的**入口**：把 `ai_reply` 中的行为翻译成候选 `WorldAction`。

纪律优先级：v2.0.0 的原则是**规则做厚、LLM 只在必要处**（`README.md` §10.1）。因此提取以**确定性词表**为默认通道，LLM 仅作为默认关闭的可选增强。

## Objective

从 `ctx.ai_reply` 提取候选世界动作，产出 `WorldAction(status=candidate)` 列表：

- **只产出候选**，绝不修改 World（INV-4）；
- **宁缺毋滥**：疑问句 / 假设句 / 未来意愿 / 复述 / 角色扮演 一律不提取；
- 保留**证据片段、文本顺序与置信度**，供校验裁决与可观测；
- 零前台副作用、零新增前台 LLM 调用。

## Existing Architecture

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `application/post_process.py` | `STEP_HANDLERS` 9 步；`PostProcessContext` 含 `user_id`/`session_id`/`user_input`/`ai_reply`/`scene_state`/`current_turn`/`trace`/`llm` | 注册新步骤 `run_character_action_sync`（第 9 步位次，见下） |
| `application/world_engine.py` | `build_context()` 产出 `WorldContext`（含 `inventory` 名称列表、`current_location`）；`find_object_by_name` | **不修改**；只读调用以获取"已知物品名/当前位置" |
| `services/world/interpreter.py` | 动词表 `TAKE_VERBS`/`PUT_VERBS`/`CUT_VERBS`/`EAT_VERBS`/`DISCARD_VERBS`/`BUY_VERBS`；`_negated` 否定守卫；`_resolve_target` 问句不回退 | **不修改**；思路复用（动词匹配 + 否定/问句守卫） |
| `services/action/detector.py` | `_is_question_inquiry`（含 `(你|能|可以|会).{0,10}(吗|么|嘛)` 正则）、`_is_imperative` | **不修改**；守卫思路复用 |
| `character/asuna/action.py` | `OBJECT_CATEGORY_KEYWORDS` / `infer_object_category` | **不修改**；复用类目推断 |
| `character/asuna/world.py` | `DEFAULT_HOUSEHOLD`（库存名）、`OBJECT_CREATION_HINTS`、`LOCATION_ALIASES` | **不修改**；作为名词与地点词表来源 |
| `services/world/locations.py` | `resolve_location_alias` | **不修改**；地点解析复用 |
| `models/scene.py` | `SceneState`（`current_action` / `pending_action` / `location`） | **只读咨询**；辅助指代消解 |
| `app/character/asuna/`（ACTION-001 新增词表） | `NARRATIVE_ACTION_VERBS` / `NARRATIVE_QUANTITY_WORDS` / `NARRATIVE_NOISE_PATTERNS` / `NARRATIVE_OBJECT_NOUNS` | 使用（本 Task 的配置面） |

## Data Model

### 输入切片（只读）

| 输入 | 用途 |
|---|---|
| `ai_reply` | 提取语料 |
| `scene_state`（advisory） | 指代消解（"我把它端过去"的"它"）；位置合理性线索 |
| `WorldContext.inventory`（名称集合） | 判断叙事对象是否为**世界已知物品**（降低噪声） |
| `world.current_location` | CREATE 默认落点、MOVE 合理性线索 |
| `turn_ref` | 生成幂等键与 ordinal |

### 提取产物

| 对象 | 字段 |
|---|---|
| `ExtractionResult` | `candidates: list[WorldAction]`、`channel`、`notes: list[str]`（bounded）、`skipped_reason`（可选） |
| `WorldAction` | 见 [ACTION-001](ACTION-001.md) |
| 候选置信度 | `metadata.confidence ∈ {high, medium, low}` |

### 词表契约（Character 资产）

| 资产 | 结构 | 示例 |
|---|---|---|
| `NARRATIVE_ACTION_VERBS` | `动作类型 → (动词/句型, …)` | CONSUME：`用掉`/`用了`/`吃掉`/`喝了`；CREATE：`做好`/`做了`/`煮好`/`盛好`/`端出`/`烤好`；MOVE：`拿到`/`放到`/`搬去`/`收进` |
| `NARRATIVE_QUANTITY_WORDS` | `中文数字/量词 → 数值/单位` | `两`→2、`半`→0.5（若支持）、`个`/`枚`/`杯`/`碗`/`盒`/`块` |
| `NARRATIVE_NOISE_PATTERNS` | 守卫模式串 | `吗`/`呢`/`？`/`如果`/`要是`/`要不要我`/`我可以给你`/`你说`/`假装` |
| `NARRATIVE_OBJECT_NOUNS` | 物品名词集合 | 合并世界库存名/别名 + `OBJECT_CREATION_HINTS` 键 |

## Interfaces

> 概念契约，不含实现。

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 提取入口 | `ai_reply`、`scene_state`、`world_ctx`、`turn_ref`、门控设置 | `ExtractionResult` | 唯一对外入口；异常 → 空结果 |
| 门控判定 | 全局开关 | bool | 关闭即直接返回空 |
| 噪声守卫 | 文本片段 | bool（是否为疑问/假设/未来/复述） | 命中即整句不提取 |
| 动词匹配 | 句子 | `(动作类型, 触发动词)` 或空 | 一轮可命中多个（一条回复可有多个动作） |
| 参数抽取 | 句子 + 触发动词 | `{对象, 数量?, 地点?}` + 缺失项 | 数量可缺省（CONSUME 默认 1 份 / CREATE 默认 1） |
| 数量解析 | 数量片段 | float | 中文数字 + 阿拉伯数字 |
| 文本顺序编号 | 候选列表 | 带回 `ordinal` 的候选 | 保证执行顺序与叙事顺序一致 |

**关键纪律**：`WorldContext` / `SceneState` 在提取阶段**只读**；提取器**不 import 任何写库模块**（编译期即保证写不进来）。

## Processing Flow

```text
ai_reply
  │
  ├─(1) 门控：v2_character_action_sync_enabled?  ── 否 → 空结果
  │
  ├─(2) 分句：按句读切分为有序句段（保留原句偏移 span）
  │
  ├─(3) 逐句守卫（任一命中即跳过该句）：
  │      疑问（吗/呢/？/怎么/哪）｜假设（如果/要是/万一）
  │      未来意愿（我给你做/要不要我/马上/待会）｜复述（你说/他说的）
  │      角色扮演（假装/假如我是）｜否定（不/没/别 + 动词）
  │
  ├─(4) 动词匹配：NARRATIVE_ACTION_VERBS 命中 → (action_type, verb)
  │
  ├─(5) 参数抽取：
  │      对象 ← NARRATIVE_OBJECT_NOUNS ∩ 句中名词（含库存别名）
  │      数量 ← NARRATIVE_QUANTITY_WORDS / 阿拉伯数字（缺省见下）
  │      地点 ← resolve_location_alias（MOVE 必需；CREATE 可选）
  │
  ├─(6) 候选构造：WorldAction(status=candidate, metadata={evidence, span, channel=lexicon, confidence})
  │      · 对象或（MOVE 的）地点缺失 → 丢弃 或 标 low confidence 并交校验闸
  │      · ordinal 按句序/动词出现顺序递增
  │
  ├─(7) 轮内初步去重（同 dedupe_key 合并）
  │
  └─(8) 返回 ExtractionResult（候选按文本顺序）
```

### 数量缺省规则（重要）

| 动作 | 显式数量 | 缺省 |
|---|---|---|
| `CONSUME` | 「两个」→ 2.0；「一个」→ 1.0 | **1 份**（"用了个鸡蛋"） |
| `CREATE` | 「两碗」→ 2.0 | **1** |
| `MOVE` | 不适用 | `null` |

### 语义边界：只提取"已发生"的行为

| 表述 | 处理 | 理由 |
|---|---|---|
| 「我做好了一碗面」 | ✅ CREATE | 已完成行为 |
| 「我用了两个鸡蛋」 | ✅ CONSUME 2 | 已完成行为 |
| 「我把牛奶拿到桌上了」 | ✅ MOVE | 已完成行为 |
| 「我给你做鸡蛋卷」（承诺/未来） | ❌ 不提取 | 承诺 ≠ 事实；避免把"待做"当"已做" |
| 「有煎蛋卷和番茄汤」（状态声称） | ❌ 不提取 | 存在性声称不是动作（见架构 §12.2） |
| 「你想吃面吗？」 | ❌ 不提取 | 疑问句 |

> **可选增强（默认关闭）**：`v2_character_action_sync_llm_extract_enabled`。开启后新增一条**后台结构化提取链**（参照既有 `chains/extractor_chain.py` 的抽取模式），输入 `ai_reply` + 库存名集合 + 严格 schema，输出候选列表。无论哪个通道，产出**永远是 candidate**，裁决权在 ACTION-003。

## State Transition

本 Task 是纯提取，**不涉及状态迁移**（候选一律 `candidate`）。此处给出**句级决策级联**（用于测试覆盖）：

```text
句段
 ├─ 命中噪声守卫 ──────────────► 丢弃（不计入 note）
 ├─ 无动词命中 ────────────────► 丢弃
 ├─ 有动词但对象缺失（非 MOVE）─► 丢弃 或 low-confidence 候选（按配置）
 ├─ MOVE 且地点无法解析 ───────► 仍产出候选（由 ACTION-003 判 LOCATION_UNRESOLVED）
 └─ 完整命中 ──────────────────► 产出 candidate
```

## Error Handling

| 情形 | 处理 |
|---|---|
| 总闸关闭 | 立即返回空结果，零开销 |
| `ai_reply` 为空/非字符串 | 返回空结果 |
| 词表缺失/配置错误 | 异常被捕获 → 空结果 + trace error |
| 数量解析失败（"若干"） | 该候选丢弃或标 low confidence（按配置），不猜数量 |
| 对象名词无法匹配已知集合 | 丢弃（宁缺毋滥）；除非动词是明确 CREATE 且配置允许新名 |
| 时间/资源超限 | 设上限（如单轮 ≤ `max_actions_per_turn` 条），超出截断并 trace |
| 任何未预期异常 | **捕获 → 空结果**，绝不影响本轮回答（INV：聊天不因本模块失败） |

## Idempotency

- **确定性**：同一 `ai_reply` + 同一 `turn_ref` + 同一配置 → 提取结果**逐条一致**（无随机、无时间依赖）。
- **ordinal 稳定**：按句序与动词出现顺序编号，保证重放时 `dedupe_key` 一致。
- **无副作用**：提取阶段零写库，重复调用不产生任何状态变化。
- **与 ACTION-003 分工**：提取不做世界幂等判定（那是校验闸的职责）；提取只做**轮内字面去重**。

## Transaction Boundary

- 本 Task **只读**：读 `ai_reply` / `scene_state` / `WorldContext`；不开启事务、不写库。
- 运行于 `post_process` 的 per-user 写锁内（作为步骤），但自身不获取锁、不创建后台任务。
- 因此提取阶段**不产生不可回滚副作用**，为整体"整轮非原子但单步安全"提供保证。

## Observability

- 复用 `trace.record("character_action_sync", duration_ms, status, …)` 的汇总记录（见 ACTION-005）。
- 提取侧建议字段：`candidates`（条数）、`channel`、`skipped_reason`、逐条 `{action_type, target.name, quantity, confidence, evidence}`（经 `bound_extra` 有界）。
- 必须能回答：「本轮角色说了哪些可能的世界行为？为什么某句没被提取？」（证据片段 + 守卫类型）。

## Testing

| 类型 | 用例 |
|---|---|
| Unit（表驱动） | 动词表全覆盖：每类 ≥ 3 动词 × 有/无数量 × 有/无地点 |
| Unit（守卫） | 疑问 / 假设 / 未来 / 复述 / 否定 / 角色扮演 各 ≥ 3 例，断言零提取 |
| Unit（数量） | 中文数字（一/两/二/三/十）、阿拉伯数字、缺省规则 |
| Integration | 复现审查报告原句：「我用了两个鸡蛋」→ 1 条 CONSUME qty=2；「我做好了一碗面」→ 1 条 CREATE |
| 语义边界 | 「我给你做鸡蛋卷」/「有番茄汤」→ 零提取 |
| Determinism | 同输入跑 100 次结果逐条一致 |
| FailureInjection | 词表损坏 / 空回复 / 超长回复 → 空结果且不抛异常 |
| Performance | 单轮提取 P95 < 5ms（纯字符串规则） |

## Acceptance Criteria

1. 给定「我用了两个鸡蛋」，提取出 `CONSUME 鸡蛋 quantity=2`（含 evidence span）。
2. 给定「我做好了一碗面」，提取出 `CREATE 面`（数量缺省 1）。
3. 给定「我把牛奶拿进厨房」，提取出 `MOVE 牛奶`，地点解析为 `home.kitchen`。
4. 给定疑问句 / 假设句 / 未来意愿句 / 复述句，提取结果为空。
5. 提取阶段的可观测写入为 0（无 DB 写入、无 trace 之外的副作用）。
6. 关闭总闸时，提取入口零执行且返回空结果。

## Implementation Constraints

- **不新增前台 LLM 调用**；LLM 提取通道仅后台、默认关闭、计入日预算。
- 提取器**不得 import 世界写入模块**（`world_engine` 的写函数）；只允许只读获取 `WorldContext` / `SceneState`。
- 词表属角色资产（`app/character/asuna/`），逻辑属 `app/services/`（沿 `character/asuna/action.py` ↔ `services/action/detector.py` 的既有分工）。
- 不修改解释器（`interpreter.py`）与 V9 检出器（`detector.py`）。
- 所有输出必须**有界**（条数上限 + evidence 长度上限）。
- 不添加代码注释，用命名表达意图（`AGENTS.md`）。
