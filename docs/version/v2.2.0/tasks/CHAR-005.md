# CHAR-005 · Character Habit Runtime 触发与合成

## Task Overview

### 为什么需要

习惯目前是**静态清单**（`habits.py` 的 `HABIT_LIST` + `habit_runtime.py` 的候选生成/加载），但缺少「**本轮到底该触发哪些习惯**」的运行时判定：

1. **触发判定缺失**：`behavior_engine.match_habits` 只按「strategy 的 domain 适用性」筛选习惯（如 quiet_companion → relate/pace 域），**不判断「本轮情境是否真的命中了某条习惯的条件」**（如「用户在倾诉」才触发 `habit_listen_before_speak`）。
2. **优先级合成缺失**：多条习惯同时命中时，没有「同优先级冲突如何消解」的确定性规则。
3. **习惯不进 Character State**：习惯没有作为可查询的运行时状态暴露给 StyleContract。

### 解决什么问题

- 实现习惯的**运行时触发判定**（关键词/情境标签匹配，0 LLM），让习惯真正「在合适的情境出现」。
- 实现**优先级合成 + 冲突消解**，保证命中结果确定、不冗余。
- 把命中的习惯作为 `TriggeredHabit` 暴露给 StyleContract（解决 P4 缺个人习惯）。

## Architecture Position

```text
HABIT_LIST + habit_runtime.load_effective_habits() (既有，只读)
        ↓
本轮情境 (TurnAnalysis + conflict_status + 话题)
        ↓
CHAR-005 trigger_habits (本 Task)
        ↓ 产出 TriggeredHabit[]
StyleContract.habits (CHAR-001)
        ↓
CHAR-006 装配 → CHAR-007 prompt 注入
```

- **上游**：`HabitRule` 清单（`habit_runtime.load_effective_habits()`）+ 本轮情境。
- **下游**：`TriggeredHabit[]` 填入 `StyleContract`。
- **边界**：是 Persona 资产的**运行时触发层**，不产生新习惯事实，不硬编码回复。

## Responsibility

**负责：**
- 实现 `trigger_habits(context) -> list[TriggeredHabit]` 的触发判定（规则匹配，0 LLM）。
- 实现优先级排序 + 同优先级冲突消解（更具体条件优先 + 域顺序 relate>express>pace 兜底，裁决 Q4）。
- 命中数量上限 `HABIT_MAX_COUNT`（复用既有常量 2）。

**不负责：**
- **不修改** `behavior_engine.match_habits` 与 `habit_runtime.py` 既有函数（二者并存，`match_habits` 是 strategy 域筛选，本 Task 是情境触发）。
- 不产生新习惯、不写习惯清单（习惯清单是配置期资产，候选生成/审核仍是 `habit_runtime` 职责）。
- 不硬编码回复文本（只给 `instruction` 行为指令，措辞由 LLM 在契约内生成）。
- 不读 Memory（`habit_memory_light_touch` 仅以「是否提及记忆」为信号，不直接驱动措辞）。

## Data Model

### 纯函数，零新表

| 项 | 类型 | 说明 |
|---|---|---|
| `TriggeredHabit` | 值对象（CHAR-001 定义） | rule_id/priority/instruction |
| `HabitTriggerContext` | 输入值对象（本 Task 定义） | 本轮情境：emotion_event/behavior/relationship_event/conflict_status/话题关键词 |
| `TRIGGER_RULES` | 配置常量（`character/asuna/habit_triggers.py`） | 习惯 id → 触发条件（关键词/情境标签） |

### 触发规则设计（`TRIGGER_RULES`，示意）

