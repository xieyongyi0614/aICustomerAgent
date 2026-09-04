# Relationship Update & 防跳变

## 1. 分工

- LLM：识别事件类型/档位/置信度（relationship-events.md）。
- **代码**：delta 计算、上限、clamp、stage、持久化。LLM 全程无分数修改权。

## 2. 变化上限（三层防跳变）

| 层 | 规则 | settings |
|---|---|---|
| 单事件 | delta 表数值即上限；strong 档 ×1.4 后仍封顶（每维绝对值 ≤ 0.17） | `rel_max_event_delta` |
| 单轮 | 同轮事件 + behavior modifier 合计后每维绝对值 ≤ 0.15 | `rel_max_turn_delta` |
| 每日 | 同日累计正向变化每维 ≤ 0.30（按 relationship_events 当日 impact 聚合，超出部分截断仍落账） | `rel_max_day_delta` |

- 负向变化同规则（冲突日 tension 最多 +0.30/日，防一天吵崩）。
- 事件行 `impact` 记录截断后的实际值（账本与状态严格一致）。

## 3. 情绪与关系的变化边界

- 情绪（分钟~小时）：单轮 intensity ≤ 0.4，衰减小时级 —— 见 emotion-decay.md。
- 关系（天~周）：单轮 ≤ 0.15、日 ≤ 0.30 —— 两套上限独立配置，禁止共用。
- Emotion 不直接改关系分数：情绪事件和关系事件是同一检测器的两个输出，各自走各自的表，不互相换算。

## 4. 更新算法（纯代码）

```text
delta = EVENT_DELTAS[type] × magnitude 系数 + BEHAVIOR_DELTAS[behavior]
delta = 每维 clamp(delta, -rel_max_event_delta, +rel_max_event_delta)
delta = 每维 clamp(delta, 日内余量)            # 日上限
new_value = clamp(current + delta, 0, 1)
tension 正向互动消耗规则（relationship-model.md）
stage = next_stage(...)（V2 迟滞机制 + tension 冻结）
```

## 5. 执行位置

- `_post_process` 后台；trace step `relationship_event`。
- 失败：关系停在上一轮，trace 记 error，不影响回答。

## 6. 验收标准

- Case 9：构造 strong conflict 单轮，各维变化 ≤ 上限（0.15/日 0.30），禁止 0.30→0.95。
- Case 10：模拟 30 天 user_care 累计，trust 从 0.35 缓升至 ~0.6+，stage 依阈值迁移。
- 事件表 impact 总和 == 状态实际变化（对账单测）。
