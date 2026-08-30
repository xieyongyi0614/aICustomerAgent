# V8.5 M8：Autonomy Integration（自主行为集成）

> 关系决定"能不能主动、敢不敢打扰"。高信任：可以主动提醒与关怀；低信任/冲突期：减少打扰甚至闭嘴。V7 的八步裁决是纯函数闸门，V8.5 以追加规则的方式挂入（模式同 V8 world_facts 的 W1/W2/W3）。

## 1. PolicySnapshot 扩展（可选字段，默认值 = 关闭语义）

```python
class PolicySnapshot(BaseModel):     # 扩展 V7 模型
    ...                              # 既有字段不动（intimacy/tension/stage 已在其中）
    respect: float = 0.60            # ★
    comfort: float = 0.60            # ★
    conflict_status: str = "none"    # ★（state 行冗余列直读）
    neglect_active: bool = False     # ★
    unlocks: tuple[str, ...] = ()    # ★（里程碑解锁集）
```

- `_snapshot_for` 装配时从 relationship_state 单行直读（零额外查询）；装配失败 → 全部默认值（降级 = V7 现状）。
- **不传新字段的调用方输出与 V7 逐位一致**（既有 autonomy 测试零回归的硬保证）。

## 2. R1~R5 门控规则（追加在八步闸门之后，纯函数）

| # | 条件 | 效果 | reason |
|---|---|---|---|
| R1 冲突克制 | conflict_status ∈ {conflict, cold} | 一律否决，**除** intent=reconciliation_check_in（需 unlocks 含 conflict_recovery_available 且 trust>0.3，且单冲突至多一次） | relationship_conflict |
| R2 自在调节 | comfort < 0.35 | 冷却间隔 ×1.5 | relationship_low_comfort |
| R3 信任门槛 | intent ∈ {reminder, followup} 且 trust < rel_autonomy_trust_floor=0.45 | 否决（提醒是信任特权） | relationship_low_trust |
| R4 里程碑解锁 | intent 类别对应的 unlock key 缺失 | 否决（例：goodnight_care 需 proactive_goodnight） | relationship_locked |
| R5 疏远召回 | neglect_active 且 stage ≥ friend | **放行**一次轻量问候（reconnect_check_in），覆盖 R3 | relationship_reconnect |

- 既有 gate 全部保留且先于 R 规则执行（R 只做追加收紧/单点放行，不解除任何既有闸门——不可拆闸门原则，同 V8 W3）。
- 现有 intimacy 语义保留：intimacy<0.3 不主动（V7 既有）、intimacy≥0.55 冷却减半（既有）——R 规则与其叠加不冲突。
- intent 类别 × unlock 对应表进角色资产（与 M4 §5 unlocks 语义表一致，单一事实源）。

## 3. 与冲突态的主动行为语义

| 态 | 主动行为 |
|---|---|
| strain | 允许但语气克制（R1 不管，M7 prompt 管语气）；频率不变 |
| conflict / cold | R1 强抑制，仅允许一次和解问候 |
| recovery | 恢复正常门槛；文本生成侧（M7）给软化指令 |
| resolved | 全部恢复正常 |

- 主动消息**不触发** V5/V8.5 状态更新（V7 既有纪律）——角色主动打招呼不等于发生关系事件；效果由用户回应那一轮的信号自然吸收（用户回复 = 新互动 = 新信号）。

## 4. 回流闭环

```text
主动消息 → 用户回应（正/负/忽略）→ 下轮 InteractionAnalyzer 信号 → 演化
例：R5 召回问候被热情回应 → support/positive → trust/comfort 回升 → neglect 复位
例：R1 期间硬问候被冷回应 → 冷信号 → 冲突加深
```

- 无专门回流通道：主动行为的后果就是用户的下一轮互动， Analyzer 天然覆盖——不加"主动效果评分"这类新表。

## 5. 与 V7/V8 的边界

- 不新增触发类型、不动 trigger_evaluator / proactive 状态机 / 执行器 / 静音时段（V7 全套零修改）。
- 不消费 V8 world_facts（那是 V8-011 的挂载点）；两者都追加在八步之后，若同时实现，执行顺序 = 既有闸门 → V8 W 规则 → V8.5 R 规则（后到者更严，放行类 R5 最后评估）。

## 6. 验收标准

- 不传新字段 → policy 输出与 V7 逐位一致（快照对比测试）。
- R1~R5 逐条正反例；R1 的唯一放行通道（reconciliation_check_in）单冲突一次的幂等。
- R5 覆盖 R3 的优先级正确；所有 reason 串进 decision_records（V7.8 既有决策留痕）。
- 装配失败降级为默认值且 V7.5 autonomy 维评估照常。
- 触发器/入队/执行器测试零回归。
