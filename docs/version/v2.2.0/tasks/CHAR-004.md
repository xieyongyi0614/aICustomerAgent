# CHAR-004 · Relationship Addressing（关系→表达档映射）

## Task Overview

### 为什么需要

关系六维数值引擎（V8.5）已经正确地在后台更新 `intimacy` / `trust` / `familiarity` / `respect` / `comfort` / `tension`，但存在断层：

1. **数值不决定表达**：`relationship_state` 的数值在涨，但「这一句该用什么称呼、什么语气、主动到什么程度、情绪放得多开」没有显式映射。PromptBuilder 目前只把「亲密/信任/熟悉」的 `describe_level` 文本贴进 prompt，**称呼、语气、主动程度、情绪表达四维没有运行时档位**。
2. **词表覆盖不全**：`relationship_lexicon.py` 只覆盖了 `respect` / `comfort` 两维的文案，缺称呼档、语气档、主动程度、情绪表达档。

### 解决什么问题

- 实现「关系快照 → `Addressing` 四维表达档」的确定性映射，让关系阶段真正决定**怎么说**（解决 P3 长期关系感不足）。
- 补全关系词表，扩展 `relationship_lexicon.py` 的档位文案。

## Architecture Position

```text
relationship_state (SoT，V8.5 六维 + stage + conflict_status)
        ↓ 只读投影
CHAR-004 build_addressing / relationship_emotion_boost (本 Task)
        ↓ 产出 Addressing
StyleContract.addressing (CHAR-001)
        ↓
CHAR-006 装配 → CHAR-007 prompt 注入
```

- **上游**：`relationship_state`（关系 SoT）+ `relationship_lexicon.py`（词表资产）。
- **下游**：`Addressing` 填入 `StyleContract`；`relationship_emotion_boost` 单向注入 CHAR-002。
- **边界**：是 Relationship 域的**读侧翻译层**，**零新增关系数学**。

## Responsibility

**负责：**
- 定义「stage + 关键维度阈值 → `Addressing` 四维档」的确定性映射。
- 处理 `conflict_status` 对档位的覆盖（冲突期压低 tone/initiative）。
- 提供 `relationship_emotion_boost(stage) -> float` 单向调制（供 CHAR-002 用）。
- 扩展 `relationship_lexicon.py`（**只增不改既有键**）。

**不负责：**
- **不新增任何关系数学**（D1/D2/D3/D5、里程碑、冲突状态机零改动）。
- 不写关系数值（关系引擎自走）。
- 不读 Memory 原始事实（称呼/语气由数值驱动，不由记忆内容驱动）。
- 不做关系事件的产生与判定（属 V8.5 引擎）。

## Data Model

### 值对象 + 词表资产，零新表

| 项 | 类型 | 说明 |
|---|---|---|
| `Addressing` | 值对象（CHAR-001 定义） | 四维档（term/tone/initiative/emotion_expressiveness） |
| `TERM_BY_STAGE` 等词表 | 配置资产（扩展 `relationship_lexicon.py`） | 称呼/语气/主动/情绪表达档文案 |
| `relationship_emotion_boost` 返回值 | `float` | 0..1 单向调制系数 |

### 四维档位枚举（与 CHAR-001 `Addressing` 对齐）

| 维度 | 档位（递进） |
|---|---|
| `term` | respectful → name → affectionate → intimate |
| `tone` | polite → natural → warm → affectionate |
| `initiative` | passive → responsive → proactive → devoted |
| `emotion_expressiveness` | restrained → natural → open |

### 映射规则（阈值常量起步，裁决 Q3）

| stage | term | tone | initiative | emotion_expressiveness |
|---|---|---|---|---|
| stranger | respectful | polite | passive | restrained |
| friend | name | natural | responsive | natural |
| close_friend | affectionate | warm | proactive | natural |
| partner | intimate | affectionate | devoted | open |

