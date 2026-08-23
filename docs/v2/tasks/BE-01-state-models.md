# BE-01 状态领域模型

| 字段 | 内容 |
|---|---|
| Task ID | BE-01 |
| Task Name | 状态领域模型（behavior / emotion / character_state / relationship） |
| Type | BE |
| Priority | P0 |

## Description

定义 V2 全部 Pydantic DTO：行为决策、用户情绪与轮次分析、角色状态、关系状态。全部为可序列化纯 DTO（不跨层传 ORM），是后续所有 V2 任务的类型基础，也是未来 LangGraph checkpoint 的状态对象。

## Scope

- `app/models/behavior.py`：`BehaviorType`（7 值 Literal）、`BehaviorDecision(behavior, reason)`
- `app/models/emotion.py`：`UserEmotionLabel`（8 值）、`EventCategory`（9 值）、`UserEmotion(emotion, event)`、`TurnAnalysis(user_emotion, behavior)`（嵌套，均带默认值）
- `app/models/character_state.py`：`Mood`（8 值）、`CharacterState(mood, energy, current_topic, inner_state, updated_at)`、`StateUpdateDecision(mood, mood_reason, inner_state, current_topic)`
- `app/models/relationship.py`：`RelationshipStage`（4 值）、`RelationshipState(intimacy, trust, familiarity, stage)`、`RelationshipDelta(intimacy, trust, familiarity)`
- `app/models/conversation.py`：`ConversationState` 增 `character_state` / `relationship_state` 两个带默认值字段

字段定义与默认值以架构文档 §3 为准。

## Out of Scope

- ORM 行模型与建表（DB-01）
- 状态更新规则（BE-02）
- ConversationState 两个新字段的填充逻辑（BE-06）

## Dependencies

- 无（V1 models 层已存在，纯增量）

## Input

- `docs/v2/v2-architecture.md` §3 Pydantic 模型设计
- `app/models/conversation.py`（V1 现状）

## Output

- `app/models/behavior.py`、`app/models/emotion.py`、`app/models/character_state.py`、`app/models/relationship.py`
- `app/models/conversation.py`（修改）

## Business Rules

1. 浮点字段全部 `Field(ge=0.0, le=1.0)`：`energy` / `intimacy` / `trust` / `familiarity`。
2. `TurnAnalysis()` 无参构造必须得到 neutral / daily / normal_reply——它就是编排层的降级快照。
3. `CharacterState.updated_at` 只由 repository 填充，业务层不写；默认 `None`。
4. 枚举一律 `Literal`，非法值直接拒收，不做运行时纠错。
5. 不添加代码注释，用命名表达意图（全局约定）。

## API Dependencies

- 无

## Data Dependencies

- 无（纯内存 DTO）

## Permission

- 无

## Error Handling

- 边界与枚举校验交给 Pydantic ValidationError，向上传播，不吞不转。

## Subtask 拆分

- S1：`behavior.py` + `emotion.py`（预侧类型）
- S2：`character_state.py` + `relationship.py`（状态类型）
- S3：`ConversationState` 扩展（带默认值，保证 V1 旧路径不炸）
- S4：边界校验单测

## Acceptance Criteria

- `CharacterState(energy=-0.1)`、`RelationshipState(intimacy=1.5)` 抛 ValidationError
- `TurnAnalysis()` 默认值为 neutral / daily / normal_reply
- 既有 pytest 全绿（向后兼容）
- `pylint` 不低于既有基线

## Test Requirements

- `tests/test_models_v2.py`：浮点上下边界拒绝、枚举非法值拒绝、TurnAnalysis 默认值、ConversationState 不传新字段可构造
- 不依赖网络与真实 LLM
