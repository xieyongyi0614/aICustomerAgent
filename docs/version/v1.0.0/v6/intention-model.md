# Intention Model

## 1. 定位

```text
Goal（想要什么，跨轮）
   ↓ 本轮评估
Intention（这轮打算做什么，单轮）
   ↓ 人格化表达（LLM）
Response（怎么说）
```

Intention ≠ Sentence：同一 Intention 在人格约束下有无数合法表达；Intention 也不直接是 V2 behavior——behavior 是表达层指令（沿用），intention 是动机层决策（新增），二者在 Prompt 中并存且 intention 为主。

## 2. 枚举（12 值，V6 封顶）

```python
IntentionType = Literal[
    # 用户福祉类
    "comfort_user",        # 安抚用户情绪（配 user_care/relationship）
    "suggest_rest",        # 建议收尾/休息（配 user_care-劝休；语义是建议不是赶人）
    "encourage_user",      # 给用户打气
    "celebrate_with_user", # 和用户一起庆祝
    # 关系类
    "express_affection",   # 表达亲近（需 intimacy ≥ 阈值，Policy 校验）
    "tease_user",          # 轻微调侃（需 familiarity ≥ 阈值）
    "maintain_distance",   # 保持距离感（仅 tension > 0.5 时合法）
    "repair_rapport",      # 修复隔阂（配 relationship-修复目标）
    # 对话类
    "continue_topic",      # 延续当前话题（默认兜底值）
    "ask_followup",        # 追问用户近况/细节
    "share_own_feeling",   # 分享角色自身状态/感受
    "lighten_mood",        # 轻松化解（配 funny/teased 情绪事件后）
]
```

对照题设：`change_topic` 收敛进 continue_topic（换话题由话题管理负责，V6 不引入话题状态机）；`end_conversation` 不引入（赶人语义风险大，suggest_rest 覆盖）；`wait` 不引入（无主动行为）。

## 3. IntentionDecision（LLM 输出 Schema）

```python
class IntentionDecision(BaseModel):
    intention: IntentionType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=60)   # 结构化理由，见 §6
```

LLM 只输出候选 + 理由；**无分数修改权、无 Goal 修改权**。

## 4. 有效性规则（IntentionPolicy，纯代码）

| Intention | 合法条件（任一不满足即降级） |
|---|---|
| express_affection | relationship.intimacy ≥ 0.55（复用 stage_close 阈值语义） |
| tease_user | familiarity ≥ 0.4 且 tension ≤ 0.3 |
| maintain_distance | tension > 0.5 |
| repair_rapport | tension ≥ 0.3 |
| celebrate_with_user | 本轮 user_emotion.event == achievement 或情绪为 happy |
| suggest_rest | user_emotion.emotion ∈ {tired} 或深夜时段（23:00~06:00） |
| comfort_user | user_emotion.emotion ∈ {sad, anxious, tired} 或本轮 emotion_event ∈ {criticized, worrying_news} |
| 其余 6 值 | 恒合法 |

降级规则：非法候选 → 依次回退 `continue_topic`；链失败/非法输出 → 同样回退。**Policy 永远输出一个合法 Intention。**

## 5. 与 V2 Behavior 的映射（过渡期共存）

| Intention | 建议 behavior（写入现有 TurnAnalysis.behavior 消费链路） |
|---|---|
| comfort_user / suggest_rest | comfort / show_concern |
| encourage_user | encourage |
| celebrate_with_user | celebrate |
| ask_followup | ask_followup |
| 其余 | normal_reply |

answer prompt 两者都注入：intention 段为主、behavior 段保留（不改 V2 表达资产）。

## 6. Reason 的边界（重要）

- 允许：一句结构化决策理由，≤60 字，格式"信号 → 选择"（"用户表达疲惫，当前目标为陪伴放松，故选择安抚"）。
- 禁止：思维链/隐藏 reasoning/多步推理文本。Schema 上以 max_length + prompt 指令双重约束；Policy 对超长 reason 截断。
- 用途：trace/turn_meta/debug 面板内部解释，**不进用户可见回复**。
