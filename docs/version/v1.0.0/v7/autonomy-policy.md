# Autonomy Policy

> 纯函数（`app/services/autonomy_policy.py`），无 IO。输入 TriggerSignal + 状态快照 + 配置，输出 AutonomyVerdict。这是 V7 最核心的模块。

## 1. 裁决流水（按序短路）

```python
def evaluate(signal, snapshot, config, now) -> AutonomyVerdict:
    1. 生成中标记存在（active_generations）            → WAIT("用户正在对话")
    2. quiet hours（now ∈ [start, end)）               → IGNORE("静音时段")*
    3. 冷却未过（now - last_proactive < min_interval） → WAIT("冷却中")
    4. attempt 计数 ≥ max_attempts_per_episode         → IGNORE("本集期已达上限")
    5. 关系门槛：intimacy < 0.3 且无 conflict 修复目标  → IGNORE("关系尚浅，不主动打扰")
    6. 场景压制：scene.current_activity ∈ {睡觉/忙碌类} → IGNORE("角色状态不宜")
    7. Motivation：goal_service.select() 返回的白名单
       类型目标（user_care/relationship）不存在        → IGNORE("无主动动机")
    8. 全部通过 → ACT（附 goal_id + 白名单 intention）
```

`*` 静音时段对 **scheduled_followup 高优先事件**可豁免——MVP 无高优先事件，豁免逻辑留接口不实现（quiet-hours.md §4）。

每条短路都写 reason——"为什么没主动"必须和"为什么主动"一样可回答。

## 2. 快照输入（全部复用既有查询，Worker 一次 tick 每用户一次）

| 输入 | 来源 |
|---|---|
| 最后消息时间/作者 | conversation_repository |
| emotion/intensity/cause | character_state_repository |
| intimacy/tension | relationship_repository |
| active goals | goal_repository（含 V6 select） |
| scene.current_activity | scene_state_repository |
| 生成中标记 | 内存 registry（chat_pipeline 置位） |
| last_proactive/attempt 计数 | proactive_actions 表聚合 |

## 3. Confidence 与门槛

MVP 不引入连续 confidence 打分——五条件门本身就是离散门槛，伪精确分数只增加不可解释性。`AutonomyVerdict` 暂不含 confidence 字段；若 V8 引入多 Trigger 竞争排序再加。

## 4. Motivation 的构成（不满足即 IGNORE）

```text
Motivation 存在 ⟺
  selected_goal.type ∈ PROACTIVE_INTENTIONS 键集
  且 selected_goal.reason 非降级
```

例：用户离开 35 分钟 + user_care"陪伴用户放松"目标 active → ACT(check_in)；
用户离开 35 分钟 + 仅 conversation 目标 → IGNORE("对话类目标不触发主动")。

## 5. 状态修正（体现"角色性格影响主动性"）

| 信号 | 修正 |
|---|---|
| intimacy ≥ 0.55 | 视为亲密：冷却间隔 × 0.5（更自然地主动关心） |
| tension > 0.5 且有修复目标 | 冷却间隔 × 0.5（主动破冰优先级高） |
| emotion.mood == "tired"（角色自己累了） | IGNORE（角色状态不宜主动） |
| 角色夜间场景（睡觉类 activity） | IGNORE（§1 第 6 条） |

修正只作用于 Worker 这一次评估，不写任何持久状态。

## 6. 可测性

Policy 是 `(signal, snapshot, config, now) → verdict` 的纯函数：全部矩阵用例（testing.md Case 1~9 的 policy 部分）直接喂构造快照断言三值输出，无需 DB/LLM。
