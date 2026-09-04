# Emotion Evaluation

> Emotion 维检查（规则层 app/services/evaluation_rules/emotion.py，新增）：检测情绪变化是否自然——跳变、无触发切换、文本与状态冲突。事实源是 V5 的 `emotion_history`（mood_before/after、event、magnitude 逐轮留痕）。

## 1. 检什么

本系统的情绪是**离散 mood 标签 + intensity 标量 + cause**（无 valence/arousal 双轴），且 `state_engine.update_emotion` 已经在写入侧做了钳制（切换阈值、置信度门槛、单轮 Δ 上限、惯性）。因此评估**不重复实现引擎的钳制公式**，只审计三个结果层问题：

| 问题 | 例子 | 检查 |
|---|---|---|
| 转移合理性 | 用户普通聊天 → 角色从 calm 跳到 sad | mood A→B 是否有匹配强度的触发事件 |
| 触发一致性 | 用户夸奖（praise）→ 角色转向 angry | 事件类别与 mood 方向是否相容 |
| 文本-状态一致性 | mood=happy 且无负向事件，回复通篇悲伤低沉 | 回复文本情绪信号与状态冲突 |

## 2. 规则层

### 2.1 EMOTION_UNTRIGGERED_SHIFT（warning）

输入：`emotion_history` 最新一条（mood_before / mood_after / event / magnitude）。

```text
IF mood_before ≠ mood_after
   AND event ∈ {none} 或 magnitude = weak
THEN issue(EMOTION_UNTRIGGERED_SHIFT, warning,
           evidence = cause 字段 + before/after)
```

strong / normal 事件驱动的切换是引擎的正常产物，不报。引擎已保证的属性（单轮 Δ ≤ `emotion_max_turn_delta`、切换需过 strong 阈值）**不需要复查**——评估审计的是"引擎放行的结果在事件维度上是否讲得通"，这是引擎输入（LLM 判定的 event/magnitude）可能说谎的地方：turn_analysis 把用户情绪事件判弱了，引擎忠实地小步移动，结果仍是一次"没有理由"的情绪摆动。

### 2.2 EMOTION_TEXT_STATE_CONFLICT（warning，候选级）

词表启发式：回复文本命中强情绪信号词（悲伤 / 愤怒 / 恐惧类），而 mood_after 为不相容档位（如 happy/calm）且本轮无对应 event → 报候选 issue，交 judge 在采样轮确认或忽略。

方向性设计：只查"文本负向 × 状态正向"这一种高频冲突，反向（文本欢快 × 状态悲伤）常属正常安慰场景，不报。

### 2.3 候选与 judge 的确认闭环

词表候选是高误报信号（"平静叙述悲伤往事"会命中），它的定位是 **judge 的注意力输入，不是独立结论**：

```text
judge 在场（采样命中且未降级）：
    judge 报 EMOTION_TEXT_STATE_CONFLICT → 吸收候选，保留 judge 版 issue
    judge 未报该 code                   → 候选吸收丢弃（已被主动复核过）
judge 缺席（未采样 / 调用失败）：
    候选自身生效（warning）——弱信号优于无信号
```

与 memory 维刻意不同：memory 的 CANDIDATE 在 judge 缺席时保留、judge 确认后升格为 FABRICATION（critical）；emotion 候选在 judge 在场时以 judge 为唯一裁决——因为情绪词表的误报率显著高于 recall-marker，不值得独立定罪。吸收关系在合并器中按 code 确定性执行（同 llm-judge.md §6 的冲突预定义原则）。

## 3. Judge 层

```python
class EmotionJudgement(BaseModel):
    score: float
    codes: list[EmotionIssueCode]   # 受限枚举：EMOTION_OVERSHIFT / EMOTION_TEXT_STATE_CONFLICT
    evidence_quote: str             # reply 子串校验
    confidence: float
```

judge 的判定输入是 digest 的 `emotion` 切片 + reply + 近期消息，评审标准固定写入 prompt：

1. 相对触发事件，情绪强度是否过度（EMOTION_OVERSHIFT）；
2. 转向是否在短时间内反复摇摆（近 6 条消息内 mood 多次相向切换——从 digest.recent_messages 配对的 emotion 快照读取）。

## 4. 与 state_engine 的关系（明确分工）

```text
state_engine（写入侧，V5 既有）   ：保证"单次变化"受控——Δ 上限 / 切换门槛 / 惯性
emotion rules（审计侧，V7.5 新增）：审计"变化序列"合理——事件讲不讲得通、方向对不对
```

评估不复算引擎公式、不否决引擎结果；即使规则报警，mood 也不回滚——**报警是给开发者看的，不是给状态机的**。

## 5. 已知局限

- event/magnitude 由 turn_analysis LLM 判定，评估依赖同一判定——上游判错且"错得自洽"时两侧同向错。缓解：`emotion_history` 的 cause 字段进入 digest，judge 可对照原文复核。
- 词表法对"平静叙述悲伤往事"会误报候选——severity=warning + judge 确认机制吸收。
