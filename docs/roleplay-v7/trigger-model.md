# Trigger Model

## 1. MVP 两种 Trigger（其余明确延期）

| Trigger | MVP | 语义 | 数据来源 |
|---|---|---|---|
| conversation_inactivity | ✅ P0 | 用户"我去忙了/睡觉了"后长时间无互动，或会话闲置超阈值 | `conversation_repository.get_recent_messages` 最后一条 |
| scheduled_followup | ✅ P1（V7-011） | V4 记忆中的事件时间到期（"今天有面试"→傍晚询问结果） | 记忆/事件时间 + 内存待触发登记 |
| emotion/relationship change | ❌ 延期 | 状态突变触发——V5 状态本就随对话变化，无独立扰动源 | — |
| memory event（非时间类） | ❌ 延期 | — | — |
| goal event | ❌ 延期 | goal_review 的变更结果作为信号 | — |

**MVP 只有 time 系 Trigger**：它们是"用户不在场"时唯一可观测的环境信号，且无需引入新数据依赖。

## 2. conversation_inactivity 判定（纯函数）

```text
成立条件（全部满足）：
  1. 最后一条消息距 now ≥ autonomy_inactivity_minutes（默认 30）
  2. 最后一条消息存在（会话有过交互；从未聊过的空会话不触发）
  3. 该"闲置集期"（episode）内主动次数 < autonomy_max_attempts_per_episode
     episode 起点 = 用户最后一条消息时间；用户回复即重置
  4. dedupe_key 未在本 episode 出现过

dedupe_key = f"inactivity:{user_id}:{last_user_message_id}"
```

边界：
- 用户最后一条是**角色**主动消息且未获回应 → 不再重复触发（attempt 计数已 +1，冷却与 max_attempts 拦截）——防"不回复→主动→不回复→再主动"循环（testing.md Case 3）。
- 用户刚回复（last 是用户且 < 最短互动间隔 2 分钟）→ 不触发（Reactive Mode 优先，见 §3）。

## 3. Reactive / Proactive 互斥

```text
Reactive Mode：用户在交互（最近 5 分钟内有用户消息 / 生成中标记存在）
  → chat_pipeline 全权负责，Worker 对该用户一律 IGNORE

Proactive Mode：用户离开（闲置阈值达到）且无生成中标记
  → Worker 才可能 ACT
```

判定信号（全部已有）：`conversation_recent_messages` 最后一条时间、内存 `active_generations[user]` 标记（chat_pipeline 流式开始置位、结束清除）。两套机制永不抢消息。

## 4. scheduled_followup（V7-011，P1）

```text
登记：goal_review / memory 管线发现带时间语义的事件（"明天面试"）→ 内存待触发表 {user, due_at, dedupe_key}
到期：Worker tick 发现 due_at ≤ now → 产出 TriggerSignal(type=scheduled_followup)
用途：intention=check_in（"面试怎么样了？"）——V4 记忆与自主行为的第一次协同
```

MVP 内存登记即可（重启丢失可接受，事件本身低频）；持久化登记延后。
