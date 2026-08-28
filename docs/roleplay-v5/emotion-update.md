# Emotion Update

## 1. 分工（V3/V4 同一原则的延续）

| 职责 | 执行者 |
|---|---|
| 识别"发生了什么"（EmotionEvent.type/magnitude/cause） | LLM（扩展现有 `turn_analysis_chain`，与 role_router/scene_intent 并行） |
| 强度转移、新旧情绪覆盖、多事件叠加、衰减、clamp、持久化 | **代码**（`state_engine` 扩展） |

## 2. 更新算法（纯代码）

```text
输入：prev Emotion + EmotionEvent（本轮单个主事件；多个候选取 confidence 最高者）
1. target = EMOTION_EVENTS[event.type]["emotion"]
2. raw_delta = base_delta × magnitude 系数（weak 0.6 / normal 1.0 / strong 1.4）
3. 同情绪叠加：target == prev.primary → intensity = clamp(intensity + raw_delta, 0, 1)
4. 异情绪切换：
   - 若 prev.intensity ≥ 0.6（强情绪）且 event.confidence < 0.8 → 拒绝切换（强情绪不被弱事件打断）
   - 否则切换：intensity = clamp(raw_delta + prev.intensity × 0.2, 0, 1)   # 旧情绪残留 20% 惯性
5. event.type == "none" → 仅执行衰减（emotion-decay.md）
6. cause 更新；updated_at = now
```

## 3. 防跳变

- 单轮 intensity 变化绝对值 ≤ 0.4（settings.emotion_max_turn_delta）。
- 强情绪保护阈值 0.6 与置信度 0.8 均入 settings。
- LLM 不输出任何分数；只输出 type/magnitude/confidence/cause。

## 4. 与 V2 StateUpdateDecision 的边界调整

- `StateUpdateDecision.mood` **废弃**（保留字段但被 Updater 忽略，过渡期后删除）。
- `inner_state` / `current_topic` 保留 LLM 直写（叙事性内容，不是数值）。
- energy 更新逻辑（EVENT/BEHAVIOR modifiers）原样保留。

## 5. 执行位置

- `_post_process` 后台，与 scene_update / memory / summary 并行，互不阻塞。
- trace step：`emotion_update`。

## 6. 验收标准

- Case：夸奖→happy 上升、批评→sad、冲突→angry（档位映射正确）。
- Case：强情绪不被低置信弱事件覆盖。
- Case：单轮变化 ≤ 0.4。
- V2 mood 直写路径退役后，既有 state 测试改写后通过。
