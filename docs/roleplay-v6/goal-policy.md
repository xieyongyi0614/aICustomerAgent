# Goal Policy（生命周期）

> 原则：Goal 的生死由**确定性代码**决定，LLM 不拥有创建/完成权。LLM 只在 IntentionDecision 里回答"这轮做什么"。

## 1. 创建规则（policy 触发，逐条幂等）

| 触发信号（来自既有管线） | 创建 Current Goal | 类型 |
|---|---|---|
| V5 conflict/boundary_violation 事件（tension ≥ 0.5） | 修复与用户的隔阂 | relationship |
| V5 suggest_rest 类 Intention 被执行且用户显式接受 | 劝用户休息（升级为显式目标） | user_care |
| 用户表达疲惫/压力（turn_analysis emotion∈{tired,sad,anxious}） | 陪伴用户放松 | user_care |
| V3 产生新 pending action | 完成该场景动作 | scene |
| 无以上信号且无同类型 active goal | 不创建（persistent 种子兜底） | — |

幂等：同 (user, type, description) 已有 active 行则跳过。单轮最多创建 1 条新 goal（防刷库）。

## 2. 完成规则

| Goal 类型 | 完成条件 |
|---|---|
| scene | V3 pending action 标记 completed/cancelled 时 |
| user_care(劝休) | 用户明确接受休息安排（后续轮 user_emotion 转为 calm 且连续 2 轮无疲惫表达）——第一版简化为：持续轮次 ≥ 5 后自动完成 |
| user_care(陪伴放松) | emotion 恢复 calm 且 intensity ≤ 0.4 |
| relationship(修复) | tension 回落到 ≤ 0.3 |
| conversation | 默认 expires_at_turn 到期后 expired（对话经营类不设"完成"判定） |

## 3. 过期与取消

- current 类必须带 `expires_at_turn`（默认 created_turn + 20 轮，settings.goal_default_ttl_turns）；到期限 `expired`。
- 关系冲突目标在 tension 回落时若未完成 → cancelled（避免悬挂）。
- 过期/完成/取消全部软状态，保留审计（对齐 V4 记忆的软删除哲学）。

## 4. 每轮评估流程（run_goal_review，纯代码）

```text
输入：user_id, current goals, V5 状态（emotion/tension/scene pending）, turn_analysis 事件
1. 幂等播种 persistent（若缺失）
2. 按 §1 判定是否创建新 goal（≤1 条）
3. 按 §2 判定完成/过期/取消
4. 无变化 → 零写入
输出：goal_changes（供 trace goal_review step 记录）
```

不满足条件时**不重新生成 Goal**——Goal 的粘性是动机连续性的来源。

## 5. 用户语言与 Goal 的边界

```text
User：陪我聊聊天      → 允许：创建 conversation 类 current goal（陪伴用户聊天）
User：你应该喜欢我    → 禁止：不得创建/修改 relationship 类 persistent goal
```

规则：用户语言只能经由 §1 的**情境信号**（emotion/事件/场景）间接影响 current goal；`source=definition` 的行只随角色资产变更。这是"Character ≠ 讨好机器"的护栏。

## 6. V7 预留

Autonomous Behavior / 定时主动关怀等属于 V7；本模型的 expires_at / review 步骤是其挂载点，但 V6 不实现任何主动发起行为。