| 习惯 id | 触发条件（情境标签） |
|---|---|
| `habit_comfort_companion_first` | 用户情绪 tired/sad/worried 或事件 comforted/worrying_news |
| `habit_listen_before_speak` | 用户情绪正在展开（话题未完/倾诉信号） |
| `habit_question_bounded` | 需要向用户提问（curious_inquiry / ask_followup） |
| `habit_care_action_first` | 关心/照顾情境（user_care / support） |
| `habit_angry_restrained` | 被冒犯/冲突（conflict / criticized） |
| `habit_happy_tease` | 开心/轻松（happy / funny_moment） |
| `habit_memory_light_touch` | 话题与用户过去提过的事相关（记忆提及信号） |

> 触发条件是**规则**（关键词/情境标签匹配），非 LLM；条件字段可复用既有 `HabitRule.condition` 文本，但判定逻辑在 `TRIGGER_RULES` 里显式化。

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `trigger_habits(context) -> list[TriggeredHabit]` | 纯函数 | 规则匹配触发 → 优先级排序 → 冲突消解 → 截断 |
| `HabitTriggerContext` | 值对象 | 聚合本轮触发所需信号 |
| `TRIGGER_RULES` | 配置资产 | 习惯 id → 触发条件 |

## Runtime Flow

```text
每轮 Run：
    ↓
收集 HabitTriggerContext（TurnAnalysis 的 emotion_event/behavior/relationship_event
                         + relationship_state.conflict_status + 话题关键词）
    ↓
trigger_habits：
    ① 遍历 load_effective_habits()，用 TRIGGER_RULES 匹配触发条件
    ② 命中习惯按 priority 升序排序
    ③ 同优先级冲突 → 更具体条件优先 + 域顺序(relate>express>pace)兜底
    ④ 截断到 HABIT_MAX_COUNT 条
    ↓
产出 TriggeredHabit[] → 填入 StyleContract.habits
    ↓
CHAR-006 装配 → CHAR-007 注入 prompt
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat** | 无直接集成 | 经 CHAR-006/007 进入 prompt |
| **Memory** | 弱信号 | `habit_memory_light_touch` 仅以「是否提及记忆」为触发信号，不读记忆内容 |
| **Reflection** | 无 | 不产/不读 Insight |
| **Autonomy / Decision** | 无 | 表达切面正交 |
| **Behavior（behavior_engine）** | **并存不冲突** | 不改 `match_habits`；`trigger_habits` 是独立的情境触发来源 |
| **Habit Runtime（habit_runtime）** | **只读复用** | 读 `load_effective_habits()`，不写清单 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| 本轮无任何习惯命中 | 返回空列表，不抛错 |
| 多条同优先级命中 | 冲突消解规则确定（不依赖遍历顺序） |
| 命中数超过上限 | 截断到 `HABIT_MAX_COUNT` 条 |
| 触发条件关键词同时命中多条 | 全部进入候选，再由优先级/消解规则收敛 |
| 生效习惯清单为空（`load_effective_habits` 返回空） | 返回空列表 |
| `context` 缺失某信号（如无 conflict_status） | 缺失信号对应规则不命中，不整体失败 |

## Implementation Plan

1. **Step 1**：新建 `app/character/asuna/habit_triggers.py`，定义 `TRIGGER_RULES` 触发规则表。
2. **Step 2**：新建 `app/services/experience/habit_trigger.py`，定义 `HabitTriggerContext` 与 `trigger_habits` 纯函数。
3. **Step 3**：编写单测（单习惯命中、多习惯排序、同优先级冲突消解、无命中返回空、超限截断），确认不改 `match_habits`。

## Acceptance Criteria

- [ ] 对「用户工作累」情境能命中 `habit_comfort_companion_first` 等确定性习惯，结果稳定。
- [ ] 同优先级冲突消解规则确定（不依赖遍历顺序、无随机性）。
- [ ] 命中数量 ≤ `HABIT_MAX_COUNT`，且不硬编码任何回复句子。
- [ ] 不修改 `behavior_engine.match_habits` 与 `habit_runtime.py` 既有函数（仅新增调用）。
- [ ] 单测覆盖：单命中、多习惯排序、同优先级冲突、无命中返回空、超限截断。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
