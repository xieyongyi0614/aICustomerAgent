# Relationship Events

## 1. 背景

V2 的关系变化只进 `emotion_history`（每轮轨迹行），没有"事件→影响"实体，无法审计与调参。

## 2. RelationshipEvent 模型

```python
class RelationshipEvent(BaseModel):
    id: str                       # uuid PK
    user_id: str                  # 索引
    character_id: str = "asuna"
    session_id: str
    type: RelationshipEventType   # user_care / conflict / ...
    magnitude: Literal["weak", "normal", "strong"]
    impact: RelationshipDelta     # 实际应用的各维变化（代码计算后回填）
    confidence: float             # 检测置信度
    source: Literal["conversation", "memory_replay"] = "conversation"
    cause: str = Field(default="", max_length=50)
    created_at: datetime
```

## 3. 事件来源

1. **conversation**：本轮对话检测（主来源）。
2. **memory_replay**：V4 `relationship_event` 类型记忆在长期未互动会话中召回时，补记一次衰减过的历史事件（memory-integration.md），source 标记区分。

## 4. 生成流程

```text
turn_analysis_chain 扩展输出（与 role_router / scene_intent 并行）
  → RelationshipEventType + magnitude + confidence + cause
  → 代码查 delta 表 × magnitude 系数 → RelationshipDelta
  → 上限校验（relationship-update.md）→ 应用到 RelationshipState
  → RelationshipEvent 落库（含 impact 实际值）+ emotion_history 保留
```

- `impact` 记录**实际生效值**（经过系数与 clamp），保证"事件表 = 状态变化的完整账本"。
- type=none：不建事件行（防表膨胀）；daily 类累计行为由 familiarity 小步 delta 表达，也建行（弱影响，magnitude=weak）。

## 5. 与 emotion_history 的关系

- emotion_history（V2）：每轮一行，情绪视角轨迹，保留不动。
- relationship_events（V5 新表）：仅在有关系事件时一行，关系视角账本。
- 两者不合并：查询模式不同（轨迹 vs 账本）。

## 6. 表膨胀控制

- 只在"有事件"时落行；无事件轮零写入。
- 后续调参可按 impact 聚合回放；超过 90 天的历史事件归档（P2）。

## 7. 验收标准

- Case：user_care → trust +0.04/intimacy +0.03 的 event 行落库，impact 与实际状态变化一致。
- 无事件轮不产生行。
- source=memory_replay 的事件在 Debug 面板可区分。
