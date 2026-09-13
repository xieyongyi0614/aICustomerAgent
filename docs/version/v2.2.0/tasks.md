# V2.2.0 Tasks

> 上游：`docs/version/v2.2.0/architecture.md`
> 定位：把散落在 behavior_engine / state_engine / PromptBuilder 中的体验信号，收敛为一个统一的 `StyleContract` 装配层，并补齐情绪转移轨迹、关系→表达档位、人格结构化三类真正缺失的运行时能力
> 拆解原则：每个 Task 可独立 Coding + 独立测试（纯函数优先，0 额外 LLM）；不新建 Chat Pipeline / Runtime / Memory / Workflow Engine；不重写情绪衰减与关系数学

---

## 依赖关系总览

```text
CHAR-001 (StyleContract 数据模型)
   ├── CHAR-002 (Emotion Expression 映射)  ← 读 character_state + 既有 update_emotion
   ├── CHAR-003 (Personality Profile 结构化)  ← 读 Persona 资产 + personality_state(可选)
   ├── CHAR-004 (Relationship Addressing)  ← 读 relationship_state 快照 + lexicon 扩展
   └── CHAR-005 (Habit Runtime 触发)  ← 读 HabitRule 清单 + 本轮情境
            │
            ▼
CHAR-006 (Style Contract 装配 + 冲突消解)  ← 依赖 002/003/004/005
            │
            ▼
CHAR-007 (PromptBuilder 集成 + Flag 灰度)  ← 依赖 006
```

关键裁决（来自 architecture §附 Q1~Q6，拆分前已定）：
- **Q1** 情绪转移矩阵归属 → 按 Persona 声明（配置期资产，放 `character/asuna/`）。
- **Q2** `style_contract_records` → **不建表**，复用 `runtime_traces` 记录 StyleContract。
- **Q3** Addressing 阈值 → 规则常量起步（`character/asuna/` 资产），纳入评估回归观察。
- **Q4** 习惯冲突消解 → 「更具体条件优先 + 域顺序（relate>express>pace）兜底」。
- **Q5** style 段与 behavior_ctx → **并列新增 style 段**，behavior_ctx 保留不动。
- **Q6** Experience 与 Decision 顺序 → 独立纯函数，由调用方串行调用，失败降级为「无契约仍可回复」。

---

## CHAR-001
**Priority:** P0（全部 Task 的数据底座，最先落地）

**Goal:**
定义 `StyleContract` 及其子结构的纯数据模型（Pydantic），作为 Experience Layer 各组件产出的统一值对象，但不实现任何装配逻辑。

**Description:**
新建 `app/models/style_contract.py`，定义：
- `Addressing`：`term`（称呼档）/ `tone`（语气档）/ `initiative`（主动程度档）/ `emotion_expressiveness`（情绪表达档）四个枚举 + 各自文案。
- `EmotionExpression`：`channel_bias`（action/verbal/balanced）/ `tone_directive`（语气指令）/ `expression_intensity`（subtle/natural/rich）。
- `PersonalityModulation`：`assertiveness` / `warmth` / `curiosity` / `patience` 四个 float（0..1，含 baseline/current/bound 语义字段）。
- `TriggeredHabit`：`rule_id` / `priority` / `instruction`。
- `StyleContract`：聚合上述 + `forbidden: list[str]` + `principles: list[str]` + `style_hint: str`。

沿用 `app/models/behavior_strategy.py` 的枚举风格（`Literal` + 默认值 + `Field` 约束），保证与既有 `BehaviorDirective` 可共存。**不落表、不写 IO、不调 LLM**——纯数据定义。可提供 `prompt_lines() -> list[str]` 与 `style_hint` 的生成（纯文本拼装），供后续 Task 复用。

**Dependencies:** 无（仅依赖既有 `pydantic`）。

**Acceptance Criteria:**
- 新文件 `app/models/style_contract.py` 可 import，`StyleContract` 可实例化且带默认值。
- 所有枚举字段非法值会被 Pydantic 拒绝（`Literal` 校验）。
- `prompt_lines()` 输出为可注入 prompt 的纯文本列表，无花括号转义问题。
- 不引入任何数据库表、任何 LLM 调用、任何对既有域服务的 import。
- 配套单测覆盖：默认构造、各字段合法/非法、`prompt_lines`/`style_hint` 输出稳定。

---

## CHAR-002
**Priority:** P1

**Goal:**
实现「情绪 → 表达约束」的确定性映射（`EmotionExpression`），并把既有 `state_engine.update_emotion` 的情绪转移/衰减结果显式暴露为可读的运行时投影，供 StyleContract 消费。

