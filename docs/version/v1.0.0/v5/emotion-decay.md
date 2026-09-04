# Emotion Decay

## 1. 背景

V2 只有 `apply_idle_recovery`（超 N 小时把 tired/angry 重置 calm 的开关式恢复），没有强度随时间衰减的概念。

## 2. 衰减模型（第一版：线性 + 底线，不做心理学模型）

```text
每次状态读取时（load_states 内，纯代码）：
elapsed = now - updated_at
intensity' = intensity - decay_rate_per_hour × elapsed_hours
衰减分两段：
  高强度（> 0.5）：0.20 / 小时    # 激烈情绪回落较快
  低强度（≤ 0.5）：0.10 / 小时    # 轻微情绪留存更久
intensity ≤ decay_floor(0.15) 时：
  情绪复位为 calm，intensity = 0.3（默认静息值），cause 清空
updated_at 只在实际写库时刷新，衰减读取用 last_event_at（避免"读导致衰减重置"）
```

- 所有速率/底线入 `core/settings.py`：`emotion_decay_strong` / `emotion_decay_mild` / `emotion_decay_floor` / `emotion_rest_intensity`。
- 衰减在**读取侧**惰性计算 + 写回，不引入定时任务（与 V2 idle recovery 同一模式，简化实现）。

## 3. 情绪持续时间（隐式）

- strong(normal) 事件 intensity≈0.55，约 2~3 小时回落到底线 → 复位。
- strong 档事件 intensity≈0.7，约 4 小时。
- 持续对话中的新事件会不断重置 updated_at，形成"只要还在聊就维持"的自然效果。

## 4. 新事件覆盖与多事件叠加

- 覆盖规则见 emotion-update.md（同情绪叠加 +0.x；异情绪切换带 20% 惯性；强情绪保护）。
- 同轮多个候选事件：只取 confidence 最高者作为主事件，其余**不叠加**（第一版防震荡；多事件叠加列为 P2 评估项）。

## 5. 边界情况

- 跨天回归：衰减按 elapsed 一次性计算，不逐小时循环；intensity 一定落在 [0,1]。
- 衰减计算失败：沿用旧值，trace 记 error。
- scene_mood（V3）与 CharacterEmotion 语义区分：scene_mood 是场景氛围（临时、不落库），CharacterEmotion 是角色内在情绪（持久、带衰减），互不干扰。

## 6. 验收标准

- Case：事件后 intensity 按速率回落，到底线自动复位 calm。
- Case：1.5 小时后读取，0.55 强度 happy → 约 0.25（数值断言 ±0.05）。
- 读取侧衰减不阻塞回答（同 load_states 现有路径）。
