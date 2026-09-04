# Cooldown（冷却与重复防护）

## 1. 三个层次的防轰炸

```text
L1 最小间隔（min_interval）：同用户两次主动行为的全局最小间隔，默认 240 分钟
L2 集期上限（max_attempts_per_episode）：一次"用户离开"集期内最多主动 2 次，用户回复即重置
L3 指数退避（backoff）：集期内第 N 次主动未获回应后，下次可主动间隔 = min_interval × multiplier^(N-1)
```

L3 意味着：默认参数下第一次主动后 4 小时、第二次后 8 小时——"用户不回复→无限轰炸"在数学上不可能发生。

## 2. 状态记账（全在 proactive_actions 表聚合，无新表）

```text
last_proactive_at   = 最近一条 delivered/acked 行的 delivered_at
attempt 计数         = 当前 episode（起点=用户最后一条消息时间）内 delivered 行数
episode 重置         = 用户发言（chat_pipeline.save_turn 后置内存标记 + 评估时按时间重算）
```

判定为纯函数：`(signal, last_proactive_at, attempt_count, config, now) → 冷却是否通过 + 生效间隔`。

## 3. 冷却与 V5 状态的互动（autonomy-policy.md §5 修正的落点）

| 信号 | 生效间隔修正 |
|---|---|
| intimacy ≥ 0.55 | × 0.5（亲密关系可更自然地主动） |
| tension > 0.5 且修复目标 active | × 0.5（破冰优先） |
| 其余 | × 1.0 |

修正后仍必须 ≥ 硬底线 `autonomy_min_interval_floor_minutes`（默认 60）——亲密度再高也不允许小时级轰炸。

## 4. 与队列深度 1 的配合

冷却通过 ≠ 立即行动：若该用户已有非终态 action（上一条未 delivered/acked/终态），直接 WAIT。四道闸从外到内：

```text
Trigger 幂等键 → 冷却/退避 → episode 上限 → 队列深度 1
```

## 5. 用户回应的复位语义

用户任意一条消息（正常 chat 流程）即：
- episode 重置（attempt=0，退避清零）；
- 未 acked 的主动消息自动 acked（用户已回来，气泡无意义）；
- 若主动 action 尚在 candidate（还没生成文本）→ discarded（"我刚要主动，用户先说话了"→ 让位给反应式）。

## 6. 测试锚点

- Case 3（连续主动防护）：两次 trigger 间无用户回应 → 第 2 次 WAIT（attempt=2 = max）；
- 退避验证：mock 时间推进 min_interval×1 但 backoff 后有效间隔为 ×2 → WAIT；
- 复位验证：用户发言后 attempt 清零、候选 action 被 discarded。
