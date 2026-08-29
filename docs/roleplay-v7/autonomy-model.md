# Autonomy Model

## 1. 五条件门（同时满足才 ACT）

```text
ACT  ⟺  Trigger 成立 ∧ Motivation 存在 ∧ Permission 允许 ∧ 冷却通过 ∧ Action 合法
WAIT  ⟺  Trigger 成立但任一条件未满足（保留候选，下轮再评）
IGNORE ⟺ Trigger 不成立 / 已处理过（丢弃，不留候选）
```

三值输出防止"该说话时不说（漏）"与"不该说话时说（扰）"两类错误被混在一个布尔里。

## 2. 触发记录（评估的原子单位）

```python
@dataclass
class TriggerSignal:
    type: TriggerType            # conversation_inactivity / scheduled_followup
    user_id: str
    detected_at: datetime
    context: dict                # 闲置时长/到期事件摘要等
    dedupe_key: str              # "inactivity:u1:20260829T2130" / "followup:{memory_id}"
```

`dedupe_key` 是防重复评估的幂等键：同一 key 在冷却窗口内只产出一次 ActionCandidate。

## 3. 裁决结果

```python
class AutonomyVerdict(BaseModel):
    decision: Literal["act", "wait", "ignore"]
    reason: str = Field(max_length=60)      # 结构化单句（"用户离开 35 分钟且存在 user_care 目标"）
    trigger: TriggerSignal | None
    goal_id: str | None
    intention: IntentionType | None
```

reason 与 V6 同规：结构化单句、无思维链、max_length 截断、不进用户可见回复。

## 4. 主动意图白名单（V6 IntentionType 子集）

```python
PROACTIVE_INTENTIONS = {
    "user_care":     "check_in",        # 主动问候/关心（V6-011 时并入 IntentionType）
    "relationship":  "repair_rapport",  # 修复隔阂
}
```

MVP 白名单只有这两个映射；不在白名单的 Goal 类型（conversation/scene）**不触发主动行为**——对话类目标没有"用户不在场"的动机，场景目标依附于用户在场。

## 5. 配置集中（core/settings 新增组，全部不写死）

```python
autonomy_enabled: bool = True
autonomy_tick_seconds: int = 60
autonomy_inactivity_minutes: int = 30        # 会话闲置触发阈值
autonomy_min_interval_minutes: int = 240     # 同用户两次主动最小间隔
autonomy_max_attempts_per_episode: int = 2   # 单次闲置集期内最多主动次数
autonomy_backoff_multiplier: float = 2.0     # 每次未获回应后间隔翻倍
autonomy_quiet_hours_start: str = "23:00"
autonomy_quiet_hours_end: str = "08:00"
autonomy_max_retries: int = 2
autonomy_poll_seconds: int = 30              # 前端轮询建议值（文档约定）
```

## 6. 与 V5/V6 的分工重申

- Emotion/Relationship：进入 Policy 作为**阈值修正**（陌生关系提高门槛、concerned 情绪强化 check_in 动机），永不单独构成行动条件。
- Memory：scheduled_followup 类 Trigger 的来源（V7-011 P1），Memory 本身不是 Trigger。
- Scene：current_activity 属"角色在睡觉/忙碌"类时 Policy 直接 IGNORE（见 autonomy-policy.md §5）。
