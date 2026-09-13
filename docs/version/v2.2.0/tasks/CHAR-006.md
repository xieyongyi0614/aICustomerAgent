# CHAR-006 · StyleContract 装配中枢与冲突消解

## Task Overview

### 为什么需要

CHAR-002~005 各自产出了独立的约束片段（`EmotionExpression` / `PersonalityModulation` / `Addressing` / `TriggeredHabit`），但它们是**散落的、相互之间可能矛盾**的：

1. **无统一汇流**：四路信号没有汇聚成一个完整契约，调用方（CHAR-007）无法一次性拿到「这一句该怎么说的全部约束」。
2. **无冲突消解**：情绪说「先倾听」（worried），关系档说「主动关心」（partner + proactive），人格说「耐性高」（建议后置）——三者叠加时谁优先？没有统一的裁决规则就会产生内部矛盾。
3. **无降级兜底**：任一子组件异常时，不能让整个回复链路中断。

### 解决什么问题

- 实现 `StyleContract` 的**装配中枢**：四路投影 → 一个完整、自洽、可解释的契约。
- 实现**固定优先级的冲突消解**（硬约束 > 情绪 > 关系档位 > 人格调制 > 习惯）。
- 实现**降级兜底**（最小契约），保证永不阻塞回复。

## Architecture Position

```text
CHAR-002 EmotionExpression ──┐
CHAR-003 PersonalityModulation┤
CHAR-004 Addressing ──────────┤
CHAR-005 TriggeredHabit ──────┘
        ↓ 装配 + 冲突消解
CHAR-006 assemble_style_contract (本 Task，Experience Layer 中枢)
        ↓ 产出完整 StyleContract
CHAR-007 PromptBuilder 注入 (下游)
```

- **上游**：CHAR-002~005 四个纯函数组件。
- **下游**：`StyleContract`（CHAR-001 定义）交给 CHAR-007。
- **边界**：是 Experience Layer 的**装配编排点**，纯函数、无 IO、0 额外 LLM。

## Responsibility

**负责：**
- 调用四个子组件，聚合为完整 `StyleContract`。
- 按固定优先级做**冲突消解**（见下）。
- 生成 `style_hint` 一句话摘要。
- 任一子组件异常时降级为最小契约。

**不负责：**
- 不做任何情绪/关系/人格/习惯的**底层计算**（那是 CHAR-002~005 的职责）。
- 不做 prompt 文本注入与预算控制（那是 CHAR-007 的职责）。
- 不落库、不调 LLM、不写任何域状态。
- 不处理 `style_ctx` 的 Flag 开关（Flag 由 CHAR-007 在调用方控制）。

## Data Model

### 纯函数，零新表

| 项 | 类型 | 说明 |
|---|---|---|
| `StyleContract` | 值对象（CHAR-001 定义） | 产出物，不落表 |
| `assemble_style_contract(state, analysis, personality_state=None)` | 纯函数 | 装配入口 |
| `_resolve_conflicts(...)` | 私有纯函数 | 冲突消解 |

### 冲突消解优先级（architecture §5.5）

| 优先级 | 约束来源 | 冲突时行为 |
|---|---|---|
| 1（最高） | 硬约束 forbidden / principles | **永不妥协**，任何情况保留 |
| 2 | 情绪 EmotionExpression | 情绪与关系档位冲突时，**情绪优先**（当下感受 > 关系礼貌） |
| 3 | 关系档位 Addressing | 让位于情绪 |
| 4 | 人格调制 PersonalityModulation | 人格与习惯冲突时，**人格基线优先**（习惯在人格边界内生效） |
| 5（最低） | 习惯 TriggeredHabit | 让位于人格 |

### 冲突消解的具体落点

- **情绪 vs 关系档位**：当 `EmotionExpression.expression_intensity` 与 `Addressing.emotion_expressiveness` 不一致时，最终 `expression_intensity` 取**情绪优先**（但可受 CHAR-004 的 `relationship_emotion_boost` 单向抬升上限，见 CHAR-004 契约）。
- **人格 vs 习惯**：当某条 `TriggeredHabit.instruction` 与 `PersonalityModulation` 的轴方向矛盾（如习惯「先给建议」但 patience 高「建议后置」），以人格轴方向为准，弱化该习惯指令（或降其优先级）。
- **硬约束恒在**：`forbidden` / `principles` 不参与任何「稀释」，直接透传。

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `assemble_style_contract(state, analysis, personality_state=None)` | 纯函数 | 调四子组件 → 冲突消解 → 产出 StyleContract + style_hint |
| `_resolve_expression_intensity(emotion, addressing, boost)` | 纯函数 | 情绪/关系表达强度冲突消解 |
| `_resolve_habit_vs_personality(habits, modulation)` | 纯函数 | 习惯与人格轴冲突消解 |
| `_minimal_contract(forbidden, principles)` | 纯函数 | 降级兜底（最小契约） |

## Runtime Flow

```text
每轮 Run（前台表达切面）：
    ↓
assemble_style_contract(state, analysis, personality_state)
    ↓
① 调 CHAR-002 build_emotion_expression(state.character_state)
② 调 CHAR-003 build_personality_modulation(profile, personality_state)
③ 调 CHAR-004 build_addressing(state.relationship_state)
④ 调 CHAR-005 trigger_habits(context)
    ↓
⑤ 冲突消解：
     硬约束恒在 → 情绪 vs 关系档(情绪优先) → 人格 vs 习惯(人格优先)
    ↓
⑥ 生成 style_hint
    ↓
⑦ 任一子组件异常 → 降级为 _minimal_contract(仅硬约束 + 空习惯)
    ↓
返回完整 StyleContract
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat** | 无直接集成 | 产出交给 CHAR-007 |
| **Memory** | 无 | 装配层不读记忆 |
| **Reflection** | 无 | 不产/不读 Insight |
| **Autonomy / Decision** | 无 | 表达切面正交；装配不干预决策 |
| **CHAR-002~005** | 编排调用 | 唯一上游，纯函数调用 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| 任一子组件抛异常 | 捕获，降级为最小契约（仅硬约束 + 空习惯），不向上抛 |
| 情绪与关系档冲突 | 情绪优先（`expression_intensity` 取情绪档，可受 boost 抬升） |
| 习惯与人格轴冲突 | 人格基线优先，弱化冲突习惯指令 |
| 硬约束为空（理论极端） | 最小契约仍保留默认硬约束（防御），不产生「无约束」契约 |
| 四路信号全为默认值 | 产出「自然」风格的最小有效契约，`style_hint` 可读 |
| `personality_state` 为 None | 正常，CHAR-003 走默认基线 |

## Implementation Plan

1. **Step 1**：新建 `app/services/experience/style_assembler.py`，实现 `assemble_style_contract` 主流程与三个消解/兜底纯函数。
2. **Step 2**：接入四个子组件纯函数，实现冲突消解与 `style_hint` 生成。
3. **Step 3**：编写单测（正常装配、冲突消解各分支、子组件异常降级、最小契约、style_hint 非空）。

## Acceptance Criteria

- [ ] 给定 `ConversationState` + `TurnAnalysis` 能产出完整 `StyleContract`，字段齐全。
- [ ] 冲突消解符合优先级（情绪优先于关系档、硬约束恒在、人格优先于习惯）。
- [ ] 任一子组件抛异常时返回最小契约而非抛错（降级语义）。
- [ ] `style_hint` 非空且可读。
- [ ] 全流程 0 LLM 调用（无 `get_llm` / chain import）。
- [ ] 单测覆盖：正常装配、冲突消解各分支、子组件异常降级、最小契约。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
