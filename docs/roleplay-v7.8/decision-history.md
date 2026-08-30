# M2 Decision History

> 目标：记录角色的决策过程，回答"为什么主动行为触发了 / 为什么这次没有触发 / 当轮目标为什么选了这个"。
> 针对 V6 Goal 与 V7 Autonomy：决策本身是纯函数（`autonomy_policy.evaluate` 八步裁决、`goal_service.select`），观测层只在**决策产出之后**读取结果落记录。

## 1. DecisionKind：四类决策

```text
proactive_autonomy   主动行为裁决（P0，005）——trigger → policy → action 全链
turn_goal            当轮目标选择（P1，009）
turn_intention       当轮意图决策（P1，009）
turn_behavior        当轮行为策略（P1，009，strategy/budget 摘要）
```

P0 只做 proactive_autonomy：它是"角色自主性"最容易被质疑的决策，且目前完全没有过程记录；turn 级决策已有 trace step 承载概要，明细记录放 009。

## 2. 域模型（DecisionRecord）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | uuid hex |
| kind | DecisionKind | 上表四类 |
| request_id | str \| None | 关联 trace（turn 级决策有；autonomy tick 无 HTTP 请求，为空） |
| user_id | int | |
| conversation_id | str \| None | |
| action_id | str \| None | 关联 proactive_actions（仅 proactive_autonomy 且通过裁决时） |
| trigger | str \| None | 触发源：inactivity_4h / poll_due / …；无触发（策略前置拒绝）则为空 |
| input_snapshot | dict | 决策输入摘要（有界）：静音窗口、冷却剩余、周期计数、关系分、活跃度等 policy 实际读到的值 |
| decision | str | allow / deny / enqueue / deliver / fail（按 kind 语义化枚举） |
| reason | str | 裁决依据：policy 八步链路命中的裁决步骤名 + 关键值（如 `cooldown_active, remaining=37m`） |
| confidence | float \| None | 策略未产出置信度时为 null（V7 policy 无此字段，留列不造数） |
| outcome | str \| None | 后续补写：delivered / acked / failed / expired（幂等 UPDATE，不新建行） |
| created_at | datetime | |

## 3. 采集点（全部在决策产出之后）

### proactive_autonomy（005）

```text
autonomy_engine._process_user（app/application/autonomy_engine.py:111）
  ├─ trigger_evaluator.evaluate_inactivity / poll_due   → 读取触发结果（只读）
  ├─ autonomy_policy.evaluate(...)                      → 读取裁决对象：decision + reason 链（只读）
  │     ├─ deny  → on_decision(deny, reason)            ← 没有 action_id，"为什么不主动"就靠它
  │     └─ allow → proactive_repository.enqueue         → on_decision(enqueue, action_id=…)
  └─ （60s tick 每用户只在存在触发候选时产生记录，避免每分钟噪音行）

proactive_executor.execute（app/services/proactive_executor.py:94）
  └─ transition delivered / failed 之后                  → decision_repository.mark_outcome(action_id, …)
```

采集是**读结果对象**，不改 `_process_user` 的任何控制流；policy / trigger_evaluator 文件零改动。

### turn 级（009）

chat_pipeline 在 `_select_goal` / intention / behavior_engine 步骤返回后，从 `GoalContext` / `IntentionDecision` / `BehaviorDirective` 只读提取（goal、intention 方向、strategy、budget 余量）→ `on_decision`，request_id 关联当轮 trace。同样零控制流变更。

## 4. 查询 API

| 端点 | 行为 |
|---|---|
| `GET /debug/decisions?user_id=&kind=&window=`（005） | 决策时间线；前端/人工回答"最近为什么主动 / 为什么沉默" |
| `GET /debug/proactive/{action_id}/correlation`（008） | 决策 + trace + 评估 + LLM 调用 bundle（M6 主动侧入口） |

决策记录与 evaluation 的 subject（proactive_action）经 `action_id` 互通：一次主动行为可还原为 trigger → policy → enqueue → generate → deliver → evaluate → ack 的全链时间线。

## 5. 边界

- 不给 policy 增加 confidence 之类的字段，不为观测改任何裁决逻辑；策略没有的数值就留 null。
- deny 记录是本模块的核心价值（沉默的原因同样重要），但只记"有触发候选被裁决"的 tick，不记空转。
- input_snapshot 有界（复用 step extra 上限常量），不存完整状态快照。
