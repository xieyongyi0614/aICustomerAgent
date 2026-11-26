# CHAR-002 · Emotion Expression 映射与转移轨迹投影

## Task Overview

### 为什么需要

情绪系统当前是「算得出、说不出」。`state_engine.update_emotion` / `apply_emotion_decay` 已经在后台正确地更新了 `character_state` 的 `mood` + `intensity`（含惯性、速率钳制、衰减），但存在两个缺口：

1. **表达侧断层**：情绪数值更新后，PromptBuilder 只是把 `心情：worried（强度 0.5）` 这种**原始数值**贴进 prompt，没有翻译成「应该怎么表达」——`channel_bias`（动作/语言/平衡）、`tone_directive`（语气指令）、`expression_intensity`（情绪表达强度）这三个表达维度没有显式的确定性映射。
2. **转移不可见**：情绪从 `calm` 切到 `worried` 的这个「转移轨迹」只存在于 `state_engine` 的内部计算中，没有暴露为可读投影，导致无法回答「她为什么突然变得关切」、无法写入 `style_hint` 与 trace。

### 解决什么问题

- 把「情绪状态」翻译为「情绪表达约束」（`EmotionExpression`），让情绪真正**决定这句话怎么说**。
- 把情绪的「转移 + 衰减」显式暴露为可读轨迹（`describe_transition`），支撑可解释性与审计。

## Architecture Position

```text
character_state (SoT)
        ↓ 只读
state_engine.update_emotion / apply_emotion_decay (既有数学，不改)
        ↓ 读结果
CHAR-002 build_emotion_expression / describe_transition (本 Task)
        ↓ 产出 EmotionExpression
StyleContract.emotion_constraint (CHAR-001)
        ↓
CHAR-006 装配 → CHAR-007 prompt 注入
```

- **上游**：`character_state`（情绪 SoT）与 `state_engine`（既有情绪数学）。
- **下游**：`EmotionExpression` 填入 `StyleContract`。
- **边界**：是 State 域的**读侧翻译层**，绝不写回情绪数值。

## Responsibility

**负责：**
- 定义「mood + intensity → EmotionExpression」的确定性映射（查表 + 分档）。
- 提供「情绪转移前后 → 可读轨迹文本」的描述函数。
- 新建 `character/asuna/emotion_expression.py` 资产（8 个 mood 的 `tone_directive` / `channel_bias` 表）。

**不负责：**
- **不改 `state_engine` 的任何情绪数学与衰减数学**（`update_emotion` / `apply_emotion_decay` / `apply_idle_recovery` 原样保留）。
- 不写回 `character_state`（写回走既有 `state_service` 通道）。
- 不读关系数值（`relationship_emotion_boost` 由 CHAR-004 单向注入，本 Task 不反向依赖）。
- 不做情绪事件识别（`EmotionEvent` 识别属既有 `TurnAnalysis` 链，本 Task 只消费其结果）。

## Data Model

### 纯函数 + 配置资产，零新表

| 项 | 类型 | 说明 |
|---|---|---|
| `EmotionExpression` | 值对象（CHAR-001 定义） | 产出物，不落表 |
| `EMOTION_EXPRESSION_TABLE` | 配置常量（`character/asuna/emotion_expression.py`） | 8 mood → (channel_bias, tone_directive) 查表 |
| `describe_transition` 返回值 | `str` | 轨迹文本，随 trace 记录 |

### 资产表设计（`EMOTION_EXPRESSION_TABLE`）

| mood | channel_bias | tone_directive（示意，实现期润色） |
|---|---|---|
| happy | balanced | 语气轻快、带着笑意 |
| calm | balanced | 语气平和、自然 |
| worried | verbal | 语气柔和、先倾听不急着给建议 |
| sad | verbal | 语气放软、共情地陪伴 |
| shy | verbal | 语气轻声、略带不好意思 |
| excited | balanced | 语气活泼、有感染力 |
| tired | verbal | 语气温柔、带着一点疲惫感 |
| angry | balanced | 语气克制、说事实不说气话 |