> 维度微调：`close_friend` / `partner` 内部再按 `intimacy` / `familiarity` / `comfort` 阈值做细分（如 partner 且 comfort < 0.4 时 initiative 回调），实现「数值 → 档位」的连续过渡而非仅靠 stage 跳跃。

### conflict_status 覆盖（复用 `CONFLICT_DIRECTIVES`）

| conflict_status | 覆盖动作 |
|---|---|
| strain | tone 降一档、initiative 降一档 |
| conflict | tone 降两档、initiative 降一档 |
| cold | tone 降两档、initiative 降至 passive |
| recovery | tone 维持、initiative 维持（不进一步压低） |

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `build_addressing(relationship_state) -> Addressing` | 纯函数 | stage + 维度阈值 → 四维档；conflict 覆盖 |
| `relationship_emotion_boost(stage) -> float` | 纯函数 | 亲密阶段返回更高表达强度系数 |
| `TERM_BY_STAGE` / `TONE_TEXTS` 等 | 配置资产 | 档位文案（扩展 `relationship_lexicon.py`） |

## Runtime Flow

```text
每轮 Run：
    ↓
读取 relationship_state 快照（stage + 六维 + conflict_status）
    ↓
build_addressing：
    ① stage → 四维基础档
    ② intimacy/familiarity/comfort 阈值 → 维度微调
    ③ conflict_status → 覆盖 tone/initiative
    ↓
产出 Addressing → 填入 StyleContract
    ↓
relationship_emotion_boost(stage) → 单向注入 CHAR-002（调制 expression_intensity 上限）
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat** | 无直接集成 | 经 CHAR-006/007 进入 prompt |
| **Memory** | 无 | 称呼/语气由数值驱动，不读记忆内容 |
| **Reflection** | 无 | 不产/不读 Insight |
| **Autonomy / Decision** | 无 | 表达切面正交 |
| **Relationship（V8.5）** | **只读投影** | 读快照；数值/账本/引擎零改动 |
| **Emotion（CHAR-002）** | **单向注入** | 提供 `relationship_emotion_boost`，情绪不反向读关系数值 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| stage 为默认 friend 且维度为默认值 | 返回 friend 档，不抛错 |
| 维度在阈值边界（如 comfort=0.7 恰为分界） | 闭区间取上档（确定性，不依赖浮点误差） |
| conflict_status 为 none | 不覆盖，直接用常规档 |
| conflict_status 与 stage 冲突（如 stranger + conflict） | conflict 覆盖优先（冲突期表达优先于常规档） |
| 未知 stage / conflict_status | 防御兜底 friend / none，不抛错 |
| `relationship_emotion_boost` 越界 | 钳制到 0..1 |

## Implementation Plan

1. **Step 1**：扩展 `app/character/asuna/relationship_lexicon.py`，新增 `TERM_BY_STAGE`、语气档、主动程度、情绪表达档文案（**只增不改既有键**）。
2. **Step 2**：新建 `app/services/experience/relationship_addressing.py`，实现 `build_addressing` 与 `relationship_emotion_boost`。
3. **Step 3**：编写单测（四 stage 映射、维度阈值边界、conflict 覆盖、boost 范围、未知值防御），确认既有关系测试全绿。

## Acceptance Criteria

- [ ] 四 stage 各自产出确定性 `Addressing`，且随 stage 递进单调变化（更亲、更亲昵、更主动、更放开）。
- [ ] `conflict_status` 非 none 时 tone/initiative 被压低且优先于常规档。
- [ ] 不修改 `relationship.py` 模型与任何关系引擎/账本代码；既有关系测试全绿。
- [ ] `relationship_emotion_boost` 钳制在 0..1，不反向读情绪。
- [ ] `relationship_lexicon.py` 只增不改（既有 `describe_respect` / `describe_comfort` 等键不受影响）。
- [ ] 单测覆盖：四 stage、维度阈值边界、conflict 覆盖、boost 范围、未知值防御。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