**Description:**
新建 `app/services/experience/emotion_expression.py`（或并入既有 experience 包），提供纯函数：
- `build_emotion_expression(character_state) -> EmotionExpression`：把 `character_state` 的 `mood` + `intensity` 映射为 `channel_bias` / `tone_directive` / `expression_intensity`。
  - `expression_intensity` 由 `intensity` 阈值分档（复用 PromptBuilder.build_emotion_section 已有的 tier 逻辑：≤0.3 subtle / ≤0.6 natural / >0.6 rich）。
  - `channel_bias` 与 `tone_directive` 由 `mood` 查表（新建 `character/asuna/emotion_expression.py` 资产，8 个 mood 各给 tone_directive）。
- `describe_transition(before: CharacterState, after: CharacterState) -> str`：对比 `state_engine.update_emotion` 前后值，产出「calm → worried（0.3→0.55）」这类可读轨迹文本，供 `style_hint` 与 trace 使用。

**铁律**：**不改 `state_engine` 的情绪数学与衰减数学**，只读其结果。`update_emotion` / `apply_emotion_decay` 原样保留，本 Task 只做「读 + 翻译」。

**Dependencies:** CHAR-001（消费 `EmotionExpression` 模型）；读 `app/services/state_engine.py`（只读）、`app/models/character_state.py`、新建 `app/character/asuna/emotion_expression.py` 资产。

**Acceptance Criteria:**
- 8 个 mood 各自能产出确定性的 `EmotionExpression`（tone_directive 非空、channel_bias 合法）。
- `intensity` 三分档映射正确（0.3/0.6 边界）。
- `describe_transition` 对「同情绪强度变化」与「跨情绪切换」两种情况都产出可读文本。
- 不修改 `state_engine.py` 任何既有函数；`update_emotion` 行为回归不变（既有测试全绿）。
- 单测覆盖：8 mood 映射、3 intensity 档位、transition 描述、边界值（intensity=0/1）。

---

## CHAR-003
**Priority:** P1

**Goal:**
把 `identity.py` / `personality.py` 的静态人格文本，升级为结构化的 `PersonalityProfile`（核心人格/行为偏好/语言风格/禁止项/原则），并叠加 V2.1.0 `personality_state` 轴做 `PersonalityModulation`。

**Description:**
1. 新建 `app/character/asuna/personality_profile.py` 资产：结构化 `PersonalityProfile`（`core_traits` / `behavior_preferences` / `language_style` / `forbidden_behaviors` / `principles`），内容从既有 `identity.py` 与 `personality.py` 文本**语义等价迁移**，不改原语义。
2. 新建 `app/services/experience/personality_modulation.py`：纯函数 `build_personality_modulation(profile, personality_state=None) -> PersonalityModulation`：
   - 无 `personality_state` 时，返回 Persona 基线导出的默认轴值（assertiveness/warmth/curiosity/patience 各给基线常量）。
   - 有 `personality_state`（V2.1.0 演化轴）时，在 `bound` 内叠加到 baseline（读侧，不写回）。
   - 输出 `forbidden` / `principles` 直接来自 Profile（硬约束，不可被调制稀释）。

**铁律**：人格静态资产（identity.py / personality.py）**原样保留**，Profile 是新增的**结构化投影**，不删除、不修改原文件（沿「Persona 不可写回」）。`personality_state` 仅读，演化写回仍走 Evolution Engine。

**Dependencies:** CHAR-001（消费 `PersonalityModulation`）；读 `identity.py` / `personality.py` / `personality_state`（可选，需 Flag `v21_personality_evolution_enabled` 未开启时跳过读）。

**Acceptance Criteria:**
- `PersonalityProfile` 五类字段齐全，且与 `identity.py`/`personality.py` 语义一致（对照表可验证）。
- 无演化轴时返回确定性默认调制；有轴时叠加结果被 `bound` 钳制。
- `forbidden` / `principles` 在任何情况下非空且不被轴调制稀释。
- 不修改、不删除既有 `identity.py` / `personality.py`。
- 单测覆盖：默认调制、轴叠加、bound 钳制、硬约束恒在。

---

## CHAR-004
**Priority:** P1

**Goal:**
在 V8.5 关系数值引擎之上，实现「关系快照 → 称呼/语气/主动/情绪表达」四维表达档的确定性映射（`Addressing`），并处理冲突状态覆盖。

