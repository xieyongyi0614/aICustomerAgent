# Action Model

## 1. MVP 单一 Action 类型

```python
ProactiveActionType = Literal["send_message"]     # V8+: remind / scene_act / tool_call
```

第一版只验证"角色能否合理地主动说一句话"（README §2）。

## 2. 字段

```python
class ProactiveAction(BaseModel):
    id: str                        # uuid
    user_id: str
    character_id: str = "asuna"
    session_id: str                # 投递目标会话
    type: ProactiveActionType = "send_message"
    trigger_type: TriggerType      # conversation_inactivity / scheduled_followup
    dedupe_key: str                # 幂等键（TriggerSignal 透传）
    goal_id: str | None            # 动机来源（V6 GoalRecord.id）
    intention: str                 # check_in / repair_rapport
    reason: str = Field(max_length=60)
    payload_text: str | None = None        # Executor 生成后回填（≤V2 语言风格约束）
    status: ActionStatus
    attempt: int = 0
    next_retry_at: datetime | None = None  # 失败退避
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None = None
    message_id: str | None = None          # 落库后的 conversation message id
    acked_at: datetime | None = None       # 前端确认展示
```

## 3. 状态机（MVP 收缩版）

```text
candidate ──policy 二次通过──► approved ──生成文本成功──► delivered ──前端 ack──► acked
    │                             │
    │ policy 否决                  │ 生成失败（attempt<max）
    ▼                             ▼
 discarded                    failed（next_retry_at=now+backoff → 重新 approved）
                                  │ attempt ≥ max_retries
                                  ▼
                               failed（终态）
超时（delivered 后前端 24h 未 ack）→ expired（软状态）
```

对比题设五态 + 失败态：合并 candidate/approved 入 policy 瞬时（无独立排队等待），MVP 不引入 scheduled 停留态（time-due 触发即评估）。保留 discarded/failed/expired/acked 全部软状态审计。

## 4. 队列深度约束

**单用户同时最多 1 条非终态 action**（candidate/approved/failed-retryable）。已有待处理 action 时，新 Trigger 直接 IGNORE（"上一条主动消息还没交付/未获回应"）——这是防轰炸的最后一道闸（cooldown.md §4）。

## 5. 不暴露给 LLM 的字段

type/attempt/next_retry_at/status/message_id/acked_at 全部代码持有；proactive_chain 只拿到 goal/intention/最近对话/语言风格约束——与 V4 privacy、V6"内部字段不进 Prompt"原则一致。