> 关键约束：`channel_bias` 沿用 `behavior_strategy.py` 的 `ExpressionChannel`（action/verbal/balanced）枚举；`tone_directive` ≤ 30 字（受 CHAR-001 `Field` 约束）。

### 强度分档（复用 PromptBuilder 既有 tier 逻辑）

| intensity | expression_intensity |
|---|---|
| ≤ 0.3 | subtle（克制） |
| ≤ 0.6 | natural（自然） |
| > 0.6 | rich（放开） |

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `build_emotion_expression(character_state) -> EmotionExpression` | 纯函数 | mood 查表得 channel_bias/tone_directive；intensity 分档得 expression_intensity |
| `describe_transition(before, after) -> str` | 纯函数 | 对比前后 mood/intensity，产出「calm → worried（0.3→0.55）」或「worried 强度 0.3→0.55」 |
| `EMOTION_EXPRESSION_TABLE` | 配置资产 | 8 mood 的表达映射表（Persona 声明，裁决 Q1） |

## Runtime Flow

```text
本轮用户消息
    ↓
既有 TurnAnalysis 产出 EmotionEvent（已有，本 Task 不碰）
    ↓
既有 state_engine.update_emotion 计算 before→after（已有，本 Task 只读）
    ↓
CHAR-002：
    before / after 传入 describe_transition → 轨迹文本（供 style_hint / trace）
    after.mood + after.intensity 传入 build_emotion_expression → EmotionExpression
    ↓
EmotionExpression 填入 StyleContract.emotion_constraint
    ↓
CHAR-006 装配 → CHAR-007 注入 prompt
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat** | 无直接集成 | 经 CHAR-006/007 进入 prompt；本 Task 不碰 `answer_chain` |
| **Memory** | 无 | 情绪不读记忆 |
| **Reflection** | 无 | 不产/不读 Insight |
| **Autonomy / Decision** | 无 | 表达切面正交 |
| **State（state_engine）** | **只读** | 读 `update_emotion` 结果；**零改动**，写回走 `state_service` |
| **Relationship（CHAR-004）** | **接收单向注入** | 消费 `relationship_emotion_boost(stage)` 调制 `expression_intensity` 上限，但本 Task 不 import 关系数值 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| `character_state` 为默认值（calm/0.3） | 查表 + 分档返回 `calm` + `subtle`，不抛错 |
| `mood` 出现未知值 | 兜底 `balanced` + 空 `tone_directive`（防御式 `get`），不抛错 |
| `intensity` 边界值 0 / 1 | 分别落 `subtle` / `rich`，闭区间处理 |
| `before == after`（无变化） | `describe_transition` 返回「情绪平稳」或空描述，不伪造变化 |
| 跨情绪切换 vs 同情绪强度变化 | `describe_transition` 两种情况都给出可读文本 |
| 强情绪（intensity ≥ 0.8） | 仅影响 `expression_intensity=rich`，**不**改变 channel_bias（与 `behavior_engine` 的 budget 归零逻辑无关，本 Task 不重复实现） |

## Implementation Plan

1. **Step 1**：新建 `app/character/asuna/emotion_expression.py`，定义 `EMOTION_EXPRESSION_TABLE`（8 mood 全覆盖）。
2. **Step 2**：新建 `app/services/experience/emotion_expression.py`，实现 `build_emotion_expression` 与 `describe_transition` 两个纯函数。
3. **Step 3**：编写单测（8 mood 映射、3 分档边界、transition 两种形态、越界防御），确认 `state_engine` 既有测试全绿、`pylint` 不降级。

## Acceptance Criteria

- [ ] 8 个 mood 各自产出确定性 `EmotionExpression`（`tone_directive` 非空、`channel_bias` 合法）。
- [ ] `intensity` 三分档正确（0.3/0.6 边界），边界值 0/1 落正确档位。
- [ ] `describe_transition` 对「同情绪强度变化」与「跨情绪切换」均产出可读文本；无变化时输出稳定。
- [ ] 未知 mood / 越界 intensity 走防御兜底，不抛错。
- [ ] 不修改 `state_engine.py` 任何函数；`update_emotion` 行为回归不变。
- [ ] 单测覆盖：8 mood、3 档位、transition 两形态、防御分支。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
