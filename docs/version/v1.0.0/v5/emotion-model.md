# Emotion Model

## 1. 背景

V2 `CharacterState.mood` 只有标签，无强度与成因，且由 LLM 每轮直写。

## 2. 情绪集合（V5 第一版固定 8 值，沿用 V2）

```python
EmotionLabel = Literal[
    "happy", "sad", "angry", "worried",
    "shy", "excited", "tired", "calm",
]
```

评估结论：题设 8 值中 `embarrassed` 与 V2 已有 `shy` 语义重合、`neutral` 以 `calm`（默认值）兼任——**不引入新标签**，保持与 V2 数据库 CheckConstraint、prompt、测试的连续性。

## 3. CharacterEmotion 模型

```python
class CharacterEmotion(BaseModel):
    primary_emotion: EmotionLabel = "calm"
    intensity: float = Field(default=0.3, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)   # "用户主动关心角色"
    updated_at: datetime | None = None
```

- 存储上并入 `character_state` 表扩展三列（primary_emotion 即现有 mood 保持兼容、新增 intensity/cause），不建新表。
- `cause` 仅用于 Debug 与 Prompt（"因为你刚才夸我"），50 字上限防膨胀。

## 4. EmotionEvent（检测器输出）

```python
EmotionEventType = Literal[
    "praise",          # 被夸奖/肯定
    "comforted",       # 被安慰/关心
    "criticized",      # 被批评/否定
    "teased",          # 被调侃
    "conflict",        # 冲突/争吵
    "warm_moment",     # 温馨互动
    "funny_moment",    # 好笑/开心
    "worrying_news",   # 令人担忧的消息
    "reunion",         # 久别重逢
    "none",            # 无显著情绪事件
]

class EmotionEvent(BaseModel):
    type: EmotionEventType = "none"
    magnitude: Literal["weak", "normal", "strong"] = "normal"   # 强度档位，LLM 只选档
    confidence: float = Field(ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)
```

## 5. 事件→情绪映射（代码持有，LLM 不可见修改权）

```python
EMOTION_EVENTS: dict[str, dict] = {
    "praise":        {"emotion": "happy",   "delta": +0.3},
    "comforted":     {"emotion": "happy",   "delta": +0.25},
    "teased":        {"emotion": "shy",     "delta": +0.25},
    "warm_moment":   {"emotion": "happy",   "delta": +0.2},
    "funny_moment":  {"emotion": "excited", "delta": +0.3},
    "criticized":    {"emotion": "sad",     "delta": +0.3},
    "conflict":      {"emotion": "angry",   "delta": +0.4},
    "worrying_news": {"emotion": "worried", "delta": +0.35},
    "reunion":       {"emotion": "excited", "delta": +0.3},
}
# magnitude 系数：weak=0.6 / normal=1.0 / strong=1.4
```

## 6. 验收标准

- 8 值与 V2 CheckConstraint 一致（迁移零转换）。
- intensity/cause 字段 50 字与 [0,1] 边界被强制。
- 情绪判定只输出档位，无自由分数。
