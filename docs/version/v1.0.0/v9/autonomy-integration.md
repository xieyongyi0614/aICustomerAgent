# V9 Autonomy Integration（行动 ↔ V7 双向集成）

> 自治是行动的第二个来源：角色不仅响应用户，还主动行动。本篇定义 action_facts 进裁决快照、due_action 触发器与自治产行动分支。**八步裁决闸门零修改**——与 V8 的 W1/W2/W3 同款纪律：只增事实输入，不拆闸门。

## 1. 双向关系总览

```text
V7 Autonomy（V9 之前：只会"说"）
    │
    ├─ ① action_facts（只读注入）──────────→ 八步裁决看得见行动（知道"我设过提醒、还没到期"）
    ├─ ② due_action 触发器（新信号）────────→ 到期提醒 → 主动汇报（"到点了，该买牛奶了"）
    └─ ③ 自治产行动分支（autonomy_action_enabled，默认关）
            act 裁决 → ActionPlan(source="autonomy") → Capability   ← 真正"做"而不只是"说"
```

## 2. ① action_facts 进 PolicySnapshot（只读事实包）

- `autonomy_engine._snapshot_for` 增读 `action_engine.collect_facts(user_id) -> dict`（H-A5，与 `world_engine.collect_facts` 同惯例：有界、失败返回 `{}`）：

```text
{
  "active_plans": 2,                          # 非终态行动数
  "pending_reminders": [{"title": "开会", "due_in_hours": 14.2}],
  "recent_failures": [{"action": "create_reminder", "reason": "参数不足"}],   # ≤3 条
  "last_action_at": "…"
}
```

- `PolicySnapshot.action_facts` 默认空 dict——不传时 policy 输出与 V8 完全一致（既有测试零回归的断言点）。
- 消费方式（P1）：policy 追加 A 系列修饰规则（纯函数，只追加 reason，不改 decision）——A1：存在 24h 内到期提醒时为 relationship/user_care 目标追加"可跟进行动"理由；A2：recent_failures 非空时建议补救型 check_in。**不新增闸门、不覆盖 wait/ignore**（W1/W2/W3 同款）。

## 3. ② due_action 触发器（到期提醒 → 主动汇报）

- `trigger_evaluator` 新增 `poll_due_actions(user_id, now) -> TriggerSignal | None`（H-A6），查询优先级排在既有 `poll_due_followup` **之前**（到期汇报比复盘追问更紧急）：

```text
WorldEvent(type ∈ {reminder, appointment}, status=active, due_at ≤ now, 汇报未发送)
    → TriggerSignal(trigger_type="action_due", goal_id=行动记录的 goal_id, dedupe_key="action_due:{event_id}")
```

- **"汇报未发送"判定**：WorldEvent.payload 增 `reported_by_autonomy` 标志（V8 payload dict 既有机制，零迁移）——触发器命中后置位，幂等保证同一到期只汇报一次。
- 触发后走**完全既有**的八步裁决 → ProactiveAction(send_message) → proactive_executor：主动消息文本由 proactive_chain 生成（"到点了，你之前让我提醒你买牛奶"），**不新建 ActionRecord**（发消息是言语不是行动，action-model.md §5）。
- 静音时段/冷却/容量闸门全部照旧：深夜到期的提醒等到静音结束才汇报（八步闸门第 2 步），这是"角色有分寸"的既有语义，V9 不豁免。
- 用户在到期前自己完成/取消（"面完了"/"不用提醒了"）→ 事件 completed/cancelled → 不再命中触发器（行动事实与世界事实天然一致）。

## 4. ③ 自治产行动分支（默认关）

用户场景："角色发现用户连续工作 8 小时 → 决定提醒休息"。两档实现：

| 档位 | 机制 | 状态 |
|---|---|---|
| 言语提醒（现状可达） | 自治裁决 act → 主动消息"休息一下吧"（V7 既有，intention=suggest_rest） | **已存在，V9 不改** |
| 真行动提醒 | 自治裁决 act → `create_action_plan(source="autonomy", action_type=create_reminder, params={content:"休息", due:now+30min})` → ActionEngine 六闸门（G1~G6 复用）→ WorldEvent | **autonomy_action_enabled 门控，默认 false，P2 实现** |

- 真行动分支的设计约束：
  1. **同一八步裁决先行**——自治产行动不是绕过闸门的旁门，而是 act 决策的另一种履行方式；`PROACTIVE_ACTION_MAP`（intention → 可执行 ActionType 映射，如 suggest_rest → create_reminder）为纯函数表，命中且开关开启时产 ActionPlan 而非 send_message。
  2. **额度收紧**：autonomy 来源行动并入 G5 容量 + 独立日额度 `autonomy_action_daily_limit`（默认 1）——无人确认的行动必须比对话行动保守。
  3. **无反馈闭环**：自治创建的提醒到期 → due_action 触发器 → 主动汇报 → 用户回应，闭环自然形成。
- 默认关闭理由：自治直接产生外部效果（哪怕只是 WorldEvent）的行为边界未经验证；先由 debug 端点灰度观测，人工回归后再开。

## 5. 与 V7 既有机制的边界

| V7 既有 | V9 增量 | 关系 |
|---|---|---|
| poll_due_followup（V7.8 复盘追问） | poll_due_actions（到期汇报） | 同级信号源，优先级 action_due > followup > inactivity |
| 八步闸门 | 零修改，仅 PolicySnapshot 增字段 | 只读注入 |
| PROACTIVE_INTENTION_MAP（goal → 言语意图） | PROACTIVE_ACTION_MAP（intention → 行动类型，默认关） | 并行映射表，言语路径不变 |
| proactive_executor（send_message 执行） | ActionEngine（能力执行） | 两套执行器，投递域与执行域分离 |
| 深夜目标/静音时段（datetime.now 消费者） | 不接管（V8 时间同款纪律） | 世界/行动时间是事实输入，不接管 runtime 时钟 |

## 6. 验收底线

- `PolicySnapshot` 不传 action_facts 时，policy 输出与 V8 逐位一致（既有测试零回归）。
- `poll_due_actions` 关闭（`autonomy_action_enabled=false` 且无 due 提醒）时，自治链路与 V7.8 行为一致。
- 到期汇报全链：设提醒 → WorldEvent active → 触发器命中（幂等一次）→ 八步闸门 → 主动消息落库；V7 全部测试零回归。
- 自治产行动分支关闭时 `PROACTIVE_ACTION_MAP` 不被求值（零路径）。