**Description:**
1. 扩展 `app/character/asuna/relationship_lexicon.py`（**只增不改既有键**）：新增称呼档词表（`TERM_BY_STAGE`）、语气档文案、主动程度文案、情绪表达档文案，沿用既有 `describe_respect` / `describe_comfort` 的分档风格。
2. 新建 `app/services/experience/relationship_addressing.py`：纯函数 `build_addressing(relationship_state) -> Addressing`：
   - 读 `stage` + 关键维度（`intimacy` / `familiarity` / `comfort`）阈值，映射四维档位（阈值常量起步，见裁决 Q3）。
   - `conflict_status` 覆盖：`strain`/`conflict`/`cold`/`recovery` 临时压低 `tone` 与 `initiative`（复用既有 `CONFLICT_DIRECTIVES`），冲突期优先于常规档位。
   - 提供 `relationship_emotion_boost(stage) -> float` 单向调制（亲密阶段允许更高 `expression_intensity`），供 CHAR-002 消费，但**情绪不反向读关系数值**。

**铁律**：**不新增任何关系数学**。D1/D2/D3/D5、里程碑、冲突状态机零改动；只读 `relationship_state` 投影做翻译。

**Dependencies:** CHAR-001（消费 `Addressing`）；读 `app/models/relationship.py`、扩展 `relationship_lexicon.py`。

**Acceptance Criteria:**
- 四个 stage（stranger/friend/close_friend/partner）各自产出确定性的四维 `Addressing`，且随 stage 递进单调变化（称呼更亲、语气更亲昵、更主动、情绪表达更放开）。
- `conflict_status` 非 none 时，`tone`/`initiative` 被压低，且优先于常规档位。
- 不修改 `relationship.py` 模型与任何关系引擎/账本代码；既有关系测试全绿。
- `relationship_emotion_boost` 输出被钳制在合法范围，且不反向读情绪。
- 单测覆盖：四 stage 映射、维度阈值边界、conflict 覆盖、boost 范围。

---

## CHAR-005
**Priority:** P1

**Goal:**
实现习惯的**运行时触发判定 + 优先级合成**，把静态 `HabitRule` 清单升级为「本轮命中哪些习惯」的确定性机制，输出 `TriggeredHabit` 列表。

**Description:**
新建 `app/services/experience/habit_trigger.py`：纯函数 `trigger_habits(context) -> list[TriggeredHabit]`：
- 输入 `context`：本轮 `TurnAnalysis`（含 emotion_event / behavior / relationship_event）+ 关系 `conflict_status` + 话题关键词。
- 对 `HABIT_LIST`（复用 `habit_runtime.load_effective_habits()`）做**规则匹配**（关键词/情境标签，0 LLM），筛出命中的 `HabitRule`。
- **优先级合成**：按 `priority` 排序；同优先级冲突按「更具体条件优先 + 域顺序（relate>express>pace）兜底」（裁决 Q4）择优，上限 `HABIT_MAX_COUNT`（复用既有常量 2）。
- 输出 `TriggeredHabit`（rule_id/priority/instruction），**不硬编码回复文本**——只给行为指令。

**与既有 `behavior_engine.match_habits` 的边界**：`match_habits` 是「按 strategy 的 domain 适用性筛选 + 去重」，本 Task 的 `trigger_habits` 是「按本轮情境触发 + 冲突消解」。两者**并存**，本 Task 不改 `match_habits`；`trigger_habits` 的输出作为 StyleContract 的独立习惯来源（裁决 Q4/Q5）。

**Dependencies:** CHAR-001（消费 `TriggeredHabit`）；读 `habit_runtime.py`（只读 `load_effective_habits`）、`habits.py`、`TurnAnalysis`。

**Acceptance Criteria:**
- 对「用户工作累」情境能命中 `habit_comfort_companion_first` 等确定性习惯，且命中结果稳定。
- 同优先级冲突时消解规则确定（不依赖遍历顺序、无随机性）。
- 命中数量 ≤ `HABIT_MAX_COUNT`，且不硬编码任何回复句子。
- 不修改 `behavior_engine.match_habits` 与 `habit_runtime.py` 的既有函数（仅新增调用）。
- 单测覆盖：单习惯命中、多习惯优先级排序、同优先级冲突消解、无命中返回空。

---

## CHAR-006
**Priority:** P0（装配中枢，依赖前四个组件）

**Goal:**
实现 `StyleContract` 的装配中枢：把 Emotion / Personality / Relationship / Habit 四路投影，按固定优先级合成一个可解释、可回放的 `StyleContract`。

**Description:**
新建 `app/services/experience/style_assembler.py`：纯函数 `assemble_style_contract(state, analysis, personality_state=None) -> StyleContract`：
1. 分别调用 CHAR-002/003/004/005 的纯函数，得到 `EmotionExpression` / `PersonalityModulation` / `Addressing` / `TriggeredHabit`。
2. **约束合并优先级**（architecture §5.5）：硬约束（forbidden/principles）> 情绪 > 关系档位 > 人格调制 > 习惯。
   - 冲突消解：硬约束永不妥协；情绪与关系档位冲突时情绪优先（当下感受>关系礼貌）；人格调制与习惯冲突时人格基线优先。
3. 生成 `style_hint`（一句话摘要，如「温柔地、关切地、先倾听后建议」），供调试与 trace。
4. 全程规则/查表，**0 额外 LLM**；任何子组件异常时降级为「最小契约」（仅硬约束 + 空习惯），保证不阻塞回复。

**Dependencies:** CHAR-001~005。

**Acceptance Criteria:**
- 给定一个 `ConversationState` + `TurnAnalysis`，能产出完整的 `StyleContract`，字段齐全。
- 冲突消解符合优先级（构造冲突用例可验证：情绪优先于关系档位、硬约束恒在）。
- 任一子组件抛异常时，返回最小契约而非抛错（降级语义）。
- `style_hint` 非空且可读。
- 全流程 0 LLM 调用（无 `get_llm` / chain import）。
- 单测覆盖：正常装配、冲突消解各分支、子组件异常降级。

---

## CHAR-007
**Priority:** P0（落地接线，依赖装配中枢）

**Goal:**
把 `StyleContract` 接入 `PromptBuilder`，以新增 `style` 段注入 prompt，并用 Flag 灰度控制整体开关与各子闸。

**Description:**
1. **PromptBuilder 集成**：`PromptBuilder.build()` 新增可选参数 `style_ctx: StyleContract | None`；当非空时，在 `state_sections` 之后新增一个 `("system", build_style_section(style_ctx))` 段（新建 `build_style_section`，产出「【本轮表达风格】+ 称呼/语气/情绪表达/习惯指令/禁止项」的紧凑文本，遵循既有 `_literal` 转义 + 字符预算惯例）。
   - **behavior_ctx 保留不动**（裁决 Q5），style 段与之并列。
2. **调用方接线**：在 `answer_chain.astream` / `build_chain` 的调用点（或 chat pipeline 装配处）构造 `style_ctx`（先调 CHAR-006 的 `assemble_style_contract`），传入 PromptBuilder；失败时传 `None`，降级为「无风格契约仍可回复」（裁决 Q6）。
3. **Flag 灰度**：在 settings 新增 `v22_experience_enabled` 总闸 + `v22_emotion_transition_enabled` / `v22_relationship_addressing_enabled` / `v22_habit_runtime_enabled` / `v22_style_contract_enabled` 子闸（沿用 v2.1 的 `_shared.py` + domain settings 惯例），总闸+子闸双开才生效，关闭后行为与 V2.1.0 逐字节一致。
4. **trace 记录**：StyleContract 随 `runtime_traces` 记录（复用既有 `trace.record`，不建新表，裁决 Q2）。

**Dependencies:** CHAR-006；读 `prompts/builder.py`、`chains/answer_chain.py`、`core/settings/`。

**Acceptance Criteria:**
- Flag 关闭时，PromptBuilder 输出与 V2.1.0 逐字节一致（回归断言）。
- Flag 开启且 style_ctx 非空时，prompt 出现「本轮表达风格」段且包含称呼/语气/习惯/禁止项。
- style_ctx 构造失败时降级为 None，回复链路不中断。
- 不新建数据库表；StyleContract 记录进 trace。
- 既有 chat 链路回归测试全绿；新增集成测试覆盖 Flag on/off 两条路径。

---

## 附：拆分后仍需评审的遗留项

| # | 项 | 说明 |
|---|---|---|
| R1 | `style_hint` 是否进入调试控制台展示 | 依赖前端控制台，本版本可先只进 trace，后续接 |
| R2 | Addressing 阈值常量的最终数值 | CHAR-004 以常量起步，需一轮真实模型回归后调参 |
| R3 | `PersonalityProfile` 默认轴值（assertiveness/warmth/...）的初始取值 | CHAR-003 需与角色设定对齐，避免默认值失真 |
| R4 | `build_style_section` 的字符预算 | 需与 `context_total_char_budget` 协调，避免挤占记忆/历史预算 |
